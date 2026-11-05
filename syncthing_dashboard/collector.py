"""Poll one Syncthing instance over its REST API.

Every call carries the ``X-API-Key`` header and a timeout. A host that cannot
be reached yields a :class:`HostSnapshot` with ``reachable=False`` and an
error message; it never raises into the page.
"""

from __future__ import annotations

import json
import logging
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .config import HostConfig

log = logging.getLogger(__name__)


@dataclass
class FolderStatus:
    """Local state of a folder on the host that has it (``/rest/db/status``)."""

    state: str
    global_bytes: int
    need_bytes: int
    need_items: int
    errors: int
    error: str = ""


@dataclass
class Completion:
    """What a host knows about a remote device's copy of a folder."""

    completion: float
    need_items: int
    need_bytes: int
    remote_state: str  # valid, notSharing, paused, unknown (or "" on old versions)


@dataclass
class HostSnapshot:
    name: str
    url: str
    reachable: bool = False
    error: str = ""
    my_id: str = ""
    version: str = ""
    # devices: device ID -> {"name", "paused", "addresses"}
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    # folders: folder ID -> {"label", "path", "type", "paused", "devices": [ids]}
    folders: dict[str, dict[str, Any]] = field(default_factory=dict)
    # connections: device ID -> {"connected", "paused", "address", "clientVersion"}
    connections: dict[str, dict[str, Any]] = field(default_factory=dict)
    folder_status: dict[str, FolderStatus] = field(default_factory=dict)
    # completion[(folder ID, device ID)]
    completion: dict[tuple[str, str], Completion] = field(default_factory=dict)
    # folders offered by other devices and not accepted here: folder ID -> {"label", "offered_by": [ids]}
    pending_folders: dict[str, dict[str, Any]] = field(default_factory=dict)
    system_errors: int = 0
    polled_at: datetime | None = None  # set by the background poller
    contacting: bool = False  # a poll is running and this data, if any, is out of date

    @property
    def awaiting_answer(self) -> bool:
        """Being contacted, with nothing usable to show until it answers."""
        return self.contacting and not self.reachable

    @property
    def connected_peers(self) -> int:
        return sum(1 for c in self.connections.values() if c.get("connected"))


class RestError(Exception):
    pass


class SyncthingClient:
    def __init__(self, host: HostConfig, timeout: float = 5.0):
        self.host = host
        self.timeout = timeout
        self._context: ssl.SSLContext | None = None
        if host.url.lower().startswith("https://"):
            self._context = ssl.create_default_context(cafile=host.ca_file)

    def get(self, path: str, **params: str) -> Any:
        url = self.host.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"X-API-Key": self.host.api_key})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            raise RestError(f"{path}: HTTP {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise RestError(f"{path}: TLS verification failed ({reason.verify_message})") from exc
            raise RestError(f"{path}: {reason}") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise RestError(f"{path}: timed out after {self.timeout:g}s") from exc
        except (OSError, ValueError) as exc:
            raise RestError(f"{path}: {exc}") from exc


def _int(value: Any) -> int:
    """Syncthing reports counters as numbers, but be lenient with missing or odd values."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _folder_status(st: dict[str, Any], paused: bool) -> FolderStatus:
    """Reduce ``/rest/db/status`` to what the page shows."""
    need_items = sum(_int(st.get(k)) for k in ("needFiles", "needDirectories", "needSymlinks", "needDeletes"))
    return FolderStatus(
        state="paused" if paused else (st.get("state") or "unknown"),
        global_bytes=_int(st.get("globalBytes")),
        need_bytes=_int(st.get("needBytes")),
        need_items=need_items,
        errors=_int(st.get("errors")) + _int(st.get("pullErrors")),
        error=st.get("error") or "",
    )


def _completion(c: dict[str, Any]) -> Completion:
    """Reduce ``/rest/db/completion`` to what the page shows."""
    return Completion(
        completion=float(c.get("completion") or 0.0),
        need_items=_int(c.get("needItems")) + _int(c.get("needDeletes")),
        need_bytes=_int(c.get("needBytes")),
        remote_state=c.get("remoteState") or "",
    )


def collect_host(host: HostConfig, timeout: float = 5.0) -> HostSnapshot:
    """Collect everything the page needs from one host.

    The first four calls decide whether the host counts as reachable. Everything
    after that is best effort: a failure is logged and leaves a gap in the page.
    """
    snap = HostSnapshot(name=host.name, url=host.url)
    client = SyncthingClient(host, timeout=timeout)
    try:
        status = client.get("/rest/system/status")
        snap.my_id = status.get("myID", "")
        version = client.get("/rest/system/version")
        snap.version = version.get("version", "")
        config = client.get("/rest/config")
        connections = client.get("/rest/system/connections")
    except RestError as exc:
        snap.error = str(exc)
        log.warning("host %s unreachable: %s", host.name, exc)
        return snap
    snap.reachable = True

    for dev in config.get("devices", []):
        dev_id = dev.get("deviceID", "")
        if not dev_id:
            continue
        snap.devices[dev_id] = {
            "name": dev.get("name") or dev_id[:7],
            "paused": bool(dev.get("paused")),
            "addresses": list(dev.get("addresses") or []),
        }
    for folder in config.get("folders", []):
        folder_id = folder.get("id", "")
        if not folder_id:
            continue
        snap.folders[folder_id] = {
            "label": folder.get("label") or folder_id,
            "path": folder.get("path", ""),
            "type": folder.get("type", ""),
            "paused": bool(folder.get("paused")),
            "devices": [d.get("deviceID") for d in folder.get("devices", []) if d.get("deviceID")],
        }
    for dev_id, conn in (connections.get("connections") or {}).items():
        snap.connections[dev_id] = {
            "connected": bool(conn.get("connected")),
            "paused": bool(conn.get("paused")),
            "address": conn.get("address", ""),
            "clientVersion": conn.get("clientVersion", ""),
        }

    # Best effort from here on.
    try:
        errors = client.get("/rest/system/error")
        snap.system_errors = len(errors.get("errors") or [])
    except RestError as exc:
        log.info("host %s: %s", host.name, exc)
    try:
        pending = client.get("/rest/cluster/pending/folders")
        for folder_id, info in (pending or {}).items():
            offered = info.get("offeredBy") or {}
            label = next((o.get("label") for o in offered.values() if o.get("label")), folder_id)
            snap.pending_folders[folder_id] = {"label": label, "offered_by": list(offered)}
    except RestError as exc:
        log.info("host %s: %s", host.name, exc)

    for folder_id, folder in snap.folders.items():
        try:
            st = client.get("/rest/db/status", folder=folder_id)
            snap.folder_status[folder_id] = _folder_status(st, folder["paused"])
        except RestError as exc:
            log.info("host %s folder %s: %s", host.name, folder_id, exc)
            snap.folder_status[folder_id] = FolderStatus("unknown", 0, 0, 0, 0, str(exc))
        for dev_id in folder["devices"]:
            if dev_id == snap.my_id:
                continue
            try:
                c = client.get("/rest/db/completion", folder=folder_id, device=dev_id)
                snap.completion[(folder_id, dev_id)] = _completion(c)
            except RestError as exc:
                log.info("host %s folder %s device %s: %s", host.name, folder_id, dev_id[:7], exc)
    return snap


def collect_all(hosts: list[HostConfig], timeout: float = 5.0) -> list[HostSnapshot]:
    """Collect all hosts in parallel, in the order of the configuration."""
    with ThreadPoolExecutor(max_workers=max(1, min(len(hosts), 16))) as pool:
        return list(pool.map(lambda h: collect_host(h, timeout), hosts))
