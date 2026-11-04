import unittest
from datetime import datetime, timezone

from syncthing_dashboard.collector import FolderStatus
from syncthing_dashboard.model import build_overview
from tests import fixtures as fx


class BuildOverviewTest(unittest.TestCase):
    def setUp(self):
        self.ov = build_overview(fx.all_hosts(), now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_devices_ordered_hosts_first_then_unmonitored(self):
        self.assertEqual([d.name for d in self.ov.devices], ["nas", "laptop", "pi", "Phone"])
        self.assertEqual([d.monitored for d in self.ov.devices], [True, True, True, False])

    def test_unreachable_host_is_placed_by_name(self):
        pi = self.ov.device(fx.PI)
        self.assertTrue(pi.monitored)
        self.assertFalse(pi.reachable)
        self.assertEqual(pi.category, "error")
        self.assertEqual(self.ov.unplaced_hosts, [])

    def test_unreachable_host_without_name_match_is_reported(self):
        hosts = fx.all_hosts()
        hosts[2].name = "unknown-box"
        ov = build_overview(hosts)
        self.assertEqual(ov.unplaced_hosts, ["unknown-box"])
        self.assertNotIn("unknown-box", [d.name for d in ov.devices])

    def test_unmonitored_device_takes_name_and_version_from_peers(self):
        phone = self.ov.device(fx.PHONE)
        self.assertFalse(phone.monitored)
        self.assertTrue(phone.connected)
        self.assertEqual(phone.version, "v1.30.0")
        self.assertEqual(phone.category, "ok")

    def test_folders_sorted_by_label_with_union_of_members(self):
        self.assertEqual([f.label for f in self.ov.folders], ["Backup", "Documents", "Photos"])
        docs = next(f for f in self.ov.folders if f.id == "docs")
        self.assertEqual(docs.devices, [fx.NAS, fx.LAPTOP, fx.PI, fx.PHONE])

    def test_own_folder_state(self):
        cell = self.ov.cells[("docs", fx.NAS)]
        self.assertEqual((cell.state, cell.category, cell.completion, cell.need_items), ("idle", "ok", 100.0, 0))
        cell = self.ov.cells[("photos", fx.NAS)]
        self.assertEqual((cell.state, cell.category, cell.need_items), ("syncing", "syncing", 3))
        self.assertAlmostEqual(cell.completion, 75.0)

    def test_idle_with_needed_items_is_out_of_sync(self):
        hosts = fx.all_hosts()
        hosts[0].folder_status["docs"] = FolderStatus("idle", 1000, 10, 2, 0)
        cell = build_overview(hosts).cells[("docs", fx.NAS)]
        self.assertEqual((cell.state, cell.category), ("out of sync", "syncing"))

    def test_folder_errors_win(self):
        hosts = fx.all_hosts()
        hosts[0].folder_status["docs"] = FolderStatus("idle", 1000, 0, 0, 2)
        cell = build_overview(hosts).cells[("docs", fx.NAS)]
        self.assertEqual(cell.category, "error")
        self.assertIn("2 failed items", cell.detail)

    def test_offered_but_not_accepted_is_flagged(self):
        cell = self.ov.cells[("backup", fx.LAPTOP)]
        self.assertTrue(cell.flagged)
        self.assertEqual((cell.state, cell.category), ("not accepted", "flag"))
        self.assertIn("nas", cell.detail)

    def test_unreachable_host_cells_use_peer_reports(self):
        cell = self.ov.cells[("docs", fx.PI)]
        self.assertEqual((cell.state, cell.category), ("unreachable", "offline"))
        self.assertEqual(cell.completion, 40.0)
        self.assertEqual(cell.need_items, 12)
        self.assertIn("host unreachable", cell.detail)

    def test_unmonitored_device_cells(self):
        self.assertEqual(self.ov.cells[("docs", fx.PHONE)].state, "syncing")
        self.assertEqual(self.ov.cells[("docs", fx.PHONE)].completion, 90.0)
        self.assertEqual(self.ov.cells[("photos", fx.PHONE)].state, "in sync")
        self.assertNotIn(("backup", fx.PHONE), self.ov.cells)
        self.assertNotIn(("photos", fx.LAPTOP), self.ov.cells)

    def test_unmonitored_offline_device(self):
        hosts = fx.all_hosts()
        hosts[0].connections[fx.PHONE]["connected"] = False
        ov = build_overview(hosts)
        self.assertEqual(ov.device(fx.PHONE).category, "offline")
        cell = ov.cells[("docs", fx.PHONE)]
        self.assertEqual((cell.state, cell.category, cell.completion), ("offline", "offline", 90.0))

    def test_edges_from_declarations_with_state(self):
        edges = {tuple(sorted((self.ov.device(e.a).name, self.ov.device(e.b).name))): e for e in self.ov.edges}
        self.assertEqual(set(edges), {("laptop", "nas"), ("nas", "pi"), ("Phone", "nas"), ("laptop", "pi")})
        self.assertEqual(edges[("laptop", "nas")].state, "connected")
        self.assertEqual(edges[("laptop", "nas")].folders, ["backup", "docs"])
        self.assertEqual(edges[("nas", "pi")].state, "disconnected")
        self.assertEqual(edges[("Phone", "nas")].folders, ["docs", "photos"])
        # nobody reachable says that pi and Phone share anything, so no edge
        self.assertNotIn(("Phone", "pi"), edges)

    def test_paused_edge(self):
        hosts = fx.all_hosts()
        hosts[0].connections[fx.PI]["paused"] = True
        hosts[1].connections[fx.PI]["paused"] = True
        ov = build_overview(hosts)
        edge = next(e for e in ov.edges if {e.a, e.b} == {fx.NAS, fx.PI})
        self.assertEqual(edge.state, "paused")

    def test_all_hosts_down(self):
        hosts = [fx.pi_down()]
        ov = build_overview(hosts)
        self.assertEqual(ov.devices, [])
        self.assertEqual(ov.folders, [])
        self.assertEqual(ov.unplaced_hosts, ["pi"])


if __name__ == "__main__":
    unittest.main()
