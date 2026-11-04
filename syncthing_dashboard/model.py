"""Merge the per-host snapshots into one picture of the network.

Device IDs are the identity; names come from ``hosts.toml`` for monitored
hosts and from the other hosts' configurations for everything else.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .collector import HostSnapshot

# Syncthing folder states -> page categories (CSS classes)
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
    "unknown": "unknown",
}


@dataclass
class Device:
    id: str
    name: str
    monitored: bool
    reachable: bool | None = None  # None for unmonitored devices
    host_name: str | None = None
    version: str = ""
    connected: bool = False  # some monitored host is connected to it
    paused: bool = False  # paused on every monitored host that knows it
    error: str = ""
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
    a: str  # device ID
    b: str
    folders: list[str]  # folder IDs
    state: str  # connected, disconnected, paused, unknown


@dataclass
class Cell:
    state: str  # human readable: idle, syncing, scanning, error, paused, out of sync, not accepted, ...
    category: str  # ok, syncing, scanning, error, paused, unknown, offline, flag
    completion: float | None = None
    need_items: int | None = None
    detail: str = ""
    flagged: bool = False  # offered to a monitored host that has not accepted it


@dataclass
class Folder:
    id: str
    label: str
    type: str = ""
    devices: list[str] = field(default_factory=list)  # device IDs, in page order


@dataclass
class Overview:
    generated_at: datetime
    hosts: list[HostSnapshot]
    devices: list[Device]
    edges: list[Edge]
    folders: list[Folder]
    cells: dict[tuple[str, str], Cell]
    # monitored hosts for which no device ID could be found (unreachable and never named elsewhere)
    unplaced_hosts: list[str] = field(default_factory=list)

    def device(self, device_id: str) -> Device:
        return next(d for d in self.devices if d.id == device_id)


def _percent(global_bytes: int, need_bytes: int) -> float:
    if global_bytes <= 0:
        return 100.0
    return max(0.0, min(100.0, 100.0 * (global_bytes - need_bytes) / global_bytes))


def _resolve_host_ids(hosts: list[HostSnapshot]) -> dict[str, str]:
    """Map host name -> device ID. Unreachable hosts are matched by their configured name."""
    ids: dict[str, str] = {}
    for h in hosts:
        if h.reachable and h.my_id:
            ids[h.name] = h.my_id
    for h in hosts:
        if h.name in ids:
            continue
        wanted = h.name.casefold()
        for other in hosts:
            for dev_id, dev in other.devices.items():
                if dev_id in ids.values():
                    continue
                if str(dev.get("name", "")).casefold() == wanted:
                    ids[h.name] = dev_id
                    break
            if h.name in ids:
                break
    return ids


def build_overview(hosts: list[HostSnapshot], now: datetime | None = None) -> Overview:
    now = now or datetime.now(timezone.utc)
    reachable = [h for h in hosts if h.reachable]
    host_ids = _resolve_host_ids(hosts)
    id_to_host = {dev_id: name for name, dev_id in host_ids.items()}
    host_by_name = {h.name: h for h in hosts}

    # --- devices ---------------------------------------------------------
    devices: dict[str, Device] = {}
    for h in hosts:
        dev_id = host_ids.get(h.name)
        if dev_id is None:
            continue
        devices[dev_id] = Device(
            id=dev_id,
            name=h.name,
            monitored=True,
            reachable=h.reachable,
            host_name=h.name,
            version=h.version,
            error=h.error,
        )
    names: dict[str, Counter[str]] = {}
    paused_votes: dict[str, list[bool]] = {}
    for h in reachable:
        for dev_id, dev in h.devices.items():
            if dev_id == h.my_id:
                continue
            names.setdefault(dev_id, Counter())[str(dev.get("name") or dev_id[:7])] += 1
            paused_votes.setdefault(dev_id, []).append(bool(dev.get("paused")))
            if dev_id not in devices:
                devices[dev_id] = Device(id=dev_id, name="", monitored=False)
    for dev_id, dev in devices.items():
        if not dev.monitored:
            dev.name = names[dev_id].most_common(1)[0][0] if dev_id in names else dev_id[:7]
            votes = paused_votes.get(dev_id, [])
            dev.paused = bool(votes) and all(votes)
        for h in reachable:
            conn = h.connections.get(dev_id)
            if conn and conn.get("connected"):
                dev.connected = True
                if not dev.monitored and conn.get("clientVersion"):
                    dev.version = conn["clientVersion"]

    # --- folders ---------------------------------------------------------
    folders: dict[str, Folder] = {}
    shared_with: dict[str, set[str]] = {}  # folder ID -> device IDs that have it or are offered it
    for h in reachable:
        for folder_id, f in h.folders.items():
            folder = folders.setdefault(folder_id, Folder(id=folder_id, label=f["label"], type=f["type"]))
            if folder.label == folder_id and f["label"] != folder_id:
                folder.label = f["label"]
            members = shared_with.setdefault(folder_id, set())
            members.add(h.my_id)
            members.update(f["devices"])
    for folder_id, members in shared_with.items():
        for dev_id in members:
            if dev_id not in devices:
                devices[dev_id] = Device(id=dev_id, name=dev_id[:7], monitored=False)

    # page order: monitored hosts in configuration order, then the rest by name
    ordered: list[Device] = []
    for h in hosts:
        dev_id = host_ids.get(h.name)
        if dev_id is not None:
            ordered.append(devices[dev_id])
    ordered.extend(sorted((d for d in devices.values() if not d.monitored), key=lambda d: d.name.casefold()))
    order_index = {d.id: i for i, d in enumerate(ordered)}
    for folder in folders.values():
        folder.devices = sorted(shared_with[folder.id], key=order_index.__getitem__)
    for dev in ordered:
        dev.folder_count = sum(1 for f in folders.values() if dev.id in f.devices)

    # --- cells -------------------------------------------------------------
    cells: dict[tuple[str, str], Cell] = {}
    for folder in sorted(folders.values(), key=lambda f: f.label.casefold()):
        for dev_id in folder.devices:
            dev = devices[dev_id]
            cells[(folder.id, dev_id)] = _cell(folder.id, dev, id_to_host, host_by_name, reachable)

    # --- edges -------------------------------------------------------------
    # An edge exists where a reachable host declares that it shares a folder with a device.
    # Two unmonitored devices never get an edge: no host can tell whether they share anything.
    pairs: dict[tuple[str, str], list[str]] = {}
    for h in reachable:
        for folder_id, f in h.folders.items():
            for dev_id in f["devices"]:
                if dev_id == h.my_id:
                    continue
                key = tuple(sorted((h.my_id, dev_id), key=order_index.__getitem__))
                folder_ids = pairs.setdefault(key, [])
                if folder_id not in folder_ids:
                    folder_ids.append(folder_id)
    edges = [
        Edge(a, b, sorted(fids, key=lambda i: folders[i].label.casefold()), _edge_state(a, b, devices, id_to_host, host_by_name))
        for (a, b), fids in pairs.items()
    ]

    unplaced = [h.name for h in hosts if h.name not in host_ids]
    return Overview(
        generated_at=now,
        hosts=hosts,
        devices=ordered,
        edges=edges,
        folders=sorted(folders.values(), key=lambda f: f.label.casefold()),
        cells=cells,
        unplaced_hosts=unplaced,
    )


def _edge_state(
    a: str,
    b: str,
    devices: dict[str, Device],
    id_to_host: dict[str, str],
    host_by_name: dict[str, HostSnapshot],
) -> str:
    verdicts: list[str] = []
    for me, other in ((a, b), (b, a)):
        host = host_by_name.get(id_to_host.get(me, ""))
        if host is None or not host.reachable:
            continue
        conn = host.connections.get(other, {})
        if conn.get("connected"):
            verdicts.append("connected")
        elif conn.get("paused") or host.devices.get(other, {}).get("paused"):
            verdicts.append("paused")
        else:
            verdicts.append("disconnected")
    if not verdicts:
        return "unknown"
    if "connected" in verdicts:
        return "connected"
    if "paused" in verdicts:
        return "paused"
    return "disconnected"


def _cell(
    folder_id: str,
    dev: Device,
    id_to_host: dict[str, str],
    host_by_name: dict[str, HostSnapshot],
    reachable: list[HostSnapshot],
) -> Cell:
    host = host_by_name.get(dev.host_name or "") if dev.monitored else None

    if host is not None and host.reachable:
        if folder_id in host.folders:
            st = host.folder_status.get(folder_id)
            if st is None:
                return Cell("unknown", "unknown")
            if st.error or st.errors:
                detail = st.error or f"{st.errors} failed items"
                return Cell("error", "error", _percent(st.global_bytes, st.need_bytes), st.need_items, detail)
            category = _STATE_CATEGORY.get(st.state, "unknown")
            state = st.state
            if st.state == "idle" and st.need_items > 0:
                state, category = "out of sync", "syncing"
            return Cell(state, category, _percent(st.global_bytes, st.need_bytes), st.need_items)
        # offered by another host, not accepted here
        pending = host.pending_folders.get(folder_id)
        offered_by = sorted(
            {id_to_host.get(o, "") or o[:7] for o in (pending or {}).get("offered_by", [])}
            or {h.name for h in reachable if folder_id in h.folders and dev.id in h.folders[folder_id]["devices"]}
        )
        return Cell("not accepted", "flag", detail="offered by " + ", ".join(offered_by), flagged=True)

    # Remote view: what the reachable hosts report about this device's copy.
    reports = []
    for h in reachable:
        c = h.completion.get((folder_id, dev.id))
        if c is None:
            continue
        connected = bool(h.connections.get(dev.id, {}).get("connected"))
        reports.append((connected, c, h.name))
    if dev.monitored and not reports:
        return Cell("unreachable", "offline", detail=dev.error)
    if not reports:
        return Cell("unknown", "unknown", detail="no host reports about this device")
    reports.sort(key=lambda r: (r[0], r[1].remote_state == "valid"), reverse=True)
    connected, c, via = reports[0]
    detail = f"as seen by {via}"
    if dev.monitored:
        detail = f"host unreachable; {detail}"
    if c.remote_state == "notSharing":
        return Cell("not sharing", "flag", detail=f"device does not share this folder back ({detail})", flagged=False)
    if c.remote_state == "paused":
        return Cell("paused", "paused", c.completion, c.need_items, detail)
    if not connected:
        state = "unreachable" if dev.monitored else "offline"
        return Cell(state, "offline", c.completion, c.need_items, f"last known, {detail}")
    if c.completion >= 100.0 and c.need_items == 0:
        return Cell("in sync", "ok", 100.0, 0, detail)
    return Cell("syncing", "syncing", c.completion, c.need_items, detail)
