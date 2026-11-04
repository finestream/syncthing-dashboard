"""Hand-built snapshots of a small network, used by the unit tests.

Device IDs are placeholders in the Syncthing format; nothing here is real.
"""

from syncthing_dashboard.collector import Completion, FolderStatus, HostSnapshot

NAS = "AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA"
LAPTOP = "BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB"
PI = "CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC"
PHONE = "DDDDDDD-DDDDDDD-DDDDDDD-DDDDDDD-DDDDDDD-DDDDDDD-DDDDDDD-DDDDDDD"


def nas() -> HostSnapshot:
    return HostSnapshot(
        name="nas", url="https://nas.example.internal:8384", reachable=True, my_id=NAS, version="v2.0.0",
        devices={
            NAS: {"name": "nas", "paused": False, "addresses": ["dynamic"]},
            LAPTOP: {"name": "laptop", "paused": False, "addresses": ["dynamic"]},
            PI: {"name": "pi", "paused": False, "addresses": ["dynamic"]},
            PHONE: {"name": "Phone", "paused": False, "addresses": ["dynamic"]},
        },
        folders={
            "docs": {"label": "Documents", "path": "/data/docs", "type": "sendreceive", "paused": False,
                     "devices": [NAS, LAPTOP, PI, PHONE]},
            "photos": {"label": "Photos", "path": "/data/photos", "type": "receiveonly", "paused": False,
                       "devices": [NAS, PHONE]},
            "backup": {"label": "Backup", "path": "/data/backup", "type": "sendreceive", "paused": False,
                       "devices": [NAS, LAPTOP]},
        },
        connections={
            LAPTOP: {"connected": True, "paused": False, "address": "", "clientVersion": "v2.0.0"},
            PI: {"connected": False, "paused": False, "address": "", "clientVersion": ""},
            PHONE: {"connected": True, "paused": False, "address": "", "clientVersion": "v1.30.0"},
        },
        folder_status={
            "docs": FolderStatus("idle", 1000, 0, 0, 0),
            "photos": FolderStatus("syncing", 2000, 500, 3, 0),
            "backup": FolderStatus("idle", 100, 0, 0, 0),
        },
        completion={
            ("docs", LAPTOP): Completion(100.0, 0, 0, "valid"),
            ("docs", PI): Completion(40.0, 12, 600, "valid"),
            ("docs", PHONE): Completion(90.0, 1, 100, "valid"),
            ("photos", PHONE): Completion(100.0, 0, 0, "valid"),
            ("backup", LAPTOP): Completion(100.0, 0, 0, "notSharing"),
        },
        system_errors=0,
    )


def laptop() -> HostSnapshot:
    return HostSnapshot(
        name="laptop", url="http://192.0.2.10:8384", reachable=True, my_id=LAPTOP, version="v2.0.0",
        devices={
            LAPTOP: {"name": "laptop", "paused": False, "addresses": ["dynamic"]},
            NAS: {"name": "nas", "paused": False, "addresses": ["dynamic"]},
            PI: {"name": "pi", "paused": False, "addresses": ["dynamic"]},
        },
        folders={
            "docs": {"label": "Documents", "path": "~/docs", "type": "sendreceive", "paused": False,
                     "devices": [LAPTOP, NAS, PI]},
        },
        connections={
            NAS: {"connected": True, "paused": False, "address": "", "clientVersion": "v2.0.0"},
            PI: {"connected": False, "paused": False, "address": "", "clientVersion": ""},
        },
        folder_status={"docs": FolderStatus("idle", 1000, 0, 0, 0)},
        completion={
            ("docs", NAS): Completion(100.0, 0, 0, "valid"),
            ("docs", PI): Completion(40.0, 12, 600, "valid"),
        },
        pending_folders={"backup": {"label": "Backup", "offered_by": [NAS]}},
    )


def pi_down() -> HostSnapshot:
    return HostSnapshot(name="pi", url="https://pi.example.internal:8384", reachable=False,
                        error="/rest/system/status: timed out after 5s")


def all_hosts() -> list[HostSnapshot]:
    return [nas(), laptop(), pi_down()]
