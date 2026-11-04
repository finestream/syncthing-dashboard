"""Command line: write the page once or serve it."""

from __future__ import annotations

import argparse
import logging
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .collector import collect_all
from .config import ConfigError, HostConfig, load_hosts
from .model import build_overview
from .render import render

log = logging.getLogger("syncthing_dashboard")


def build_page(hosts: list[HostConfig], timeout: float, refresh: int | None, title: str) -> str:
    snapshots = collect_all(hosts, timeout=timeout)
    return render(build_overview(snapshots), refresh=refresh, title=title)


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer without the reverse DNS lookup of the bind address at start.

    ``HTTPServer.server_bind`` calls ``socket.getfqdn``, which can block for a long
    time in a container or sandbox without reverse DNS. The name is only used for
    the ``Server`` header, so the plain address will do.
    """

    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def make_handler(hosts: list[HostConfig], timeout: float, refresh: int | None, title: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"syncthing-dashboard/{__version__}"

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            if path in ("/healthz", "/health"):
                self._send(200, b"ok\n", "text/plain; charset=utf-8")
                return
            if path not in ("/", "/index.html", "/overview.html"):
                self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            try:
                body = build_page(hosts, timeout, refresh, title).encode("utf-8")
            except Exception:  # the page must never die with a traceback on screen
                log.exception("rendering failed")
                self._send(500, b"rendering failed, see server log\n", "text/plain; charset=utf-8")
                return
            self._send(200, body, "text/html; charset=utf-8")

        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            log.info("%s %s", self.address_string(), format % args)

    return Handler


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="syncthing-dashboard",
        description="Render one page with topology and sync status of all Syncthing hosts.",
    )
    parser.add_argument("-c", "--config", default="hosts.toml", help="hosts file (default: hosts.toml)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--out", metavar="FILE", help="write the page once to FILE ('-' for stdout)")
    mode.add_argument("--serve", metavar="PORT", type=int, help="serve the page on PORT, regenerated per request")
    parser.add_argument("--bind", default="0.0.0.0", help="address to bind with --serve (default: 0.0.0.0)")
    parser.add_argument("--refresh", type=int, default=30, help="meta refresh in seconds with --serve (0 = none, default: 30)")
    parser.add_argument("--timeout", type=float, default=5.0, help="seconds per REST call (default: 5)")
    parser.add_argument("--title", default="Syncthing overview", help="page title")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every request and REST problem")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        hosts = load_hosts(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.out is not None:
        page = build_page(hosts, args.timeout, None, args.title)
        if args.out == "-":
            sys.stdout.write(page)
        else:
            Path(args.out).write_text(page, encoding="utf-8")
        return 0

    refresh = args.refresh if args.refresh > 0 else None
    server = Server((args.bind, args.serve), make_handler(hosts, args.timeout, refresh, args.title))
    log.warning("serving on http://%s:%d/ for %d host(s)", args.bind, args.serve, len(hosts))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
