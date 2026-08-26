COLORS = [
    "#e63946", "#457b9d", "#2a9d8f", "#f4a261", "#8338ec", "#ffb703", "#06d6a0",
    "#ef476f", "#118ab2", "#073b4c", "#ffd166", "#06aed5", "#f15bb5", "#9b5de5",
    "#00bbf9", "#00f5d4", "#fee440", "#f77f00", "#d62828", "#003049", "#3a86ff",
    "#fb5607", "#ff006e", "#8ac926", "#1982c4", "#6a4c93", "#ff595e", "#ffca3a",
    "#c1121f", "#780000", "#005f73", "#0a9396", "#94d2bd", "#ee9b00", "#ca6702",
    "#bb3e03", "#9d0208",
]

WIDTH, HEIGHT = 900, 500
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 64, 40, 74, 50

FONT_STACK = "'Times New Roman', Times, serif"

STEP_CANDIDATES = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]
import math
import re


def nice_bounds(min_v, max_v, max_ticks=6):
    """Pick a clean step (a multiple of 5, scaling up as the range grows) and
    snap the axis bounds out to that step, so gridlines read as round numbers
    like 0/5/10/15/20 or 0/500/1000/1500 instead of raw padded decimals."""
    if min_v == max_v:
        min_v -= 1
        max_v += 1
    span = max_v - min_v
    step = STEP_CANDIDATES[-1]
    for c in STEP_CANDIDATES:
        if span / c <= max_ticks:
            step = c
            break
    nice_min = math.floor(min_v / step) * step
    nice_max = math.ceil(max_v / step) * step
    ticks = []
    v = nice_min
    while v <= nice_max + 1e-9:
        ticks.append(v)
        v += step
    return nice_min, nice_max, ticks

LABEL_COLOR = {
    "once": "#6b7280",
    "active": "#d62828",
    "push": "#e36414",
    "off": "#118ab2",
}


def fmt(v):
    """Human-friendly number formatting: whole numbers for big values, 2dp for small."""
    if abs(v) >= 100:
        return f"{v:.0f}"
    if abs(v) >= 1:
        return f"{v:.1f}"
    return f"{v:.2f}"


