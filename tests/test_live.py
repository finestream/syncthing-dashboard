"""Live test against the local Syncthing network of ``tests/live/harness.py``.

Skipped unless ``python -m tests.live.harness up`` has been run. Writes the
rendered page to ``tests/live/run/overview.html`` so it can be opened in a browser.
"""

import json
import time
import unittest
from pathlib import Path

from syncthing_dashboard.collector import collect_all
from syncthing_dashboard.config import load_hosts
from syncthing_dashboard.model import build_overview
from syncthing_dashboard.poller import Poller
from syncthing_dashboard.render import render

RUN = Path(__file__).resolve().parent / "live" / "run"


@unittest.skipUnless((RUN / "hosts.toml").exists(), "live network not running: python -m tests.live.harness up")
class LiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ids = json.loads((RUN / "ids.json").read_text())
        cls.hosts = load_hosts(RUN / "hosts.toml")
        cls.snaps = collect_all(cls.hosts, timeout=5)
        cls.ov = build_overview(cls.snaps)
        cls.html = render(cls.ov)
        (RUN / "overview.html").write_text(cls.html)

    def cell(self, folder, device):
        return self.ov.cells[(folder, self.ids[device])]

    def test_hosts(self):
        by_name = {s.name: s for s in self.snaps}
        self.assertTrue(by_name["alpha"].reachable)
        self.assertTrue(by_name["beta"].reachable)
        self.assertFalse(by_name["gamma"].reachable)
        self.assertEqual(by_name["alpha"].my_id, self.ids["alpha"])
        self.assertEqual(by_name["alpha"].connected_peers, 1)
        self.assertIn("offered", by_name["beta"].pending_folders)

    def test_devices(self):
        names = [d.name for d in self.ov.devices]
        self.assertEqual(names, ["alpha", "beta", "gamma", "phone"])
        gamma = self.ov.device(self.ids["gamma"])
        self.assertTrue(gamma.monitored)
        self.assertFalse(gamma.reachable)
        phone = self.ov.device(self.ids["phone"])
        self.assertFalse(phone.monitored)
        self.assertFalse(phone.connected)
        self.assertEqual(self.ov.unplaced_hosts, [])

    def test_matrix(self):
        self.assertEqual([f.id for f in self.ov.folders], ["beta-gamma", "offered", "pair-ab", "shared-all"])
        self.assertEqual(self.cell("shared-all", "alpha").category, "ok")
        self.assertEqual(self.cell("shared-all", "beta").category, "ok")
        self.assertEqual(self.cell("shared-all", "alpha").completion, 100.0)
        gamma = self.cell("shared-all", "gamma")
        self.assertEqual((gamma.state, gamma.category, gamma.completion), ("unreachable", "offline", 100.0))
        phone = self.cell("shared-all", "phone")
        self.assertEqual((phone.state, phone.completion, phone.need_items), ("offline", 0.0, 3))
        offered = self.cell("offered", "beta")
        self.assertTrue(offered.flagged)
        self.assertEqual(offered.state, "not accepted")
        self.assertIn("alpha", offered.detail)
        self.assertNotIn(("pair-ab", self.ids["gamma"]), self.ov.cells)
        self.assertNotIn(("beta-gamma", self.ids["alpha"]), self.ov.cells)

    def test_edges(self):
        edges = {frozenset((self.ov.device(e.a).name, self.ov.device(e.b).name)): e for e in self.ov.edges}
        self.assertEqual(edges[frozenset({"alpha", "beta"})].state, "connected")
        self.assertEqual(len(edges[frozenset({"alpha", "beta"})].folders), 3)
        self.assertEqual(edges[frozenset({"alpha", "gamma"})].state, "disconnected")
        self.assertEqual(edges[frozenset({"beta", "gamma"})].folders, ["beta-gamma", "shared-all"])
        self.assertNotIn(frozenset({"gamma", "phone"}), edges)

    def test_page(self):
        self.assertIn("2 of 3 hosts reachable", self.html)
        self.assertIn("not accepted", self.html)
        self.assertNotIn("<script", self.html)
        for host in self.hosts:
            self.assertNotIn(host.api_key, self.html)

    def test_background_poller(self):
        poller = Poller(self.hosts, timeout=5)
        poller.poll_due()
        deadline = time.monotonic() + 30
        while any(s.contacting for s in poller.snapshots()) and time.monotonic() < deadline:
            time.sleep(0.1)
        by_name = {s.name: s for s in poller.snapshots()}
        self.assertFalse(any(s.contacting for s in by_name.values()))
        self.assertTrue(by_name["alpha"].reachable)
        self.assertFalse(by_name["gamma"].reachable)


if __name__ == "__main__":
    unittest.main()
