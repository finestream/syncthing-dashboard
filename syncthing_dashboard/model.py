"""Merge the per-host snapshots into one picture of the network.

Device IDs are the identity. A reachable host is the device whose ID it
reports; an unreachable host is found by its name in a peer's device list.
Every other device a host lists is *unmonitored*: it is shown with what the
monitored hosts report about it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .collector import FolderStatus, HostSnapshot

# Syncthing folder state -> page category. Categories are the CSS classes of the page.
_STATE_CATEGORY = {
    "idle": "ok",
    "scanning": "scanning",
    "scan-waiting": "scanning",
    "syncing": "syncing",
    "sync-preparing": "syncing",
    "sync-waiting": "syncing",
    "cleaning": "syncing",
    "clean-waiting": "syncing",
    "error": "error",
    "paused": "paused",
}


@dataclass
class Device:
    id: str
    name: str
    monitored: bool  # listed in hosts.toml
    reachable: bool | None = None  # monitored devices only
    host_name: str | None = None  # name in hosts.toml, monitored devices only
    url: str = ""  # GUI address, monitored devices only
    version: str = ""
    connected: bool = False  # at least one reachable host is connected to it
    paused: bool = False  # paused on every reachable host that knows it
    error: str = ""  # why the host is unreachable
    folder_count: int = 0

    @property
    def category(self) -> str:
        if self.monitored:
            return "ok" if self.reachable else "error"
        if self.paused:
            return "paused"
        return "ok" if self.connected else "offline"

    @property
    def status_text(self) -> str:
        if self.monitored:
            return "reachable" if self.reachable else "unreachable"
        if self.paused:
            return "paused"
        return "connected" if self.connected else "not connected"


@dataclass
class Edge:
    a: str  # device IDs
    b: str
    folders: list[str]  # folder IDs, sorted by label
    state: str  # connected, disconnected, paused, unknown


@dataclass
class Cell:
    state: str  # shown in the cell: idle, syncing, out of sync, not accepted, ...
    category: str  # ok, syncing, scanning, error, paused, offline, flag, unknown
    completion: float | None = None  # percent
    need_items: int | None = None
    detail: str = ""  # tooltip
    flagged: bool = False  # offered to a monitored host that has not accepted it


@dataclass
class Folder:
    id: str
    label: str
    type: str = ""
    devices: list[str] = field(default_factory=list)  # device IDs that have or were offered it, page order


@dataclass
class Overview:
    generated_at: datetime
    hosts: list[HostSnapshot]
    devices: list[Device]  # monitored hosts in configuration order, then the rest by name
    edges: list[Edge]
    folders: list[Folder]  # by label
    cells: dict[tuple[str, str], Cell]  # (folder ID, device ID) -> cell
    unplaced_hosts: list[str] = field(default_factory=list)  # unreachable hosts with no device ID

    def device(self, device_id: str) -> Device:
        return next(d for d in self.devices if d.id == device_id)


def build_overview(hosts: list[HostSnapshot], now: datetime | None = None) -> Overview:
    reachable = [h for h in hosts if h.reachable]
    host_ids = _host_ids(hosts)
    host_of = {host_ids[h.name]: h for h in hosts if h.name in host_ids}  # device ID -> its host

    devices = _devices(hosts, reachable, host_ids)
    folders = _folders(reachable, devices)

    ordered = [devices[host_ids[h.name]] for h in hosts if h.name in host_ids]
    ordered += sorted((d for d in devices.values() if not d.monitored), key=lambda d: d.name.casefold())
    order = {d.id: i for i, d in enumerate(ordered)}
    for folder in folders.values():
        folder.devices.sort(key=order.__getitem__)
    for dev in ordered:
        dev.folder_count = sum(dev.id in f.devices for f in folders.values())

    cells = {
        (f.id, dev_id): _cell(f.id, devices[dev_id], host_of, reachable)
        for f in folders.values()
        for dev_id in f.devices
    }
    return Overview(
        generated_at=now or datetime.now(timezone.utc),
        hosts=hosts,
        devices=ordered,
        edges=_edges(reachable, host_of, folders, order),
        folders=sorted(folders.values(), key=lambda f: f.label.casefold()),
        cells=cells,
        unplaced_hosts=[h.name for h in hosts if h.name not in host_ids],
    )


# --- building blocks ----------------------------------------------------------


def _host_ids(hosts: list[HostSnapshot]) -> dict[str, str]:
    """Host name -> device ID.

    A reachable host reports its own ID. An unreachable one is matched by a
    device of the same name (case-insensitive) in any other host's device list.
    A host that matches neither way is left out and reported as unplaced.
    """
    ids = {h.name: h.my_id for h in hosts if h.reachable and h.my_id}
    for h in hosts:
        if h.name in ids:
            continue
        wanted = h.name.casefold()
        for other in hosts:
            match = next(
                (dev_id for dev_id, dev in other.devices.items()
                 if dev_id not in ids.values() and str(dev.get("name", "")).casefold() == wanted),
                None,
            )
            if match:
                ids[h.name] = match
                break
    return ids


def _devices(hosts: list[HostSnapshot], reachable: list[HostSnapshot], host_ids: dict[str, str]) -> dict[str, Device]:
    """Device ID -> Device: the monitored hosts first, then everything the reachable hosts list."""
    devices = {
        host_ids[h.name]: Device(
            id=host_ids[h.name], name=h.name, monitored=True, reachable=h.reachable,
            host_name=h.name, url=h.url, version=h.version, error=h.error,
        )
        for h in hosts
        if h.name in host_ids
    }
    names: dict[str, Counter[str]] = {}  # unmonitored device ID -> names used for it, by frequency
    paused: dict[str, list[bool]] = {}
    for h in reachable:
        for dev_id, dev in h.devices.items():
            if dev_id == h.my_id or dev_id in devices and devices[dev_id].monitored:
                continue
            devices.setdefault(dev_id, Device(id=dev_id, name="", monitored=False))
            names.setdefault(dev_id, Counter())[str(dev.get("name") or dev_id[:7])] += 1
            paused.setdefault(dev_id, []).append(bool(dev.get("paused")))
    for dev_id, dev in devices.items():
        if not dev.monitored:
            dev.name = names[dev_id].most_common(1)[0][0]
            dev.paused = all(paused[dev_id])
        for h in reachable:
            conn = h.connections.get(dev_id, {})
            if conn.get("connected"):
                dev.connected = True
                if not dev.monitored:
                    dev.version = conn.get("clientVersion") or dev.version
    return devices


def _folders(reachable: list[HostSnapshot], devices: dict[str, Device]) -> dict[str, Folder]:
    """Folder ID -> Folder with every device that has it or was offered it (unordered)."""
    folders: dict[str, Folder] = {}
    for h in reachable:
        for folder_id, f in h.folders.items():
            folder = folders.setdefault(folder_id, Folder(id=folder_id, label=f["label"], type=f["type"]))
            if folder.label == folder_id and f["label"] != folder_id:  # a later host knows a nicer label
                folder.label = f["label"]
            for dev_id in [h.my_id, *f["devices"]]:
                if dev_id not in folder.devices:
                    folder.devices.append(dev_id)
                devices.setdefault(dev_id, Device(id=dev_id, name=dev_id[:7], monitored=False))
    return folders


def _edges(
    reachable: list[HostSnapshot], host_of: dict[str, HostSnapshot], folders: dict[str, Folder], order: dict[str, int]
) -> list[Edge]:
    """One edge per pair of devices for which a reachable host declares a shared folder.

    Two unmonitored devices never get an edge: no host can say whether they share anything.
    """
    pairs: dict[tuple[str, str], list[str]] = {}
    for h in reachable:
        for folder_id, f in h.folders.items():
            for dev_id in f["devices"]:
                if dev_id == h.my_id:
                    continue
                a, b = sorted((h.my_id, dev_id), key=order.__getitem__)
                shared = pairs.setdefault((a, b), [])
                if folder_id not in shared:
                    shared.append(folder_id)
    return [
        Edge(a, b, sorted(ids, key=lambda i: folders[i].label.casefold()), _edge_state(a, b, host_of))
        for (a, b), ids in pairs.items()
    ]


def _edge_state(a: str, b: str, host_of: dict[str, HostSnapshot]) -> str:
    """Connection state between two devices, from whichever of them is a reachable host."""
    verdicts = []
    for me, other in ((a, b), (b, a)):
        host = host_of.get(me)
        if host is None or not host.reachable:
            continue
        conn = host.connections.get(other, {})
        if conn.get("connected"):
            verdicts.append("connected")
        elif conn.get("paused") or host.devices.get(other, {}).get("paused"):
            verdicts.append("paused")
        else:
            verdicts.append("disconnected")
    return next((s for s in ("connected", "paused", "disconnected") if s in verdicts), "unknown")


def _percent(status: FolderStatus) -> float:
    if status.global_bytes <= 0:
        return 100.0
    done = status.global_bytes - status.need_bytes
    return max(0.0, min(100.0, 100.0 * done / status.global_bytes))


def _cell(folder_id: str, dev: Device, host_of: dict[str, HostSnapshot], reachable: list[HostSnapshot]) -> Cell:
    """The matrix cell for one folder on one device."""
    host = host_of.get(dev.id)
    if host is not None and host.reachable:
        if folder_id in host.folders:
            return _own_cell(host.folder_status.get(folder_id))
        return _not_accepted_cell(folder_id, dev, host, host_of, reachable)
    return _remote_cell(folder_id, dev, reachable)


def _own_cell(st: FolderStatus | None) -> Cell:
    """A reachable host's own view of its folder (``/rest/db/status``)."""
    if st is None:
        return Cell("unknown", "unknown")
    if st.error or st.errors:
        return Cell("error", "error", _percent(st), st.need_items, st.error or f"{st.errors} failed items")
    if st.state == "idle" and st.need_items > 0:
        return Cell("out of sync", "syncing", _percent(st), st.need_items)
    return Cell(st.state, _STATE_CATEGORY.get(st.state, "unknown"), _percent(st), st.need_items)


