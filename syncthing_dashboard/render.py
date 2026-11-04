"""Render the :class:`Overview` as one self-contained HTML page.

Inline CSS, inline SVG, no scripts, no external resources. Hover texts use
``<title>`` elements, which every browser shows as a tooltip.
"""

from __future__ import annotations

import math
from html import escape

from . import __version__
from .model import Device, Edge, Overview

_CSS = """
:root { color-scheme: light dark;
  --bg: #fff; --fg: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7; --card: #f5f5f7;
  --ok: #2e9e4f; --syncing: #2f6fd6; --scanning: #7a5cd6; --error: #d6362f;
  --paused: #d49a16; --unknown: #8e8e93; --offline: #b0b0b5; --flag: #e3741c; }
@media (prefers-color-scheme: dark) { :root {
  --bg: #1c1c1e; --fg: #f2f2f7; --muted: #a1a1a6; --line: #3a3a3c; --card: #2c2c2e;
  --ok: #30c758; --syncing: #4d8df0; --scanning: #9b7ff2; --error: #ff5b52;
  --paused: #f2b53a; --unknown: #8e8e93; --offline: #636366; --flag: #ff9640; } }
* { box-sizing: border-box; }
body { margin: 0; padding: 1.5rem; font: 15px/1.45 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--fg); }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .75rem; }
.meta { color: var(--muted); font-size: .85rem; }
.hosts { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem; }
.host { background: var(--card); border-radius: 10px; padding: .75rem 1rem; min-width: 14rem; border-left: 6px solid var(--unknown); }
.host.ok { border-left-color: var(--ok); } .host.error { border-left-color: var(--error); }
.host .name { font-weight: 600; font-size: 1.05rem; }
.host .name a { color: inherit; text-decoration: none; }
.host dl { display: grid; grid-template-columns: auto 1fr; gap: .1rem .75rem; margin: .5rem 0 0; font-size: .9rem; }
.host dt { color: var(--muted); } .host dd { margin: 0; }
.host .err { color: var(--error); font-size: .85rem; margin-top: .4rem; word-break: break-word; }
.badge { display: inline-block; font-size: .75rem; padding: .05rem .5rem; border-radius: 999px; color: #fff; vertical-align: middle; background: var(--unknown); }
.badge.ok { background: var(--ok); } .badge.error { background: var(--error); } .badge.offline { background: var(--offline); }
.badge.paused { background: var(--paused); } .badge.flag { background: var(--flag); }
.topology { max-width: 100%; overflow: auto; background: var(--card); border-radius: 10px; }
svg text { font-family: inherit; fill: var(--fg); }
svg .edge { stroke-width: 2.5; fill: none; }
svg .edge.connected { stroke: var(--ok); } svg .edge.disconnected { stroke: var(--error); stroke-dasharray: 6 4; }
svg .edge.paused { stroke: var(--paused); stroke-dasharray: 2 4; } svg .edge.unknown { stroke: var(--unknown); stroke-dasharray: 1 5; }
svg .edge-label { font-size: 11px; fill: var(--muted); text-anchor: middle; }
svg .node circle { stroke-width: 3; fill: var(--card); }
svg .node.ok circle { stroke: var(--ok); } svg .node.error circle { stroke: var(--error); }
svg .node.offline circle { stroke: var(--offline); } svg .node.paused circle { stroke: var(--paused); }
svg .node.monitored circle { fill: var(--bg); }
svg .node text { text-anchor: middle; font-size: 12px; }
svg .node .sub { font-size: 10px; fill: var(--muted); }
table.matrix { border-collapse: collapse; width: 100%; font-size: .85rem; }
table.matrix th, table.matrix td { border: 1px solid var(--line); padding: .35rem .5rem; text-align: left; vertical-align: top; }
table.matrix th { background: var(--card); font-weight: 600; }
table.matrix th .sub { display: block; font-weight: 400; color: var(--muted); font-size: .75rem; }
table.matrix td.empty { background: transparent; color: var(--line); text-align: center; }
table.matrix td.cell { border-left: 5px solid var(--unknown); }
td.cell.ok { border-left-color: var(--ok); } td.cell.syncing { border-left-color: var(--syncing); }
td.cell.scanning { border-left-color: var(--scanning); } td.cell.error { border-left-color: var(--error); }
td.cell.paused { border-left-color: var(--paused); } td.cell.offline { border-left-color: var(--offline); }
td.cell.flag { border-left-color: var(--flag); background: color-mix(in srgb, var(--flag) 12%, transparent); }
td.cell .state { font-weight: 600; }
td.cell .num { color: var(--muted); display: block; }
.legend { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; margin-top: .75rem; font-size: .8rem; color: var(--muted); }
.legend span::before { content: ""; display: inline-block; width: .7rem; height: .7rem; border-radius: 2px; margin-right: .35rem; vertical-align: -1px; background: var(--c); }
.warn { background: color-mix(in srgb, var(--paused) 15%, transparent); border-radius: 8px; padding: .5rem .75rem; margin-top: 1rem; }
footer { margin-top: 2.5rem; color: var(--muted); font-size: .8rem; }
"""


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.0f}%" if abs(value - round(value)) < 0.05 else f"{value:.1f}%"


