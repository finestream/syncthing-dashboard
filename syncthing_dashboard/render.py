"""Render the :class:`Overview` as one self-contained HTML page.

Inline CSS, inline SVG, no scripts, no external resources. Hover texts use
``<title>`` elements, which every browser shows as a tooltip. Colours are CSS
variables named after the state categories of :mod:`.model` (``ok``,
``syncing``, ``scanning``, ``error``, ``paused``, ``offline``, ``flag``,
``unknown``), so a category maps to a class name everywhere.
"""

from __future__ import annotations

import math
from html import escape

from . import __version__
from .model import Cell, Device, Overview

# Specificity matters: ``.matrix td`` (one class, one element) sets the generic border, so
# the cell rules carry two classes (``.matrix .cell``) and the state rules three
# (``.matrix .cell.ok``). A flatter rule would lose the state colour, as happened once.
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
a { color: inherit; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .75rem; }
.meta { color: var(--muted); font-size: .85rem; }
.sub { display: block; font-weight: 400; color: var(--muted); font-size: .75rem; }

/* host strip */
.hosts { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem; }
.host { background: var(--card); border-radius: 10px; padding: .75rem 1rem; min-width: 14rem; border-left: 6px solid var(--unknown); }
.host.ok { border-left-color: var(--ok); }
.host.error { border-left-color: var(--error); }
.host-name { font-weight: 600; font-size: 1.05rem; }
.host-name a { text-decoration: none; }
.host-name a:hover { text-decoration: underline; }
.host dl { display: grid; grid-template-columns: auto 1fr; gap: .1rem .75rem; margin: .5rem 0 0; font-size: .9rem; }
.host dt { color: var(--muted); }
.host dd { margin: 0; }
.host-error { color: var(--error); font-size: .85rem; margin-top: .4rem; word-break: break-word; }
.badge { display: inline-block; font-size: .75rem; padding: .05rem .5rem; border-radius: 999px; color: #fff; vertical-align: middle; background: var(--unknown); }
.badge.ok { background: var(--ok); }
.badge.error { background: var(--error); }
.badge.flag { background: var(--flag); }

/* topology */
.topology { max-width: 100%; overflow: auto; background: var(--card); border-radius: 10px; }
.topology text { font-family: inherit; fill: var(--fg); font-size: 12px; }
.edge { stroke-width: 2.5; fill: none; }
.edge.connected { stroke: var(--ok); }
.edge.disconnected { stroke: var(--error); stroke-dasharray: 6 4; }
.edge.paused { stroke: var(--paused); stroke-dasharray: 2 4; }
.edge.unknown { stroke: var(--unknown); stroke-dasharray: 1 5; }
.edge-label { font-size: 11px; fill: var(--muted); text-anchor: middle; }
.node circle { fill: var(--unknown); stroke: var(--bg); stroke-width: 3; }
.node.ok circle { fill: var(--ok); }
.node.error circle { fill: var(--error); }
.node.paused circle { fill: var(--paused); }
.node.offline circle { fill: var(--offline); }
.node.unmonitored circle { stroke: var(--muted); stroke-dasharray: 4 3; fill-opacity: .55; }
.node .sub { font-size: 10px; fill: var(--muted); }

/* matrix */
.matrix { border-collapse: collapse; width: 100%; font-size: .85rem; }
.matrix th, .matrix td { border: 1px solid var(--line); padding: .35rem .5rem; text-align: left; vertical-align: top; }
.matrix th { background: var(--card); font-weight: 600; }
.matrix th a { text-decoration: none; }
.matrix th a:hover { text-decoration: underline; }
.matrix .empty { color: var(--line); text-align: center; }
.matrix .cell { border-left: 5px solid var(--unknown); }
.matrix .cell.ok { border-left-color: var(--ok); }
.matrix .cell.syncing { border-left-color: var(--syncing); }
.matrix .cell.scanning { border-left-color: var(--scanning); }
.matrix .cell.error { border-left-color: var(--error); }
.matrix .cell.paused { border-left-color: var(--paused); }
.matrix .cell.offline { border-left-color: var(--offline); }
.matrix .cell.flag { border-left-color: var(--flag); background: color-mix(in srgb, var(--flag) 12%, transparent); }
.state { font-weight: 600; }
.num { color: var(--muted); display: block; }

.legend { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; margin-top: .75rem; font-size: .8rem; color: var(--muted); }
.legend span::before { content: ""; display: inline-block; width: .7rem; height: .7rem; border-radius: 2px; margin-right: .35rem; vertical-align: -1px; background: var(--c); }
.warn { background: color-mix(in srgb, var(--paused) 15%, transparent); border-radius: 8px; padding: .5rem .75rem; margin-top: 1rem; }
footer { margin-top: 2.5rem; color: var(--muted); font-size: .8rem; }
"""

_LEGEND = [
    ("ok", "idle / in sync"),
    ("syncing", "syncing / out of sync"),
    ("scanning", "scanning"),
    ("error", "error / unreachable"),
    ("paused", "paused"),
    ("offline", "offline"),
    ("flag", "offered, not accepted"),
    ("unknown", "unknown"),
]


def _percent(value: float) -> str:
    """``100%`` for whole numbers, one decimal otherwise."""
    return f"{value:.0f}%" if abs(value - round(value)) < 0.05 else f"{value:.1f}%"


def _gui_link(url: str, text: str) -> str:
    """Link to a host's Syncthing GUI; the API key cannot log the browser in, so it is a plain link."""
    return f'<a href="{escape(url, quote=True)}" title="Open the Syncthing GUI">{text}</a>'


def _device_heading(d: Device) -> str:
    """Name plus 'monitored · reachable' sub line, linked to the GUI for monitored devices."""
    name = _gui_link(d.url, escape(d.name)) if d.url else escape(d.name)
    kind = "monitored" if d.monitored else "unmonitored"
    return f'{name}<span class="sub">{kind} · {escape(d.status_text)}</span>'


# --- sections -----------------------------------------------------------------


def _host_strip(ov: Overview) -> str:
    parts = ['<div class="hosts">']
    for h in ov.hosts:
        cls = "ok" if h.reachable else "error"
        badge = f'<span class="badge {cls}">{"reachable" if h.reachable else "unreachable"}</span>'
        parts.append(f'<div class="host {cls}"><div class="host-name">{_gui_link(h.url, escape(h.name) + " " + badge)}</div>')
        if h.reachable:
            peers = sum(1 for d in h.devices if d != h.my_id)
            errors = h.system_errors + sum(1 for s in h.folder_status.values() if s.error or s.errors)
            rows = [
                ("Version", escape(h.version or "?")),
                ("Peers", f"{h.connected_peers} / {peers} connected"),
                ("Folders", str(len(h.folders))),
                ("Errors", f'{errors} <span class="badge error">!</span>' if errors else "0"),
            ]
            if h.pending_folders:
                labels = ", ".join(escape(p["label"]) for p in h.pending_folders.values())
                rows.append(("Offered", f'<span class="badge flag">{len(h.pending_folders)}</span> {labels}'))
            parts.append("<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>")
        else:
            parts.append(f'<div class="host-error">{escape(h.error or "no answer")}</div>')
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def _topology(ov: Overview) -> str:
    """Devices on a circle, one line per pair of devices that share folders.

    Node labels sit outside the circle, edge labels at 38 % of the line, so that
    crossing diagonals and labels do not land on each other. No layout engine:
    the picture must be the same on every run.
    """
    devices = ov.devices
    n = len(devices)
    if n == 0:
        return '<p class="meta">No devices known.</p>'
    radius = max(120, 34 * n)
    cx, cy = radius + 190, radius + 80  # margins for the labels
    angle = {d.id: -math.pi / 2 + 2 * math.pi * i / n for i, d in enumerate(devices)}
    pos = {d.id: (cx + radius * math.cos(angle[d.id]), cy + radius * math.sin(angle[d.id])) for d in devices}
    if n == 1:
        pos[devices[0].id] = (cx, cy)
    folder_label = {f.id: f.label for f in ov.folders}

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {2 * cx} {2 * cy}" width="{2 * cx}" height="{2 * cy}" '
        'role="img" aria-label="Topology of Syncthing devices">'
    ]
    for e in ov.edges:
        (x1, y1), (x2, y2) = pos[e.a], pos[e.b]
        lx, ly = x1 + 0.38 * (x2 - x1), y1 + 0.38 * (y2 - y1)
        tip = f"{ov.device(e.a).name} – {ov.device(e.b).name}: {e.state}\n" + "\n".join(folder_label[f] for f in e.folders)
        out.append(
            f"<g><title>{escape(tip)}</title>"
            f'<line class="edge {e.state}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="9" fill="var(--card)"/>'
            f'<text class="edge-label" x="{lx:.1f}" y="{ly + 4:.1f}">{len(e.folders)}</text></g>'
        )
    for d in devices:
        x, y = pos[d.id]
        a = angle[d.id]
        tip = [d.name, d.id, d.status_text, d.version, f"{d.folder_count} folder(s)", d.error]
        # label 32 px outward from the node; anchor follows the side of the circle
        lx, ly = x + 32 * math.cos(a), y + 32 * math.sin(a)
        anchor = "start" if math.cos(a) > 0.3 else "end" if math.cos(a) < -0.3 else "middle"
        if anchor == "middle":
            ly += 14 if math.sin(a) > 0 else -10
        kind = "monitored" if d.monitored else "unmonitored"
        out.append(
            f'<g class="node {d.category} {kind}"><title>{escape(chr(10).join(t for t in tip if t))}</title>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="22"/>'
            f'<text x="{lx:.1f}" y="{ly:.1f}" style="text-anchor:{anchor}">{escape(d.name)}</text>'
            f'<text class="sub" x="{lx:.1f}" y="{ly + 13:.1f}" style="text-anchor:{anchor}">{kind} · {escape(d.status_text)}</text></g>'
        )
    out.append("</svg>")
    return f'<div class="topology">{"".join(out)}</div>'


