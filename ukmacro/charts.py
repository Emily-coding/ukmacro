"""Render chart JSON (the repo's common chart format) to PNG.

House style, used for every PNG:
    size      25 x 15 cm at 200 dpi (1969 x 1181 px), saved as a 256-colour PNG
    font      Source Sans 3 (SIL Open Font License, in assets/fonts/), so output is
              identical on a laptop and on GitHub Actions
    colours   a theme from THEMES (DEFAULT_THEME is used unless render() is given
              one): series colours in fixed order (colour follows the series' position
              in the chart, never its value), totals / reference lines in the theme's
              ink, and its grey scale for text, axes and gridlines
    marks     2pt lines, hairline horizontal gridlines only, no chart border,
              legend above the plot, direct value labels at line ends

A series can set "slot": n to pin its colour, so one category keeps the same colour
across related charts, or "color": "neutral" for a grey (e.g. data not available).
Series beyond the fourth are grey (see _colour).

Chart types: line; bar (several series sit side by side); stacked-bar (positive and
negative parts stack away from zero); in both bar types a series with "mark": "line" is
drawn as a line on top; grouped-hbar (categories down the side).
"""

from __future__ import annotations

import io
import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from PIL import Image  # noqa: E402

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
for f in FONTS.glob("*.ttf"):
    font_manager.fontManager.addfont(str(f))

# Colour themes. Series colours are used in this fixed order; neutrals carry all
# text, axes and gridlines. "reference" is the dataviz skill's validated palette; the
# others are built from the "Professional UI colour palettes" scales (Refactoring UI
# style) by svengraziani/ui-design: one or two strong hues for data plus the matching
# grey scale. Every series pair below passes a colour-blind check (worst simulated
# separation >= 8 in OKLab x100; normal-vision separation >= 15).
THEMES = {
    "reference": {
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
        "ink": "#0b0b0b", "text_2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "baseline": "#c3c2b7", "surface": "#fcfcfb"},
    # Blue + Yellow Vivid + Blue Grey (palette 2), teal as the third series
    "blue-amber": {
        "series": ["#186FAF", "#DE911D", "#27AB83", "#BA2525"],
        "ink": "#102A43", "text_2": "#486581", "muted": "#627D98",
        "grid": "#D9E2EC", "baseline": "#9FB3C8", "surface": "#FFFFFF"},
    # Cyan + Warm Grey (palette 7), amber and red as supporting series
    "cyan-warm": {
        "series": ["#0E7C86", "#DE911D", "#BA2525", "#486581"],
        "ink": "#27241D", "text_2": "#625D52", "muted": "#857F72",
        "grid": "#E8E6E1", "baseline": "#B8B2A7", "surface": "#FAF9F7"},
    # Blue Vivid + Cool Grey (palette 8), red vivid and teal as supporting series
    "blue-red": {
        "series": ["#0967D2", "#E12D39", "#27AB83", "#DE911D"],
        "ink": "#1F2933", "text_2": "#52606D", "muted": "#7B8794",
        "grid": "#E4E7EB", "baseline": "#9AA5B1", "surface": "#F5F7FA"},
}
DEFAULT_THEME = "blue-amber"

# Figure size. Layout below is in centimetres (margins) and scales with the width
# (how much text fits per line), so changing the size keeps the layout intact.
WIDTH_CM, HEIGHT_CM = 25, 15
SIZE = (WIDTH_CM / 2.54, HEIGHT_CM / 2.54)
LEFT_CM, RIGHT_CM = 1.95, 1.35          # plot margins
TEXT_SCALE = (WIDTH_CM - LEFT_CM - RIGHT_CM) / 26.7  # usable width relative to the original 30 cm design


def _x(cm: float) -> float:
    """A horizontal position in cm from the left edge, as a figure fraction."""
    return cm / WIDTH_CM

DPI = 200


def use_theme(name: str) -> None:
    """Switch every colour used below (they are module-level so the drawing code stays short)."""
    global SERIES, INK, TEXT_2, MUTED, GRID, BASELINE, SURFACE
    t = THEMES[name]
    SERIES, INK, TEXT_2, MUTED = t["series"], t["ink"], t["text_2"], t["muted"]
    GRID, BASELINE, SURFACE = t["grid"], t["baseline"], t["surface"]
    plt.rcParams.update({
        "font.family": "Source Sans 3",
        "font.size": 11,
        "axes.edgecolor": BASELINE,
        "axes.labelcolor": TEXT_2,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": TEXT_2,
        "ytick.labelcolor": TEXT_2,
        "xtick.labelsize": 10.5,
        "ytick.labelsize": 10.5,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    })


use_theme(DEFAULT_THEME)


# ---------------------------------------------------------------- frame

def _colour(series: dict, position: int) -> str:
    """A series' colour: "color": "neutral" -> grey; else its pinned "slot", else its
    position. Past the palette (more than 4 series) it is grey too: rather than invent
    more colours, extra series become context (e.g. UK in colour, other countries grey)."""
    slot = series.get("slot", position)
    if series.get("color") == "neutral" or slot >= len(SERIES):
        return BASELINE
    return SERIES[slot]


def _frame(chart: dict, left_cm: float = LEFT_CM):
    """Figure with title, units line and source footer; returns (fig, ax).
    `left_cm` widens the plot's left margin (for long category labels)."""
    fig = plt.figure(figsize=SIZE, dpi=DPI)
    ax = fig.add_axes([_x(left_cm), 0.17, 1 - _x(left_cm) - _x(RIGHT_CM), 0.62])
    fig.text(_x(LEFT_CM), 0.93, chart["title"], fontsize=16, fontweight="semibold", color=INK, va="baseline")
    fig.text(_x(LEFT_CM), 0.875, chart["units"], fontsize=11.5, color=TEXT_2, va="baseline")
    foot = f"Source: {chart['source']}."
    if chart.get("note"):
        foot += f" {chart['note']}"
    fig.text(_x(LEFT_CM), 0.035, "\n".join(textwrap.wrap(foot, int(190 * TEXT_SCALE))),
             fontsize=9, color=MUTED, va="bottom")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(axis="both", length=0, pad=6)
    ax.grid(axis="y", color=GRID, linewidth=0.6, linestyle="-")
    ax.set_axisbelow(True)
    return fig, ax


def _legend(fig, handles, labels):
    """Legend in a row above the plot. One series needs none (the title names it).
    If the labels won't fit on one row (roughly 130 characters including the colour
    keys at 30 cm wide, scaled to the width), wrap onto two rows and shrink the plot."""
    if len(handles) < 2:
        return
    ncol = len(handles)
    if sum(len(lab) + 8 for lab in labels) > 130 * TEXT_SCALE:
        ncol = (len(handles) + 1) // 2
        for ax in fig.axes:
            x0, y0, w, h = ax.get_position().bounds
            ax.set_position([x0, y0, w, h - 0.05])
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(_x(LEFT_CM - 0.2), 0.86), ncol=ncol,
               frameon=False, fontsize=11, labelcolor=TEXT_2, handlelength=1.6, columnspacing=1.8)