def _host_strip(ov: Overview) -> str:
    parts = ['<div class="hosts">']
    for h in ov.hosts:
        cls = "ok" if h.reachable else "error"
        badge = "reachable" if h.reachable else "unreachable"
        peers_total = sum(1 for d in h.devices if d != h.my_id)
        folder_errors = sum(1 for s in h.folder_status.values() if s.error or s.errors)
        errors = h.system_errors + folder_errors
        parts.append(f'<div class="host {cls}">')
        parts.append(
            f'<div class="name"><a href="{escape(h.url, quote=True)}">{escape(h.name)}</a> '
            f'<span class="badge {cls}">{badge}</span></div>'
        )
        if h.reachable:
            parts.append("<dl>")
            parts.append(f"<dt>Version</dt><dd>{escape(h.version or '?')}</dd>")
            parts.append(f"<dt>Peers</dt><dd>{h.connected_peers} / {peers_total} connected</dd>")
            parts.append(f"<dt>Folders</dt><dd>{len(h.folders)}</dd>")
            err_badge = ' <span class="badge error">!</span>' if errors else ""
            parts.append(f"<dt>Errors</dt><dd>{errors}{err_badge}</dd>")
            if h.pending_folders:
                labels = ", ".join(escape(p["label"]) for p in h.pending_folders.values())
                parts.append(f'<dt>Offered</dt><dd><span class="badge flag">{len(h.pending_folders)}</span> {labels}</dd>')
            parts.append("</dl>")
        else:
            parts.append(f'<div class="err">{escape(h.error or "no answer")}</div>')
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def _topology(ov: Overview) -> str:
    devices = ov.devices
    n = len(devices)
    if n == 0:
        return '<p class="meta">No devices known.</p>'
    radius = max(120, 34 * n)
    cx, cy = radius + 190, radius + 80  # room for the labels outside the circle
    width, height = 2 * cx, 2 * cy
    positions: dict[str, tuple[float, float]] = {}
    angles: dict[str, float] = {}
    for i, d in enumerate(devices):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        angles[d.id] = angle
        positions[d.id] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
    if n == 1:
        positions[devices[0].id] = (cx, cy)

    labels = {f.id: f.label for f in ov.folders}
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        'role="img" aria-label="Topology of Syncthing devices">'
    ]
    for e in ov.edges:
        (x1, y1), (x2, y2) = positions[e.a], positions[e.b]
        names = f"{ov.device(e.a).name} – {ov.device(e.b).name}"
        folder_list = "\n".join(labels.get(f, f) for f in e.folders)
        title = escape(f"{names}: {e.state}\n{folder_list}")
        out.append(f'<g><title>{title}</title><line class="edge {e.state}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
        # label at 38 % of the way, so that crossing diagonals do not share one spot
        mx, my = x1 + 0.38 * (x2 - x1), y1 + 0.38 * (y2 - y1)
        out.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="9" fill="var(--card)"/>')
        out.append(f'<text class="edge-label" x="{mx:.1f}" y="{my + 4:.1f}">{len(e.folders)}</text></g>')
    for d in devices:
        x, y = positions[d.id]
        cls = f"node {d.category}" + (" monitored" if d.monitored else "")
        tip_lines = [d.name, d.id, d.status_text]
        if d.version:
            tip_lines.append(d.version)
        tip_lines.append(f"{d.folder_count} folder(s)")
        if d.error:
            tip_lines.append(d.error)
        out.append(f'<g class="{cls}"><title>{escape(chr(10).join(tip_lines))}</title>')
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="22"/>')
        # labels sit outside the circle, away from the edges
        angle = angles[d.id]
        lx, ly = x + 32 * math.cos(angle), y + 32 * math.sin(angle)
        anchor = "start" if math.cos(angle) > 0.3 else "end" if math.cos(angle) < -0.3 else "middle"
        if anchor == "middle":
            ly += 14 if math.sin(angle) > 0 else -10
        sub = "monitored" if d.monitored else "unmonitored"
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" style="text-anchor:{anchor}">{escape(d.name)}</text>')
        out.append(f'<text class="sub" x="{lx:.1f}" y="{ly + 13:.1f}" style="text-anchor:{anchor}">{sub} · {escape(d.status_text)}</text></g>')
    out.append("</svg>")
    return f'<div class="topology">{"".join(out)}</div>'


def _matrix(ov: Overview) -> str:
    if not ov.folders:
        return '<p class="meta">No folders known.</p>'
    out = ['<table class="matrix"><thead><tr><th>Folder</th>']
    for d in ov.devices:
        sub = "monitored" if d.monitored else "unmonitored"
        out.append(f'<th>{escape(d.name)}<span class="sub">{sub} · {escape(d.status_text)}</span></th>')
    out.append("</tr></thead><tbody>")
    for f in ov.folders:
        type_sub = f'<span class="sub">{escape(f.type)}</span>' if f.type and f.type != "sendreceive" else ""
        out.append(f'<tr><th title="{escape(f.id, quote=True)}">{escape(f.label)}{type_sub}</th>')
        for d in ov.devices:
            cell = ov.cells.get((f.id, d.id))
            if cell is None:
                out.append('<td class="empty">·</td>')
                continue
            title = f' title="{escape(cell.detail, quote=True)}"' if cell.detail else ""
            nums = []
            if cell.completion is not None:
                nums.append(_fmt_pct(cell.completion))
            if cell.need_items:
                nums.append(f"{cell.need_items} item{'s' if cell.need_items != 1 else ''} needed")
            num_html = f'<span class="num">{escape(", ".join(nums))}</span>' if nums else ""
            flag = ' <span class="badge flag">!</span>' if cell.flagged else ""
            out.append(f'<td class="cell {cell.category}"{title}><span class="state">{escape(cell.state)}</span>{flag}{num_html}</td>')
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _legend() -> str:
    items = [
        ("ok", "idle / in sync"), ("syncing", "syncing / out of sync"), ("scanning", "scanning"),
        ("error", "error / unreachable"), ("paused", "paused"), ("offline", "offline"),
        ("flag", "offered, not accepted"), ("unknown", "unknown"),
    ]
    return '<div class="legend">' + "".join(f'<span style="--c: var(--{c})">{t}</span>' for c, t in items) + "</div>"


def render(ov: Overview, refresh: int | None = None, title: str = "Syncthing overview") -> str:
    """Return the complete HTML document."""
    refresh_tag = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    generated = ov.generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    reachable = sum(1 for h in ov.hosts if h.reachable)
    unplaced = ""
    if ov.unplaced_hosts:
        names = ", ".join(escape(n) for n in ov.unplaced_hosts)
        unplaced = (
            f'<div class="warn">Unreachable and not known by name to any other host, so not shown in the graph or matrix: {names}. '
            "Name the device the same way on a peer to place it.</div>"
        )
    monitored = sum(1 for d in ov.devices if d.monitored)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{refresh_tag}
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{escape(title)}</h1>
<div class="meta">Generated {escape(generated)} · {reachable} of {len(ov.hosts)} hosts reachable · {len(ov.devices)} devices ({monitored} monitored) · {len(ov.folders)} folders</div>
{_host_strip(ov)}
{unplaced}
<h2>Topology</h2>
{_topology(ov)}
<h2>Folders × devices</h2>
{_matrix(ov)}
{_legend()}
<footer>syncthing-dashboard {escape(__version__)} · standard library only · hover a node, edge or cell for details</footer>
</body>
</html>
"""
