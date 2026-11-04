import re
import unittest
from datetime import datetime, timezone

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


if __name__ == "__main__":
    unittest.main()
