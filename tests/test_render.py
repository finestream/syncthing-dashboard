import re
import unittest
from datetime import datetime, timedelta, timezone

from syncthing_dashboard.collector import HostSnapshot
from syncthing_dashboard.model import build_overview
from syncthing_dashboard.render import render
from tests import fixtures as fx


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.ov = build_overview(fx.all_hosts(), now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
        self.html = render(self.ov, refresh=30)

    def test_self_contained(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertNotIn("<script", self.html)
        self.assertNotIn("<link", self.html)
        self.assertNotRegex(self.html, r'src="https?://')
        self.assertIn('<meta http-equiv="refresh" content="30">', self.html)
        self.assertNotIn("http-equiv", render(self.ov))

    def test_host_strip(self):
        self.assertIn('<span class="badge ok">reachable</span>', self.html)
        self.assertIn('<span class="badge error">unreachable</span>', self.html)
        self.assertIn("timed out after 5s", self.html)
        self.assertIn("1 / 2 connected", self.html)  # laptop: nas connected, pi not
        self.assertIn("2 / 3 connected", self.html)  # nas: laptop and Phone connected, pi not

    def test_topology_and_matrix(self):
        self.assertEqual(len(re.findall(r'<line class="edge ', self.html)), 4)
        self.assertEqual(len(re.findall(r'<g class="node ', self.html)), 4)
        self.assertIn("not accepted", self.html)
        self.assertIn('class="cell flag"', self.html)
        self.assertIn("as seen by nas", self.html)

    def test_state_colours_apply(self):
        # Regression: a base rule more specific than ".cell.<state>" hid every state colour.
        css = self.html.split("<style>")[1].split("</style>")[0]
        self.assertIn("\n.matrix .cell { border-left: 5px", css)
        for category in ("ok", "syncing", "scanning", "error", "paused", "offline", "flag"):
            self.assertIn(f"\n.matrix .cell.{category} {{ border-left-color: var(--{category})", css)
        # nothing more specific than ".matrix .cell" may touch a td's border
        self.assertNotRegex(css, r"\n(\.[a-z-]+ ){2,}td[^{]*\{[^}]*border")
        for category in ("ok", "error", "paused", "offline"):
            self.assertIn(f".node.{category} circle {{ fill:", css)

    def test_links_to_gui(self):
        self.assertIn('<a href="https://nas.example.internal:8384" title="Open the Syncthing GUI">nas', self.html)
        # column header of a monitored device links, an unmonitored one does not
        self.assertIn('<th><a href="http://192.0.2.10:8384" title="Open the Syncthing GUI">laptop</a>', self.html)
        self.assertIn("<th>Phone<span", self.html)

    def test_escaping(self):
        hosts = fx.all_hosts()
        hosts[0].devices[fx.PHONE]["name"] = '<img src=x onerror="alert(1)">'
        hosts[0].folders["docs"]["label"] = "Docs & <b>stuff</b>"
        html = render(build_overview(hosts))
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img src=x", html)
        self.assertIn("Docs &amp; &lt;b&gt;stuff&lt;/b&gt;", html)

    def test_api_key_never_in_page(self):
        self.assertNotIn("X-API-Key", self.html)

    def test_empty_overview(self):
        html = render(build_overview([fx.pi_down()]))
        self.assertIn("No devices known", html)
        self.assertIn("No folders known", html)
        self.assertIn("not shown in the graph or matrix: pi", html)

    def test_contacting_host(self):
        hosts = fx.all_hosts()
        hosts[2] = HostSnapshot(name="pi", url=hosts[2].url, contacting=True)
        html = render(build_overview(hosts), refresh=30)
        self.assertIn('<span class="badge contacting">contacting server…</span>', html)
        self.assertIn('<div class="host contacting">', html)
        self.assertNotIn('class="badge error"', html)
        self.assertIn("contacting 1 of 3 servers…", html)
        self.assertIn('<meta http-equiv="refresh" content="2">', html)
        self.assertNotIn('content="30"', html)

    def test_reload_while_contacting_even_without_timed_refresh(self):
        html = render(build_overview([HostSnapshot(name="pi", url="http://pi", contacting=True)]))
        self.assertIn('<meta http-equiv="refresh" content="2">', html)
        self.assertIn("Waiting for the servers to answer…", html)
        self.assertNotIn("No devices known", html)
        self.assertNotIn("not shown in the graph", html)

    def test_old_data_stays_visible_while_contacting(self):
        hosts = fx.all_hosts()
        hosts[0].contacting = True
        html = render(build_overview(hosts))
        self.assertIn('<span class="badge ok">reachable</span>', html)
        self.assertIn('<div class="host-contacting">contacting server…</div>', html)
        self.assertIn('<meta http-equiv="refresh" content="2">', html)

    def test_age_of_the_data(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        hosts = fx.all_hosts()
        hosts[0].polled_at = now - timedelta(seconds=12)
        hosts[1].polled_at = now - timedelta(minutes=5)
        html = render(build_overview(hosts, now=now))
        self.assertIn("<dt>Updated</dt><dd>12 s ago</dd>", html)
        self.assertIn("<dt>Updated</dt><dd>5 min ago</dd>", html)
        self.assertNotIn("<dt>Updated</dt>", self.html)  # one-shot page: no poller, no age


if __name__ == "__main__":
    unittest.main()
