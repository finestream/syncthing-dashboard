"""Poll the hosts in the background and keep each host's latest snapshot.

Serving a page never waits for a host. A page request asks for the polls that
are due and renders what has arrived so far. Polling only follows page requests
because ``/rest/db/status`` is expensive on the host: nobody looking, no load.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .collector import HostSnapshot, collect_host
from .config import HostConfig

log = logging.getLogger(__name__)


@dataclass
class _HostState:
    host: HostConfig
    snapshot: HostSnapshot | None = None
    running: bool = False
    started: float = float("-inf")
    finished: float = float("-inf")


class Poller:
    def __init__(self, hosts: list[HostConfig], timeout: float = 5.0, max_age: float = 30.0,
                 collect=collect_host, clock=time.monotonic):
        self._states = [_HostState(h) for h in hosts]
        self._timeout = timeout
        self._max_age = max_age
        self._collect = collect
        self._clock = clock
        self._lock = threading.Lock()

    def poll_due(self) -> None:
        """Start a poll for every host whose last one started ``max_age`` ago or more."""
        now = self._clock()
        with self._lock:
            due = [s for s in self._states if not s.running and now - s.started >= self._max_age]
            for state in due:
                state.running = True
                state.started = now
        for state in due:
            threading.Thread(target=self._poll, args=(state,), daemon=True, name=f"poll-{state.host.name}").start()

    def snapshots(self) -> list[HostSnapshot]:
        """The latest snapshot per host, in the order of the configuration.

        A routine poll keeps ``contacting`` off, or every page would look busy.
        It is on for a host with no answer yet and for data that outlived two
        intervals, which means nobody looked for a while or the host is slow.
        """
        now = self._clock()
        with self._lock:
            return [self._snapshot(state, now) for state in self._states]

    def _snapshot(self, state: _HostState, now: float) -> HostSnapshot:
        if state.snapshot is None:
            return HostSnapshot(name=state.host.name, url=state.host.url, contacting=True)
        out_of_date = now - state.finished > 2 * self._max_age
        return replace(state.snapshot, contacting=state.running and out_of_date)

    def _poll(self, state: _HostState) -> None:
        host = state.host
        try:
            snapshot = self._collect(host, self._timeout)
        except Exception:  # e.g. an unreadable ca_file or an answer of an unexpected shape
            log.exception("polling host %s failed", host.name)
            snapshot = HostSnapshot(name=host.name, url=host.url, error="polling failed, see server log")
        snapshot.polled_at = datetime.now(timezone.utc)
        with self._lock:
            state.snapshot = snapshot
            state.running = False
            state.finished = self._clock()
