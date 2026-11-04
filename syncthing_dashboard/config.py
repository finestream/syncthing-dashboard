"""Load ``hosts.toml``.

Example::

    [[hosts]]
    name = "nas"
    url = "https://nas.example.internal:8384"
    api_key_file = "/run/secrets/syncthing_nas"
    ca_file = "/etc/ssl/private-ca.pem"   # optional

The API key is never written in the configuration file; it is read from
``api_key_file`` at start, with surrounding whitespace stripped. This matches
compose secrets (``/run/secrets/<name>``) and systemd credentials
(``/run/credentials/<unit>/<name>``).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """The configuration file is missing or invalid."""


@dataclass(frozen=True)
class HostConfig:
    name: str
    url: str
    api_key: str
    ca_file: str | None = None

    def __repr__(self) -> str:  # never leak the key in logs or tracebacks
        return f"HostConfig(name={self.name!r}, url={self.url!r})"


def _read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError(f"cannot read api_key_file {path}: {exc.strerror}") from exc
    if not value:
        raise ConfigError(f"api_key_file {path} is empty")
    return value


def load_hosts(path: str | Path) -> list[HostConfig]:
    """Parse ``hosts.toml`` and read each host's API key file."""
    path = Path(path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    entries = data.get("hosts")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path}: expected at least one [[hosts]] entry")

    hosts: list[HostConfig] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: [[hosts]] entry {index} is not a table")
        for key in ("name", "url", "api_key_file"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ConfigError(f"{path}: [[hosts]] entry {index} needs a string {key!r}")
        if "api_key" in entry:
            raise ConfigError(
                f"{path}: host {entry['name']!r} has an inline api_key; use api_key_file"
            )
        name = entry["name"]
        if name in seen:
            raise ConfigError(f"{path}: duplicate host name {name!r}")
        seen.add(name)
        ca_file = entry.get("ca_file")
        if ca_file is not None and not isinstance(ca_file, str):
            raise ConfigError(f"{path}: host {name!r}: ca_file must be a string")
        key_path = Path(entry["api_key_file"])
        if not key_path.is_absolute():
            key_path = path.parent / key_path
        if ca_file is not None and not Path(ca_file).is_absolute():
            ca_file = str(path.parent / ca_file)
        hosts.append(
            HostConfig(
                name=name,
                url=entry["url"].rstrip("/"),
                api_key=_read_secret(key_path),
                ca_file=ca_file,
            )
        )
    return hosts