def generate_svg_graph(sim, path="run_graph.html", title="Simulation Output"):
    history = sim.history
    events = getattr(sim, "events", [])
    if not history:
        raise ValueError("No history to plot")

    series_items = list(history.items())
    num_series = len(series_items)
    node_color = {node_id: COLORS[idx % len(COLORS)] for idx, (node_id, _) in enumerate(series_items)}

    num_ticks = max(len(v) for v in history.values())

    # --- Per-series scaling -----------------------------------------------
    # Each series is normalized to its OWN min/max, not a shared range.
    # This means a series moving between 10-40 and one moving between
    # 0-4000 both fill the full plot height, so shape-over-time stays
    # visible no matter how different the magnitudes are.
    series_range = {}
    series_ticks = {}
    for node_id, series in series_items:
        nice_min, nice_max, ticks = nice_bounds(min(series), max(series))
        series_range[node_id] = (nice_min, nice_max)
        series_ticks[node_id] = ticks

    # Legend gets denser as node count grows: smaller text/markers, and the
    # verbose "range X-Y, now Z" detail drops out past a point (it's still
    # available on the chart itself via each line's start/end labels, so
    # nothing is lost — the legend just stops trying to repeat it when there's
    # no room to do so cleanly).
    if num_series <= 8:
        legend_font, legend_marker, item_w, row_h = 12, 11, 260, 20
        show_range = True
    elif num_series <= 20:
        legend_font, legend_marker, item_w, row_h = 11, 9, 170, 17
        show_range = False
    else:
        legend_font, legend_marker, item_w, row_h = 10, 7, 120, 15
        show_range = False

    legend_cols = max(1, WIDTH // item_w)
    legend_rows = -(-num_series // legend_cols)
    legend_block_h = legend_rows * row_h + 10

    width = WIDTH
    height = max(HEIGHT, PAD_TOP + legend_block_h + PAD_BOTTOM + 220)

    plot_w = width - PAD_LEFT - PAD_RIGHT
    plot_h = height - PAD_TOP - PAD_BOTTOM - legend_block_h - 20
    plot_top = PAD_TOP + legend_block_h + 20

    def x_pos(i):
        if num_ticks <= 1:
            return PAD_LEFT
        return PAD_LEFT + (i / (num_ticks - 1)) * plot_w

    def y_pos_for(node_id, v):
        s_min, s_max = series_range[node_id]
        pct = (v - s_min) / (s_max - s_min)
        return plot_top + plot_h - pct * plot_h

    svg_parts = []

    svg_parts.append(f"""
<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
     style="background:#f7f8fa;font-family:{FONT_STACK}">
  <defs>
    <linearGradient id="cardBg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#fbfbfd"/>
    </linearGradient>
    <filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="2" stdDeviation="4" flood-color="#1a1a1a" flood-opacity="0.08"/>
    </filter>
  </defs>
""")

    svg_parts.append(
        f'<rect x="10" y="10" width="{width-20}" height="{height-20}" rx="14" '
        f'fill="url(#cardBg)" stroke="#e5e7eb" stroke-width="1" filter="url(#softShadow)" />'
    )

    svg_parts.append(
        f'<text x="28" y="30" font-size="16" font-weight="600" fill="#1f2937">{title}</text>'
    )
    svg_parts.append(
        f'<text x="28" y="50" font-size="11" fill="#9ca3af">'
        f'each line is scaled to its own min/max — compare shape, not shared height</text>'
    )

    # --- Call-type legend: what the dashed vertical markers mean, drawn with
    # the same actual marker shapes used on the chart (not text symbols),
    # placed on its own line so it doesn't get confused with the axis label.
    ct_x = width - PAD_RIGHT - 230
    ct_y = 50
    svg_parts.append(f'<circle cx="{ct_x}" cy="{ct_y - 4}" r="4" fill="#374151" />')
    svg_parts.append(
        f'<text x="{ct_x + 10}" y="{ct_y}" font-size="11" fill="#6b7280">'
        f'internal call (node \u2192 node)</text>'
    )
    ct_x2 = ct_x + 140
    svg_parts.append(f'<circle cx="{ct_x2}" cy="{ct_y - 4}" r="4" fill="white" stroke="#374151" stroke-width="1.5" />')
    svg_parts.append(
        f'<text x="{ct_x2 + 10}" y="{ct_y}" font-size="11" fill="#6b7280">'
        f'external call (.sm inject)</text>'
    )

    # --- Legend: a true grid, columns computed from available width ---------
    legend_col_w = min(item_w, plot_w / legend_cols)
    for idx, (node_id, series) in enumerate(series_items):
        color = node_color[node_id]
        node_name = sim.registry[node_id].name
        col = idx // legend_rows
        row = idx % legend_rows
        legend_x = PAD_LEFT + col * legend_col_w
        legend_y = PAD_TOP + 16 + row * row_h
        svg_parts.append(
            f'<rect x="{legend_x}" y="{legend_y}" width="{legend_marker}" height="{legend_marker}" '
            f'rx="3" fill="{color}" />'
        )
        if show_range:
            s_min_raw, s_max_raw = min(series), max(series)
            label = (
                f'{node_name} <tspan fill="#9ca3af">({node_id})</tspan> '
                f'<tspan fill="#9ca3af">range {fmt(s_min_raw)}\u2013{fmt(s_max_raw)}, now {fmt(series[-1])}</tspan>'
            )
        else:
            label = f'{node_name} <tspan fill="#9ca3af">({node_id})</tspan>'
        svg_parts.append(
            f'<text x="{legend_x + legend_marker + 5}" y="{legend_y + legend_marker - 1}" '
            f'font-size="{legend_font}" fill="#374151">{label}</text>'
        )

    # --- Gridlines: real values from the primary (first) series, snapped to a
    # clean multiple-of-5 step that scales with that series' own range. Other
    # series keep their own independent vertical scale (see y_pos_for), so
    # their real values are shown at the legend and at each line's endpoint
    # instead of cluttering a second axis.
    primary_id = series_items[0][0]
    primary_color = node_color[primary_id]
    for tick_val in series_ticks[primary_id]:
        y = y_pos_for(primary_id, tick_val)
        svg_parts.append(
            f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{PAD_LEFT + plot_w}" y2="{y:.1f}" '
            f'stroke="#eef0f3" stroke-width="1" />'
        )
        svg_parts.append(
            f'<text x="{PAD_LEFT - 10}" y="{y + 4:.1f}" font-size="11" fill="{primary_color}" '
            f'text-anchor="end">{fmt(tick_val)}</text>'
        )

    step = max(1, num_ticks // 10)
    for i in range(0, num_ticks, step):
        x = x_pos(i)
        svg_parts.append(
            f'<line x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_top + plot_h}" '
            f'stroke="#f3f4f6" stroke-width="1" />'
        )
        svg_parts.append(
            f'<text x="{x:.1f}" y="{plot_top + plot_h + 20}" font-size="11" fill="#6b7280" '
            f'text-anchor="middle">{i}</text>'
        )

    svg_parts.append(
        f'<line x1="{PAD_LEFT}" y1="{plot_top}" x2="{PAD_LEFT}" y2="{plot_top + plot_h}" '
        f'stroke="#9ca3af" stroke-width="1.5" />'
    )
    svg_parts.append(
        f'<line x1="{PAD_LEFT}" y1="{plot_top + plot_h}" x2="{PAD_LEFT + plot_w}" '
        f'y2="{plot_top + plot_h}" stroke="#9ca3af" stroke-width="1.5" />'
    )

    # --- Event markers (dashed vertical lines + dot at top) ----------------
    for ev in events:
        tick = ev["tick"]
        x = x_pos(tick)
        color = LABEL_COLOR.get(ev["label"], "#6b7280")
        origin = "external (.sm inject)" if ev["external"] else f'internal ({sim.registry[ev["source_id"]].name})'
        target_name = sim.registry[ev["target_id"]].name
        tooltip = f'tick {tick}: {origin} -> {target_name}.{ev["func_name"]}({", ".join(map(str, ev["args"]))}) [{ev["label"]}] {ev["effect"]}'
        svg_parts.append(
            f'<line x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_top + plot_h}" '
            f'stroke="{color}" stroke-width="1" stroke-dasharray="3,3" opacity="0.55" />'
        )
        marker_y = plot_top - 6
        if ev["external"]:
            svg_parts.append(
                f'<circle cx="{x:.1f}" cy="{marker_y}" r="3.5" fill="white" stroke="{color}" stroke-width="1.5">'
                f'<title>{tooltip}</title></circle>'
            )
        else:
            svg_parts.append(
                f'<circle cx="{x:.1f}" cy="{marker_y}" r="3.5" fill="{color}">'
                f'<title>{tooltip}</title></circle>'
            )

    # --- Data lines, each on its own normalized scale -----------------------
    for idx, (node_id, series) in enumerate(series_items):
        color = node_color[node_id]
        points = " ".join(f"{x_pos(i):.1f},{y_pos_for(node_id, v):.1f}" for i, v in enumerate(series))
        svg_parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.25" '
            f'stroke-linejoin="round" stroke-linecap="round" opacity="0.92" />'
        )
        # starting value: small hollow marker + label so it's clear at a glance
        # where each line began, without having to cross-reference the legend
        start_x, start_y = x_pos(0), y_pos_for(node_id, series[0])
        svg_parts.append(
            f'<circle cx="{start_x:.1f}" cy="{start_y:.1f}" r="3.5" fill="white" '
            f'stroke="{color}" stroke-width="1.5" />'
        )
        svg_parts.append(
            f'<text x="{start_x + 8:.1f}" y="{start_y - 8:.1f}" font-size="10" fill="{color}" '
            f'opacity="0.85">start {fmt(series[0])}</text>'
        )

        last_x, last_y = x_pos(num_ticks - 1), y_pos_for(node_id, series[-1])
        svg_parts.append(
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" fill="{color}" '
            f'stroke="#ffffff" stroke-width="1.5" />'
        )
        # actual value label right next to the line's endpoint
        svg_parts.append(
            f'<text x="{last_x + 8:.1f}" y="{last_y + 4:.1f}" font-size="11" fill="{color}" '
            f'font-weight="600">{fmt(series[-1])}</text>'
        )

    svg_parts.append(
        f'<text x="{PAD_LEFT + plot_w/2}" y="{height - 14}" font-size="12" fill="#6b7280" '
        f'text-anchor="middle">tick</text>'
    )
    svg_parts.append("</svg>")

    log_lines = getattr(sim, "log", [])

    def colorize_log_line(line):
        esc = (
            line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        if esc.strip().startswith("[tick"):
            return f'<div style="color:#9ca3af;margin-top:6px;font-weight:700">{esc}</div>'
        for lbl, color in LABEL_COLOR.items():
            if f"[{lbl}" in esc:
                esc = re.sub(
                    rf"(\[{lbl}[^\]]*\])",
                    rf'<span style="color:{color};font-weight:600">\1</span>',
                    esc,
                )
                break
        origin_color = "#9ca3af" if esc.strip().startswith("EXTERNAL") else "#374151"
        return f'<div style="color:{origin_color};padding-left:12px">{esc}</div>'

    log_html = "".join(colorize_log_line(l) for l in log_lines) if log_lines else (
        '<div style="color:#9ca3af">No log output for this run.</div>'
    )
    events_table = (
        f'<div style="font-family:Consolas,Menlo,\'Courier New\',monospace;'
        f'font-size:12.5px;line-height:1.5;background:#fbfbfd;border:1px solid #eef0f3;'
        f'border-radius:8px;padding:12px 14px;max-height:420px;overflow-y:auto;'
        f'white-space:pre-wrap">{log_html}</div>'
    )

    active_rows = []
    for (source_id, target_id, func_name), info in sim.behaviors.items():
        source = "external stimulus" if source_id == "EXTERNAL" else f'{sim.registry[source_id].name} ({source_id})'
        target = f'{sim.registry[target_id].name} ({target_id})'
        active_rows.append(
            f'<li><b>{source}</b> is holding <b>{target}.{func_name}</b> '
            f'[{info["label"]}] \u2014 target\'s decay is paused</li>'
        )
    active_html = (
        f'<ul style="margin:8px 0 0 0;padding-left:20px;font-size:13px;color:#374151">{"".join(active_rows)}</ul>'
        if active_rows else
        '<p style="color:#9ca3af;font-size:13px;margin:8px 0 0 0">No behaviors still active/pushing at the end of the run.</p>'
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Dile run graph</title>
<style>
  body {{
    margin: 0;
    padding: 32px;
    background: #eef1f5;
    font-family: {FONT_STACK};
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 24px;
  }}
  .card {{
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    box-shadow: 0 2px 4px rgba(26,26,26,0.08);
    padding: 20px 24px;
    width: {width - 20}px;
    box-sizing: border-box;
  }}
  .card h3 {{ margin: 0 0 4px 0; font-size: 15px; color: #1f2937; }}
</style>
</head>
<body>
{''.join(svg_parts)}
<div class="card">
  <h3>Event log</h3>
  {events_table}
</div>
<div class="card">
  <h3>Still active at end of run</h3>
  {active_html}
</div>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path