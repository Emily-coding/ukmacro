#!/usr/bin/env python3
"""US real GDP per capita growth since 1800, with recession bouncebacks hatched.

Two charts, each as a line (quarterly from 1948) and as bars (annual throughout):
  us-gdp-per-capita-growth            growth on a year earlier
  us-gdp-per-capita-growth-vs-peak    growth on the higher of a year earlier and the
                                      previous all-time peak, so rebounds that only
                                      regain lost ground don't count as growth

Data:
  1801-1928  Maddison Project Database 2023, annual GDP per capita (2011 dollars)
  1929-1947  BEA annual real GDP (FRED GDPCA) divided by BEA population
             (B230RC0A052NBEA), chained 2017 dollars
  1947-      BEA real GDP per capita (FRED A939RX0Q048SBEA), quarterly, chained
             2017 dollars, seasonally adjusted; growth on the same quarter a year
             earlier from 1948 Q1
The annual series are rescaled to join the next source (BEA annual to the 1947 average
of the quarters, Maddison to BEA annual in 1929), so they form one level series and
the all-time peak runs across them (the Second World War peak matters for the late
1940s). Rescaling keeps each source's own growth rates: 1929 is Maddison's growth on
1928, 1930-47 are BEA's.

Bouncebacks: from each NBER business-cycle trough (dates from 1854) until GDP per
capita is back above its previous all-time high. On the annual data a short
recession may leave no annual fall, and then there is nothing to shade.

Run:  .venv/bin/python builders/us/gdp_per_capita.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "chart-house-style"))

import house_style as hs  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from ukmacro.http import get, get_text  # noqa: E402

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
QUARTERLY, ANNUAL_GDP, ANNUAL_POP = "A939RX0Q048SBEA", "GDPCA", "B230RC0A052NBEA"
MADDISON = "https://dataverse.nl/api/access/datafile/421302"   # Maddison Project Database 2023
NBER = "https://data.nber.org/data/cycles/business_cycle_dates.json"
OUT, IMG = REPO / "data" / "us", REPO / "img" / "us"
LINE = 15.0   # reference growth rate, %
SOURCE = ("Source: BEA via FRED, real GDP per capita (A939RX0Q048SBEA) quarterly from 1947, real GDP (GDPCA) "
          "over population (B230RC0A052NBEA) annual 1929-47; Maddison Project Database 2023 before 1929, rescaled "
          "to join BEA; NBER business-cycle dates; ukmacro calculations.")


def fred(series: str) -> list[tuple[date, float]]:
    """A FRED series as [(date, value)], without missing observations."""
    rows = list(csv.reader(io.StringIO(get_text(FRED + series))))[1:]
    return [(date.fromisoformat(r[0]), float(r[1])) for r in rows if r[1] not in ("", ".")]


def levels() -> list[tuple[date, float, str]]:
    """[(date, GDP per capita, "A" or "Q")], annual to 1947 then quarterly, on the scale of
    BEA's quarterly series. Annual values sit at mid-year, quarterly at mid-quarter."""
    wb = openpyxl.load_workbook(io.BytesIO(get(MADDISON, timeout=180)), read_only=True)
    rows = wb["Full data"].iter_rows(values_only=True)
    next(rows)
    mad = {r[3]: r[4] for r in rows if r[0] == "USA" and r[4] is not None and r[3] >= 1800}
    bea = [(date(d.year, d.month + 1, 15), v) for d, v in fred(QUARTERLY)]
    gdp, pop = ({d.year: v for d, v in fred(s)} for s in (ANNUAL_GDP, ANNUAL_POP))
    # per capita: both in FRED's units (billions of dollars, thousands of people)
    bea_a = {y: gdp[y] * 1e6 / pop[y] for y in gdp if y in pop and y <= 1947}
    # join backwards: BEA annual to the 1947 quarters, then Maddison to BEA annual
    scale = sum(v for d, v in bea if d.year == 1947) / 4 / bea_a[1947]
    bea_a = {y: v * scale for y, v in bea_a.items()}
    first = min(bea_a)
    scale = bea_a[first] / mad[first]
    years = [y for y in sorted(mad) if y < first and all(z in mad for z in range(y, first))]  # unbroken run
    return ([(date(y, 7, 1), mad[y] * scale, "A") for y in years]
            + [(date(y, 7, 1), bea_a[y], "A") for y in sorted(bea_a)]
            + [(d, v, "Q") for d, v in bea])