def _period_ticks(ax, dates: list[str]):
    """Label the first period of each year with the year (works for any date format
    starting YYYY: 2019, 2019-Q1, 2019-01, 2019-01-31). At most about 12 labels."""
    idx = [i for i, d in enumerate(dates) if i == 0 or d[:4] != dates[i - 1][:4]]
    if len(idx) > 1 and dates[0][4:] not in ("", "-Q1", "-01"):
        idx = idx[1:]  # the first period isn't the start of its year: label from the next year
    step = max(1, len(idx) // 12)
    idx = idx[::step]
    ax.set_xticks(idx, [dates[i][:4] for i in idx])
    ax.set_xlim(-0.6, len(dates) - 0.4)


def _save(fig, path: Path) -> Path:
    """Save as a palette PNG: flat colours quantise cleanly and the file stays small."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI)
    plt.close(fig)
    buf.seek(0)
    Image.open(buf).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(
        path, format="PNG", optimize=True)
    return path


# ---------------------------------------------------------------- chart types

def _line(chart):
    """Lines, one per series. Each line ends in a direct label: its latest value for a
    coloured series, its name for a grey context series (greys can't be told apart by
    colour). Labels that would overlap are spread apart vertically."""
    fig, ax = _frame(chart)
    dates = [d["date"] for d in chart["data"]]
    x = range(len(dates))
    handles, ends = [], []
    for i, s in enumerate(chart["series"]):
        ys = [d.get(s["key"]) for d in chart["data"]]
        colour = _colour(s, i)
        (h,) = ax.plot(x, [y if y is not None else float("nan") for y in ys],
                       color=colour, linewidth=2, solid_capstyle="round",
                       zorder=3 if colour != BASELINE else 2)  # coloured lines above grey ones
        handles.append(h)
        present = [j for j, y in enumerate(ys) if y is not None]
        if present:
            j = present[-1]
            text = s["label"] if colour == BASELINE else f"{ys[j]:.1f}".replace("-", "\u2212")
            ends.append((j, ys[j], text))
    _period_ticks(ax, dates)
    _end_labels(fig, ax, ends)
    # grey context lines are named at their ends, so they stay out of the legend
    keep = [i for i, s in enumerate(chart["series"]) if _colour(s, i) != BASELINE]
    _legend(fig, [handles[i] for i in keep], [chart["series"][i]["label"] for i in keep])
    return fig


def _end_labels(fig, ax, ends: list[tuple[int, float, str]], min_gap_pt: float = 13):
    """Place labels just right of each line's last point. Labels that would overlap
    (their text spans the same horizontal space and they are closer than `min_gap_pt`
    vertically) are nudged upwards; labels on lines that end in different places are
    left where they are."""
    if not ends:
        return
    fig.canvas.draw()  # fix the axis limits so data -> screen positions are final
    to_pt = 72 / fig.dpi
    char_pt = 5.6  # rough width of one character at 10.5pt
    placed = []  # (x0, x1, y) in points of labels already placed
    final = {}
    for k, (j, y, text) in sorted(enumerate(ends), key=lambda e: e[1][1]):
        x_pt, y_pt = (v * to_pt for v in ax.transData.transform((j, y)))
        x0, x1 = x_pt + 6, x_pt + 6 + len(text) * char_pt
        # move up past every label it collides with; labels are placed bottom-up, so
        # one pass over them in height order is enough (no loop that could fail to end)
        for px0, px1, py in sorted(placed, key=lambda p: p[2]):
            if x0 < px1 and px0 < x1 and py - min_gap_pt < y_pt < py + min_gap_pt - 0.01:
                y_pt = py + min_gap_pt
        placed.append((x0, x1, y_pt))
        final[k] = y_pt
    for k, (j, y, text) in enumerate(ends):
        dy = final[k] - ax.transData.transform((j, y))[1] * to_pt
        ax.annotate(text, (j, y), xytext=(6, dy), textcoords="offset points",
                    va="center", fontsize=10.5, color=TEXT_2, annotation_clip=False)


def _bars(chart):
    """bar / stacked-bar. In a stacked-bar chart, bars stack away from zero by sign; in
    a plain bar chart, several series sit side by side. Either way a series with
    "mark": "line" is drawn as a line (in ink) on top."""
    fig, ax = _frame(chart)
    dates = [d["date"] for d in chart["data"]]
    x = list(range(len(dates)))
    stacked = chart["type"] == "stacked-bar"
    bar_series = [s for s in chart["series"] if s.get("mark") != "line"]
    n_side = 1 if stacked else max(1, len(bar_series))
    width = (0.72 if len(x) > 20 else 0.6) / n_side
    pos, neg = [0.0] * len(x), [0.0] * len(x)
    handles, labels, slot = [], [], 0
    for s in chart["series"]:
        ys = [d.get(s["key"]) or 0.0 for d in chart["data"]]  # a missing bar is drawn as nothing
        if s.get("mark") == "line":  # missing periods break the line rather than drop to zero
            line_ys = [d.get(s["key"]) if d.get(s["key"]) is not None else float("nan") for d in chart["data"]]
            (h,) = ax.plot(x, line_ys, color=INK, linewidth=1.6, marker="o", markersize=4.5,
                           markerfacecolor=INK, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
        else:
            if stacked:
                xs = x
                bottoms = [pos[j] if y >= 0 else neg[j] for j, y in enumerate(ys)]
                for j, y in enumerate(ys):
                    if y >= 0:
                        pos[j] += y
                    else:
                        neg[j] += y
            else:  # side by side, centred on the period
                k = bar_series.index(s)
                xs = [j + (k - (n_side - 1) / 2) * width for j in x]
                bottoms = [0.0] * len(x)
            h = ax.bar(xs, ys, bottom=bottoms, width=width, color=_colour(s, slot),
                       edgecolor=SURFACE, linewidth=1.0, zorder=3)  # surface gap between segments
            slot += s.get("color") != "neutral"  # a grey series doesn't use up a colour
        handles.append(h)
        labels.append(s["label"])
    ax.axhline(0, color=BASELINE, linewidth=0.9, zorder=2)
    _period_ticks(ax, dates)
    _legend(fig, handles, labels)
    return fig


def _grouped_hbar(chart):
    """Categories down the side (data[].date holds the category), one bar per series."""
    longest = max(len(str(d["date"])) for d in chart["data"])
    fig, ax = _frame(chart, left_cm=max(LEFT_CM, 0.6 + longest * 0.186))  # room for category labels
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    cats = [d["date"] for d in chart["data"]]
    n = len(chart["series"])
    h_bar = 0.8 / n
    handles = []
    for i, s in enumerate(chart["series"]):
        ys = [d.get(s["key"]) or 0.0 for d in chart["data"]]
        pos = [c + (i - (n - 1) / 2) * h_bar for c in range(len(cats))]
        handles.append(ax.barh(pos, ys, height=h_bar * 0.92, color=_colour(s, i), zorder=3))
        for p, y in zip(pos, ys):
            ax.annotate(f"{y:+.2f}".replace("-", "\u2212"), (y, p), xytext=(5 if y >= 0 else -5, 0), textcoords="offset points",
                        ha="left" if y >= 0 else "right", va="center", fontsize=10, color=TEXT_2)
    ax.set_yticks(range(len(cats)), cats)
    ax.invert_yaxis()
    ax.spines["bottom"].set_visible(False)
    ax.axvline(0, color=BASELINE, linewidth=0.9, zorder=2)
    lo, hi = ax.get_xlim()
    pad = (hi - lo) * 0.08  # room for the value labels
    ax.set_xlim(lo - pad, hi + pad)
    _legend(fig, handles, [s["label"] for s in chart["series"]])
    return fig


def _fill_periods(chart: dict) -> dict:
    """Insert empty rows for missing quarters/months so the x-axis is a true timeline."""
    dates = [d["date"] for d in chart["data"]]
    if chart["type"] == "grouped-hbar" or not dates:
        return chart
    # `step` gives the next period after d
    if all(len(d) == 7 and d[5] == "Q" for d in dates):
        step = lambda d: f"{d[:4]}-Q{int(d[6]) % 4 + 1}" if d[6] != "4" else f"{int(d[:4]) + 1}-Q1"  # noqa: E731
    elif all(len(d) == 7 and d[4] == "-" and d[5:].isdigit() for d in dates):
        step = lambda d: f"{d[:4]}-{int(d[5:]) + 1:02d}" if d[5:] != "12" else f"{int(d[:4]) + 1}-01"  # noqa: E731
    else:
        return chart  # annual or irregular dates (e.g. BICS waves): leave as they are
    have = {d["date"]: d for d in chart["data"]}
    full, d = [], dates[0]
    while d <= dates[-1]:
        full.append(have.get(d, {"date": d}))
        d = step(d)
    return {**chart, "data": full}


RENDERERS = {"line": _line, "bar": _bars, "stacked-bar": _bars, "grouped-hbar": _grouped_hbar}


def render(chart: dict, path: Path, theme: str | None = None) -> Path:
    """Render a chart (common JSON format) to a PNG at `path`; returns the path."""
    use_theme(theme or DEFAULT_THEME)
    return _save(RENDERERS[chart["type"]](_fill_periods(chart)), path)


def publish(chart: dict, json_path: Path, png_path: Path) -> None:
    """Write a chart's JSON and its PNG. The PNG is only re-rendered when the JSON
    changed: PNG bytes vary slightly between machines, and an unchanged chart
    shouldn't produce a daily commit. The theme and size are stored in the JSON so
    that changing either also counts as a change."""
    chart["theme"] = DEFAULT_THEME
    chart["size_cm"] = [WIDTH_CM, HEIGHT_CM]
    text = json.dumps(chart, indent=1) + "\n"
    if png_path.exists() and json_path.exists() and json_path.read_text() == text:
        return
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(text)
    if chart.get("type") in RENDERERS and chart.get("series") and chart.get("data"):
        render(chart, png_path)
