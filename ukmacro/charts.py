"""Render chart JSON (the repo's common chart format) to PNG.

House style, used for every PNG:
    size      30 x 15 cm at 200 dpi (2362 x 1181 px), saved as a 256-colour PNG
    font      Source Sans 3 (SIL Open Font License, in assets/fonts/), so output is
              identical on a laptop and on GitHub Actions
    colours   a theme from THEMES (DEFAULT_THEME is used unless render() is given
              one): series colours in fixed order (colour follows the series' position
              in the chart, never its value), totals / reference lines in the theme's
              ink, and its grey scale for text, axes and gridlines
    marks     2pt lines, hairline horizontal gridlines only, no chart border,
              legend above the plot, direct value labels at line ends

Chart types: line, bar (single series), stacked-bar (positive and negative parts stack
away from zero; a series with "mark": "line" is drawn as a line on top), grouped-hbar.
"""

from __future__ import annotations

import io
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

CM = 1 / 2.54
SIZE = (30 * CM, 15 * CM)
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

def _frame(chart: dict, left: float = 0.065):
    """Figure with title, units line and source footer; returns (fig, ax).
    `left` widens the plot's left margin (for long category labels)."""
    fig = plt.figure(figsize=SIZE, dpi=DPI)
    ax = fig.add_axes([left, 0.17, 0.955 - left, 0.62])
    fig.text(0.065, 0.93, chart["title"], fontsize=16, fontweight="semibold", color=INK, va="baseline")
    fig.text(0.065, 0.875, chart["units"], fontsize=11.5, color=TEXT_2, va="baseline")
    foot = f"Source: {chart['source']}."
    if chart.get("note"):
        foot += f" {chart['note']}"
    fig.text(0.065, 0.035, "\n".join(textwrap.wrap(foot, 190)), fontsize=9, color=MUTED, va="bottom")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(axis="both", length=0, pad=6)
    ax.grid(axis="y", color=GRID, linewidth=0.6, linestyle="-")
    ax.set_axisbelow(True)
    return fig, ax


def _legend(fig, handles, labels):
    if len(handles) >= 2:  # one series needs no legend: the title names it
        fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.058, 0.86), ncol=len(handles),
                   frameon=False, fontsize=11, labelcolor=TEXT_2, handlelength=1.6, columnspacing=1.8)


def _period_ticks(ax, dates: list[str]):
    """Label the first period of each year only (dates like 2019-Q1 / 2019-01 / 2019)."""
    idx = [i for i, d in enumerate(dates) if len(d) == 4 or d.endswith(("-Q1", "-01"))]
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
    fig, ax = _frame(chart)
    dates = [d["date"] for d in chart["data"]]
    x = range(len(dates))
    handles = []
    for i, s in enumerate(chart["series"]):
        ys = [d.get(s["key"]) for d in chart["data"]]
        (h,) = ax.plot(x, [y if y is not None else float("nan") for y in ys],
                       color=SERIES[i], linewidth=2, solid_capstyle="round")
        handles.append(h)
        last = max(j for j, y in enumerate(ys) if y is not None)
        ax.annotate(f"{ys[last]:.1f}".replace("-", "\u2212"), (last, ys[last]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=10.5, color=TEXT_2)
    _period_ticks(ax, dates)
    _legend(fig, handles, [s["label"] for s in chart["series"]])
    return fig


def _bars(chart):
    """bar / stacked-bar: bars stack away from zero by sign; 'mark: line' series overlay."""
    fig, ax = _frame(chart)
    dates = [d["date"] for d in chart["data"]]
    x = list(range(len(dates)))
    pos, neg = [0.0] * len(x), [0.0] * len(x)
    handles, labels, slot = [], [], 0
    width = 0.72 if len(x) > 20 else 0.6
    for s in chart["series"]:
        ys = [d.get(s["key"]) or 0.0 for d in chart["data"]]
        if s.get("mark") == "line":
            (h,) = ax.plot(x, ys, color=INK, linewidth=1.6, marker="o", markersize=4.5,
                           markerfacecolor=INK, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
        else:
            bottoms = [pos[j] if y >= 0 else neg[j] for j, y in enumerate(ys)]
            h = ax.bar(x, ys, bottom=bottoms, width=width, color=SERIES[slot],
                       edgecolor=SURFACE, linewidth=1.0, zorder=3)  # 2px surface gap between segments
            for j, y in enumerate(ys):
                if y >= 0:
                    pos[j] += y
                else:
                    neg[j] += y
            slot += 1
        handles.append(h)
        labels.append(s["label"])
    ax.axhline(0, color=BASELINE, linewidth=0.9, zorder=2)
    _period_ticks(ax, dates)
    _legend(fig, handles, labels)
    return fig


def _grouped_hbar(chart):
    """Categories down the side (data[].date holds the category), one bar per series."""
    longest = max(len(str(d["date"])) for d in chart["data"])
    fig, ax = _frame(chart, left=max(0.065, 0.02 + longest * 0.0062))  # room for category labels
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    cats = [d["date"] for d in chart["data"]]
    n = len(chart["series"])
    h_bar = 0.8 / n
    handles = []
    for i, s in enumerate(chart["series"]):
        ys = [d.get(s["key"]) or 0.0 for d in chart["data"]]
        pos = [c + (i - (n - 1) / 2) * h_bar for c in range(len(cats))]
        handles.append(ax.barh(pos, ys, height=h_bar * 0.92, color=SERIES[i], zorder=3))
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


RENDERERS = {"line": _line, "bar": _bars, "stacked-bar": _bars, "grouped-hbar": _grouped_hbar}


def render(chart: dict, path: Path, theme: str | None = None) -> Path:
    use_theme(theme or DEFAULT_THEME)
    return _save(RENDERERS[chart["type"]](chart), path)