def annual(lv: list[tuple[date, float, str]]) -> tuple[list[tuple[date, float, str]], str | None]:
    """The same levels, annual throughout: BEA quarters averaged by year. A part year at
    the end is the previous year's level grown by the year-to-date change on the same
    quarters a year earlier. Returns (levels, part-year label or None)."""
    out = [x for x in lv if x[2] == "A" and x[0].year < 1947]
    by: dict[int, list[float]] = {}
    for d, v, f in lv:
        if f == "Q":
            by.setdefault(d.year, []).append(v)
    part = None
    for y in sorted(by):
        q = by[y]
        if len(q) == 4:
            out.append((date(y, 7, 1), sum(q) / 4, "A"))
        else:   # year to date: grow last year's level by the change on the same quarters
            k, prev = len(q), by[y - 1]
            out.append((date(y, 7, 1), sum(prev) / 4 * (sum(q) / sum(prev[:k])), "A"))
            part = f"{y} is Q1 to Q{k} on the same quarters of {y - 1}."
    return out, part


def growth(lv: list[tuple[date, float, str]], vs_peak: bool) -> list[tuple[date, float]]:
    """Growth on a year earlier (4 quarters, or 1 year on the annual data); with
    vs_peak, on the higher of that and the highest level reached up to then."""
    high, running = [], float("-inf")   # high[i]: highest level up to and including i
    for _, v, _ in lv:
        running = max(running, v)
        high.append(running)
    out = []
    for i, (d, v, f) in enumerate(lv):
        lag = 4 if f == "Q" else 1
        if i - lag < 0 or lv[i - lag][2] != f:
            continue   # 1947: no quarterly year-earlier level yet
        base = max(lv[i - lag][1], high[i - lag]) if vs_peak else lv[i - lag][1]
        out.append((d, 100 * (v / base - 1)))
    return out


def bouncebacks(lv: list[tuple[date, float, str]]) -> list[tuple[date, date]]:
    """(start, end) of each recovery: NBER trough until the level is back above its
    previous all-time high (the highest level before the NBER peak)."""
    spans = []
    for c in json.loads(get_text(NBER)):
        if not c["peak"] or not c["trough"]:
            continue
        p, t = date.fromisoformat(c["peak"]), date.fromisoformat(c["trough"])
        before = [v for d, v, _ in lv if d <= p]
        if not before:
            continue
        high = max(before)
        after = [d for d, v, _ in lv if d > t and v >= high]
        dips = [v for d, v, _ in lv if p < d <= t or (d > t and (not after or d < after[0]))]
        if after and dips and min(dips) < high:
            spans.append((t, after[0]))
    return spans


BAR_SOURCE = ("Source: Maddison Project Database 2023 to 1928, rescaled to join BEA; BEA via FRED, real GDP (GDPCA) "
              "over population (B230RC0A052NBEA) 1929-46, real GDP per capita (A939RX0Q048SBEA) from 1947, quarters "
              "averaged by year; NBER business-cycle dates; ukmacro calculations.")


def draw(series: list[tuple[date, float]], spans, slug: str, title: str, units: str, note: str,
         bars: bool = False, start: int = 1800, source: str = SOURCE) -> None:
    """A growth chart from `start`: a line, or bars one year wide (annual points, at
    mid-year) or one quarter wide (quarterly points); recession bouncebacks hatched."""
    hs.apply()
    series = [(d, g) for d, g in series if d.year >= start]
    fig, ax = hs.figure(title, units, source=source + " " + note)
    c = hs.COLOURS
    for s, e in spans:
        if e.year >= start:
            ax.axvspan(max(s, date(start, 1, 1)), e, facecolor="none", edgecolor=c["grey"], hatch="////",
                       linewidth=0, zorder=1)
    ax.axhline(LINE, color=c["ink"], linewidth=1.2, zorder=3)
    ax.annotate(f"{LINE:.0f}%", (date(start, 1, 1), LINE), xytext=(2, 4), textcoords="offset points",
                fontsize=10.5, color=c["ink"], va="bottom")
    if bars:
        # annual points sit at 1 July, quarterly at the 15th of the quarter's middle month
        widths = [300 if d.month == 7 and d.day == 1 else 75 for d, _ in series]
        ax.bar([d for d, _ in series], [g for _, g in series], width=widths, color=c["series"][0],
               linewidth=0, zorder=4)
    else:
        ax.plot([d for d, _ in series], [g for _, g in series], color=c["series"][0], linewidth=1.4, zorder=4)
        last = series[-1]
        ax.annotate(f"{last[1]:.1f}".replace("-", "\u2212"), last, xytext=(5, 0), textcoords="offset points",
                    va="center", fontsize=10.5, color=c["text_2"])
    ax.axhline(0, color=c["grey"], linewidth=0.9, zorder=5)
    step = 20 if start < 1900 else 10
    ax.set_xlim(date(start, 1, 1), date(series[-1][0].year + (4 if step == 20 else 2), 1, 1))
    first = -(-start // step) * step   # first round decade
    ax.set_xticks([date(y, 1, 1) for y in range(first, series[-1][0].year + 1, step)])
    ax.xaxis.set_major_formatter(__import__("matplotlib.dates", fromlist=["DateFormatter"]).DateFormatter("%Y"))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}".replace("-", "\u2212"))
    fig.legend([Patch(facecolor="none", edgecolor=c["grey"], hatch="////", linewidth=0)],
               ["Recession bounceback: NBER trough until back above the previous all-time high"],
               loc="upper left", bbox_to_anchor=(hs._x(hs.LEFT_CM - 0.2), 0.86), handlelength=1.6)
    IMG.mkdir(parents=True, exist_ok=True)
    hs.save_png(fig, IMG / f"{slug}.png")