def _cell_html(cell: Cell | None) -> str:
    if cell is None:
        return '<td class="empty">·</td>'
    nums = []
    if cell.completion is not None:
        nums.append(_percent(cell.completion))
    if cell.need_items:
        nums.append(f"{cell.need_items} item{'s' if cell.need_items != 1 else ''} needed")
    title = f' title="{escape(cell.detail, quote=True)}"' if cell.detail else ""
    flag = ' <span class="badge flag">!</span>' if cell.flagged else ""
    num = f'<span class="num">{escape(", ".join(nums))}</span>' if nums else ""
    return f'<td class="cell {cell.category}"{title}><span class="state">{escape(cell.state)}</span>{flag}{num}</td>'


def _matrix(ov: Overview) -> str:
    if not ov.folders:
        return '<p class="meta">No folders known.</p>'
    head = "".join(f"<th>{_device_heading(d)}</th>" for d in ov.devices)
    rows = []
    for f in ov.folders:
        kind = f'<span class="sub">{escape(f.type)}</span>' if f.type and f.type != "sendreceive" else ""
        cells = "".join(_cell_html(ov.cells.get((f.id, d.id))) for d in ov.devices)
        rows.append(f'<tr><th title="{escape(f.id, quote=True)}">{escape(f.label)}{kind}</th>{cells}</tr>')
    return f'<table class="matrix"><thead><tr><th>Folder</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _legend() -> str:
    return '<div class="legend">' + "".join(f'<span style="--c: var(--{c})">{t}</span>' for c, t in _LEGEND) + "</div>"


def render(ov: Overview, refresh: int | None = None, title: str = "Syncthing overview") -> str:
    """Return the complete HTML document; ``refresh`` adds a meta refresh in seconds."""
    refresh_tag = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    generated = ov.generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    reachable = sum(1 for h in ov.hosts if h.reachable)
    monitored = sum(1 for d in ov.devices if d.monitored)
    warn = ""
    if ov.unplaced_hosts:
        names = ", ".join(escape(n) for n in ov.unplaced_hosts)
        warn = (
            f'<div class="warn">Unreachable and not known by name to any other host, so not shown in the graph '
            f"or matrix: {names}. Name the device the same way on a peer to place it.</div>"
        )
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
{warn}
<h2>Topology</h2>
{_topology(ov)}
<h2>Folders × devices</h2>
{_matrix(ov)}
{_legend()}
<footer>syncthing-dashboard {escape(__version__)} · standard library only · hover a node, edge or cell for details</footer>
</body>
</html>
"""
