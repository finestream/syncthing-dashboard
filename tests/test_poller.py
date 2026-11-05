import threading
import unittest
import urllib.request

from syncthing_dashboard.cli import Server, make_handler
from syncthing_dashboard.collector import HostSnapshot
from syncthing_dashboard.config import HostConfig
from syncthing_dashboard.poller import Poller
from tests import fixtures as fx


def host(name: str) -> HostConfig:
    return HostConfig(name=name, url=f"http://{name}.example.internal:8384", api_key="key")


class FakeCollect:
    """Stands in for ``collect_host``; a poll of a host blocks until that host is released."""

    def __init__(self):
        self.gates = {}
        self.calls = []
        self.lock = threading.Lock()
        self.done = threading.Semaphore(0)

    def gate(self, name: str) -> threading.Event:
        with self.lock:
            return self.gates.setdefault(name, threading.Event())

    def __call__(self, cfg: HostConfig, timeout: float) -> HostSnapshot:
        with self.lock:
            self.calls.append(cfg.name)
        self.gate(cfg.name).wait(10)
        return HostSnapshot(name=cfg.name, url=cfg.url, reachable=True, my_id=cfg.name)

    def release(self, poller: Poller, name: str) -> None:
        self.gate(name).set()
        for _ in range(1000):
            if any(s.host.name == name and not s.running for s in poller._states):
                return
            threading.Event().wait(0.01)
        raise AssertionError(f"poll of {name} did not finish")


class PollerTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.collect = FakeCollect()
        self.poller = Poller([host("a"), host("b")], max_age=30, collect=self.collect, clock=lambda: self.now)
        self.addCleanup(lambda: [g.set() for g in self.collect.gates.values()])

    def by_name(self):
        return {s.name: s for s in self.poller.snapshots()}

    def test_without_answers_every_host_is_contacting(self):
        self.poller.poll_due()
        snaps = self.poller.snapshots()
        self.assertEqual([s.name for s in snaps], ["a", "b"])
        self.assertTrue(all(s.contacting and s.awaiting_answer for s in snaps))

    def test_a_slow_host_does_not_hold_up_another(self):
        self.poller.poll_due()
        self.collect.release(self.poller, "a")
        snaps = self.by_name()
        self.assertTrue(snaps["a"].reachable)
        self.assertFalse(snaps["a"].contacting)
        self.assertIsNotNone(snaps["a"].polled_at)
        self.assertTrue(snaps["b"].awaiting_answer)

    def test_polls_only_when_due_and_never_twice_at_once(self):
        self.poller.poll_due()
        self.now += 100
        self.poller.poll_due()  # both still running
        self.collect.release(self.poller, "a")
        self.collect.release(self.poller, "b")
        self.assertEqual(sorted(self.collect.calls), ["a", "b"])
        self.poller.poll_due()  # started 100 s ago: due
        self.collect.release(self.poller, "a")
        self.collect.release(self.poller, "b")
        self.assertEqual(sorted(self.collect.calls), ["a", "a", "b", "b"])
        self.now += 29
        self.poller.poll_due()  # not due
        self.assertEqual(len(self.collect.calls), 4)

    def test_contacting_only_when_data_is_out_of_date(self):
        self.poller.poll_due()
        self.collect.release(self.poller, "a")
        self.collect.release(self.poller, "b")
        self.collect.gate("a").clear()

        self.now += 30  # routine poll: the old data is still good
        self.poller.poll_due()
        self.assertFalse(self.by_name()["a"].contacting)

        self.now += 31  # older than two intervals while that poll runs
        snap = self.by_name()["a"]
        self.assertTrue(snap.contacting)
        self.assertTrue(snap.reachable)  # the old data stays on the page
        self.assertFalse(snap.awaiting_answer)

        self.collect.release(self.poller, "a")
        self.assertFalse(self.by_name()["a"].contacting)

    def test_a_failing_poll_becomes_an_unreachable_host(self):
        def explode(cfg, timeout):
            raise ValueError("unexpected")

        poller = Poller([host("a")], collect=explode)
        with self.assertLogs("syncthing_dashboard.poller", "ERROR"):
            poller.poll_due()
            for _ in range(1000):
                if not poller._states[0].running:
                    break
                threading.Event().wait(0.01)
        snap = poller.snapshots()[0]
        self.assertFalse(snap.reachable)
        self.assertFalse(snap.contacting)
        self.assertIn("polling failed", snap.error)


class ServeWhilePollingTest(unittest.TestCase):
    def test_page_answers_while_every_host_is_still_polling(self):
        collect = FakeCollect()
        self.addCleanup(lambda: [g.set() for g in collect.gates.values()])
        poller = Poller([host("a")], collect=collect)
        server = Server(("127.0.0.1", 0), make_handler(poller, 30, "Test"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/"

        with urllib.request.urlopen(url, timeout=5) as resp:
            page = resp.read().decode()
        self.assertIn("contacting server…", page)
        self.assertIn('<meta http-equiv="refresh" content="2">', page)

        collect.release(poller, "a")
        with urllib.request.urlopen(url, timeout=5) as resp:
            page = resp.read().decode()
        self.assertNotIn("contacting server…", page)
        self.assertIn('<meta http-equiv="refresh" content="30">', page)


if __name__ == "__main__":
    unittest.main()