def main() -> None:
    lv = levels()
    yoy, vs_peak, spans = growth(lv, False), growth(lv, True), bouncebacks(lv)
    draw(yoy, spans, "us-gdp-per-capita-growth", "US real GDP per capita growth since 1800",
         "% change on a year earlier",
         "Annual growth to 1947, then growth on the same quarter a year earlier.")
    draw(vs_peak, spans, "us-gdp-per-capita-growth-vs-peak",
         "US real GDP per capita growth, measured against the previous peak",
         "% change on the higher of a year earlier and the previous all-time high",
         "Growth is measured from the year-earlier level or, if higher, the highest level reached up to "
         "then, so a rebound that only regains lost ground counts as negative growth.")
    # bar versions: annual throughout
    alv, part = annual(lv)
    ay, ap, aspans = growth(alv, False), growth(alv, True), bouncebacks(alv)
    tail = f" {part}" if part else ""
    draw(ay, aspans, "us-gdp-per-capita-growth-bars", "US real GDP per capita growth since 1800",
         "% change on the previous year", "Annual averages throughout." + tail, bars=True, source=BAR_SOURCE)
    draw(ap, aspans, "us-gdp-per-capita-growth-vs-peak-bars",
         "US real GDP per capita growth, measured against the previous peak",
         "% change on the higher of the previous year and the previous all-time high",
         "Annual averages throughout. A rebound that only regains lost ground counts as negative growth." + tail,
         bars=True, source=BAR_SOURCE)
    # the last 100 years as bars: annual to 1947 (no quarterly per-capita data before), then quarterly
    start = date.today().year - 100
    q_note = "Wide bars: annual growth to 1947. Narrow bars: growth on the same quarter a year earlier, from 1948."
    draw(yoy, spans, "us-gdp-per-capita-growth-100y-bars", f"US real GDP per capita growth since {start}",
         "% change on a year earlier", q_note, bars=True, start=start)
    draw(vs_peak, spans, "us-gdp-per-capita-growth-vs-peak-100y-bars",
         f"US real GDP per capita growth since {start}, measured against the previous peak",
         "% change on the higher of a year earlier and the previous all-time high",
         q_note + " A rebound that only regains lost ground counts as negative growth.", bars=True, start=start)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "us_gdp_per_capita_growth_annual.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "gdp_per_capita_2017_usd", "growth_pct", "growth_vs_peak_pct"])
        g1, g2 = dict(ay), dict(ap)
        for d, v, _ in alv:
            w.writerow([d.year, round(v, 1), round(g1[d], 2) if d in g1 else "", round(g2[d], 2) if d in g2 else ""])
    with (OUT / "us_gdp_per_capita_growth.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "frequency", "gdp_per_capita_2017_usd", "growth_yoy_pct", "growth_vs_peak_pct"])
        g1, g2 = dict(yoy), dict(vs_peak)
        for d, v, fr in lv:
            w.writerow([d.isoformat(), fr, round(v, 1), round(g1[d], 2) if d in g1 else "",
                        round(g2[d], 2) if d in g2 else ""])
    print(f"[us-gdp] {len(yoy)} growth points, {len(spans)} bounceback spans; latest {yoy[-1]}")
    above = [d.year for d, g in yoy if g >= LINE]
    print(f"[us-gdp] at or above {LINE}%: {sorted(set(above))}")


if __name__ == "__main__":
    main()
