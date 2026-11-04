"""Start and stop a small local Syncthing network for the live tests.

    python -m tests.live.harness up      # start, configure, write tests/live/run/hosts.toml
    python -m tests.live.harness down    # stop everything, keep the run directory
    python -m tests.live.harness clean   # stop and delete the run directory

The network (names are placeholders, every instance runs on 127.0.0.1):

    alpha   monitored, running            folders: shared-all, pair-ab, offered
    beta    monitored, running            folders: shared-all, pair-ab, beta-gamma
                                          ``offered`` is shared *to* beta by alpha and not accepted
    gamma   monitored, STOPPED after set-up  folders: shared-all, beta-gamma
    phone   not monitored, never started  appears in alpha's and beta's configuration for shared-all

Ports: GUI ``BASE_GUI + n``, sync ``BASE_SYNC + n`` (n = 0..2), overridable with
``SYNCTHING_TEST_GUI_PORT`` and ``SYNCTHING_TEST_SYNC_PORT``. Requires the
``syncthing`` binary (``SYNCTHING_BIN`` to override). Standard library only.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent / "run"
BIN = os.environ.get("SYNCTHING_BIN", "syncthing")
BASE_GUI = int(os.environ.get("SYNCTHING_TEST_GUI_PORT", "28384"))
BASE_SYNC = int(os.environ.get("SYNCTHING_TEST_SYNC_PORT", "32200"))

HOSTS = ["alpha", "beta", "gamma"]
EXTRA = ["phone"]
# folder id -> {instance: [peer names]}  (peers may include "phone")
FOLDERS = {
    "shared-all": {"alpha": ["beta", "gamma", "phone"], "beta": ["alpha", "gamma", "phone"], "gamma": ["alpha", "beta"]},
    "pair-ab": {"alpha": ["beta"], "beta": ["alpha"]},
    "offered": {"alpha": ["beta"]},
    "beta-gamma": {"beta": ["gamma"], "gamma": ["beta"]},
}
STOPPED = "gamma"


def gui_port(name: str) -> int:
    return BASE_GUI + HOSTS.index(name)


def sync_port(name: str) -> int:
    return BASE_SYNC + HOSTS.index(name)


def home(name: str) -> Path:
    return RUN_DIR / name


def key_file(name: str) -> Path:
    return RUN_DIR / "keys" / name


def env() -> dict[str, str]:
    e = dict(os.environ)
    e.update({"STNOUPGRADE": "1", "STNODEFAULTFOLDER": "1", "STNOPORTPROBING": "1"})
    return e


def rest(name: str, method: str, path: str, body=None):
    url = f"http://127.0.0.1:{gui_port(name)}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", key_file(name).read_text().strip())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw) if raw.strip() else None


def wait_for(name: str, what: str, pred, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            if pred():
                return
        except (urllib.error.URLError, ConnectionError, OSError, json.JSONDecodeError) as exc:
            last = exc
        time.sleep(0.5)
    raise TimeoutError(f"{name}: timed out waiting for {what} (last error: {last})")


def generate(name: str) -> str:
    subprocess.run([BIN, "generate", "--home", str(home(name)), "--no-port-probing"], check=True, env=env(),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # The GUI listens on loopback and would reject other Host headers (e.g. host.docker.internal
    # from a container). Set in the file before the first start: over REST it restarts the GUI.
    config = home(name) / "config.xml"
    config.write_text(config.read_text().replace(
        "</gui>", "    <insecureSkipHostcheck>true</insecureSkipHostcheck>\n    </gui>", 1))
    out = subprocess.run([BIN, "device-id", "--home", str(home(name))], check=True, env=env(),
                         capture_output=True, text=True).stdout
    return out.strip().split()[-1]


def start(name: str) -> subprocess.Popen:
    log = (home(name) / "syncthing.log").open("ab")
    proc = subprocess.Popen(
        [
            BIN, "serve", "--home", str(home(name)),
            "--gui-address", f"127.0.0.1:{gui_port(name)}",
            "--gui-apikey", key_file(name).read_text().strip(),
            "--no-browser", "--no-restart", "--no-upgrade", "--no-port-probing",
        ],
        env=env(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    wait_for(name, "REST API", lambda: rest(name, "GET", "/rest/system/status").get("myID"))
    return proc


def configure(ids: dict[str, str]) -> None:
    for name in HOSTS:
        options = rest(name, "GET", "/rest/config/options")
        options.update({
            "listenAddresses": [f"tcp://127.0.0.1:{sync_port(name)}"],
            "globalAnnounceEnabled": False, "localAnnounceEnabled": False,
            "relaysEnabled": False, "natEnabled": False, "urAccepted": -1,
            "crashReportingEnabled": False, "startBrowser": False,
            "reconnectionIntervalS": 2,
        })
        rest(name, "PUT", "/rest/config/options", options)
        # drop any default folder
        for folder in rest(name, "GET", "/rest/config/folders"):
            rest(name, "DELETE", f"/rest/config/folders/{folder['id']}")
        devices = rest(name, "GET", "/rest/config/devices")
        known = {d["deviceID"] for d in devices}
        for peer, dev_id in ids.items():
            if peer == name or dev_id in known:
                continue
            addresses = [f"tcp://127.0.0.1:{sync_port(peer)}"] if peer in HOSTS else ["dynamic"]
            devices.append({"deviceID": dev_id, "name": peer, "addresses": addresses, "autoAcceptFolders": False})
        rest(name, "PUT", "/rest/config/devices", devices)
        folders = []
        for folder_id, members in FOLDERS.items():
            if name not in members:
                continue
            path = home(name) / "data" / folder_id
            path.mkdir(parents=True, exist_ok=True)
            folders.append({
                "id": folder_id, "label": folder_id.replace("-", " ").title(), "path": str(path),
                "type": "sendreceive", "rescanIntervalS": 3600, "fsWatcherEnabled": False,
                "devices": [{"deviceID": ids[p]} for p in members[name]],
            })
        rest(name, "PUT", "/rest/config/folders", folders)
    # some content to sync
    for i in range(3):
        (home("alpha") / "data" / "shared-all" / f"file-{i}.txt").write_text("hello from alpha\n" * (i + 1))
    (home("alpha") / "data" / "pair-ab" / "note.txt").write_text("pair\n")
    (home("beta") / "data" / "beta-gamma" / "bg.txt").write_text("beta gamma\n")
    for name in HOSTS:
        rest(name, "POST", "/rest/db/scan")


def connected(name: str, peer_id: str) -> bool:
    conns = rest(name, "GET", "/rest/system/connections")["connections"]
    return bool(conns.get(peer_id, {}).get("connected"))


def in_sync(name: str, folder_id: str) -> bool:
    st = rest(name, "GET", f"/rest/db/status?folder={folder_id}")
    return st.get("state") == "idle" and st.get("needTotalItems", st.get("needFiles", 0)) == 0 and st.get("globalFiles", 0) > 0


def peer_complete(name: str, folder_id: str, peer_id: str) -> bool:
    c = rest(name, "GET", f"/rest/db/completion?folder={folder_id}&device={peer_id}")
    return c.get("completion") == 100 and c.get("needItems", 0) == 0


def up() -> None:
    if (RUN_DIR / "pids.json").exists():
        down()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "keys").mkdir(exist_ok=True)
    ids: dict[str, str] = {}
    for name in HOSTS + EXTRA:
        if not (home(name) / "config.xml").exists():
            ids[name] = generate(name)
        else:
            ids[name] = subprocess.run([BIN, "device-id", "--home", str(home(name))], check=True, env=env(),
                                       capture_output=True, text=True).stdout.strip().split()[-1]
    (RUN_DIR / "ids.json").write_text(json.dumps(ids, indent=2))
    for name in HOSTS:
        if not key_file(name).exists():
            key_file(name).write_text(secrets.token_hex(16) + "\n")
            key_file(name).chmod(0o600)
    procs = {name: start(name) for name in HOSTS}
    (RUN_DIR / "pids.json").write_text(json.dumps({n: p.pid for n, p in procs.items()}))
    configure(ids)
    for a in HOSTS:
        for b in HOSTS:
            if a != b:
                wait_for(a, f"connection to {b}", lambda a=a, b=b: connected(a, ids[b]), timeout=90)
    for name, members in (("alpha", "shared-all"), ("beta", "shared-all"), ("gamma", "shared-all"), ("beta", "pair-ab"), ("gamma", "beta-gamma")):
        wait_for(name, f"{members} in sync", lambda name=name, members=members: in_sync(name, members), timeout=120)
    # The peers must have received the stopped host's final index before it goes away,
    # otherwise they report its copy as incomplete ("last known" on the page).
    for name, folder_id in (("alpha", "shared-all"), ("beta", "shared-all"), ("beta", "beta-gamma")):
        wait_for(name, f"{STOPPED} complete for {folder_id}",
                 lambda name=name, folder_id=folder_id: peer_complete(name, folder_id, ids[STOPPED]), timeout=120)
    # stop one instance so the page shows an unreachable host
    os.killpg(procs[STOPPED].pid, signal.SIGTERM)
    procs[STOPPED].wait(timeout=30)
    pids = {n: p.pid for n, p in procs.items() if n != STOPPED}
    (RUN_DIR / "pids.json").write_text(json.dumps(pids))
    hosts_toml = "\n".join(
        f'[[hosts]]\nname = "{name}"\nurl = "http://127.0.0.1:{gui_port(name)}"\napi_key_file = "keys/{name}"\n'
        for name in HOSTS
    )
    (RUN_DIR / "hosts.toml").write_text(hosts_toml)
    print(f"up: alpha and beta running, {STOPPED} stopped; config at {RUN_DIR / 'hosts.toml'}")


def down() -> None:
    pid_file = RUN_DIR / "pids.json"
    if not pid_file.exists():
        print("nothing running")
        return
    for name, pid in json.loads(pid_file.read_text()).items():
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        for _ in range(60):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.5)
        else:
            os.killpg(pid, signal.SIGKILL)
        print(f"stopped {name}")
    pid_file.unlink()


def clean() -> None:
    down()
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
    print("removed", RUN_DIR)


def main(argv: list[str]) -> int:
    if shutil.which(BIN) is None:
        print(f"error: {BIN!r} not found; set SYNCTHING_BIN", file=sys.stderr)
        return 2
    cmd = argv[0] if argv else "up"
    {"up": up, "down": down, "clean": clean}[cmd]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