def _not_accepted_cell(
    folder_id: str, dev: Device, host: HostSnapshot, host_of: dict[str, HostSnapshot], reachable: list[HostSnapshot]
) -> Cell:
    """A folder another device shares with this reachable host, which has not accepted it."""
    pending = host.pending_folders.get(folder_id)
    if pending:  # the host itself lists the offer
        offered_by = {host_of[o].name if o in host_of else o[:7] for o in pending["offered_by"]}
    else:  # fall back to the hosts that declare the share
        offered_by = {h.name for h in reachable if dev.id in h.folders.get(folder_id, {}).get("devices", [])}
    return Cell("not accepted", "flag", detail="offered by " + ", ".join(sorted(offered_by)), flagged=True)


def _remote_cell(folder_id: str, dev: Device, reachable: list[HostSnapshot]) -> Cell:
    """What the reachable hosts report about this device's copy (``/rest/db/completion``).

    Used for unmonitored devices and for unreachable hosts. The report of a host
    that is connected to the device wins over a stale one.
    """
    reports = []
    for h in reachable:
        c = h.completion.get((folder_id, dev.id))
        if c is not None:
            connected = bool(h.connections.get(dev.id, {}).get("connected"))
            reports.append((connected, c.remote_state == "valid", c, h.name))
    if not reports:
        if dev.monitored:
            return Cell("unreachable", "offline", detail=dev.error)
        return Cell("unknown", "unknown", detail="no host reports about this device")
    connected, _, c, via = max(reports, key=lambda r: r[:2])
    detail = f"host unreachable; as seen by {via}" if dev.monitored else f"as seen by {via}"
    if c.remote_state == "notSharing":
        return Cell("not sharing", "flag", detail=f"device does not share this folder back ({detail})")
    if c.remote_state == "paused":
        return Cell("paused", "paused", c.completion, c.need_items, detail)
    if not connected:
        return Cell("unreachable" if dev.monitored else "offline", "offline", c.completion, c.need_items, f"last known, {detail}")
    if c.completion >= 100.0 and c.need_items == 0:
        return Cell("in sync", "ok", 100.0, 0, detail)
    return Cell("syncing", "syncing", c.completion, c.need_items, detail)
