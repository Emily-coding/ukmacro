#!/usr/bin/env python3
"""US real GDP per capita growth since 1800, with recession bouncebacks hatched.

Two charts:
  us-gdp-per-capita-growth            growth on a year earlier
  us-gdp-per-capita-growth-vs-peak    growth on the higher of a year earlier and the
                                      previous all-time peak, so rebounds that only
                                      regain lost ground don't count as growth

Data:
  1801-1947  Maddison Project Database 2023, annual GDP per capita (2011 dollars)
  1947-      BEA real GDP per capita (FRED A939RX0Q048SBEA), quarterly, chained
             2017 dollars, seasonally adjusted; growth on the same quarter a year
             earlier from 1948 Q1
The Maddison series is rescaled to match BEA's 1947 average, so the two join into one
level series and the all-time peak runs across both (the Second World War peak
matters for the late 1940s).

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

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=A939RX0Q048SBEA"
MADDISON = "https://dataverse.nl/api/access/datafile/421302"   # Maddison Project Database 2023
NBER = "https://data.nber.org/data/cycles/business_cycle_dates.json"
OUT, IMG = REPO / "data" / "us", REPO / "img" / "us"
LINE = 15.0   # reference growth rate, %
SOURCE = ("Source: BEA via FRED (A939RX0Q048SBEA), quarterly from 1947; Maddison Project Database 2023, "
          "annual before 1947, rescaled to join BEA in 1947; NBER business-cycle dates; ukmacro calculations.")


def levels() -> list[tuple[date, float, str]]:
    """[(date, GDP per capita, "A" or "Q")], annual to 1947 then quarterly, on BEA's scale.
    Annual values sit at mid-year, quarterly at mid-quarter."""
    wb = openpyxl.load_workbook(io.BytesIO(get(MADDISON, timeout=180)), read_only=True)
    rows = wb["Full data"].iter_rows(values_only=True)
    next(rows)
    mad = {r[3]: r[4] for r in rows if r[0] == "USA" and r[4] is not None and r[3] >= 1800}
    bea = []
    for r in list(csv.reader(io.StringIO(get_text(FRED))))[1:]:
        if r[1] not in ("", "."):
            d = date.fromisoformat(r[0])
            bea.append((date(d.year, d.month + 1, 15), float(r[1])))
    scale = sum(v for d, v in bea if d.year == 1947) / 4 / mad[1947]
    years = [y for y in sorted(mad) if y <= 1947 and all(z in mad for z in range(y, 1948))]  # unbroken run
    return [(date(y, 7, 1), mad[y] * scale, "A") for y in years] + [(d, v, "Q") for d, v in bea]


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


def draw(series: list[tuple[date, float]], spans, slug: str, title: str, units: str, note: str) -> None:
    hs.apply()
    fig, ax = hs.figure(title, units, source=SOURCE + " " + note)
    c = hs.COLOURS
    for s, e in spans:
        ax.axvspan(s, e, facecolor="none", edgecolor=c["grey"], hatch="////", linewidth=0, zorder=1)
    ax.axhline(0, color=c["grey"], linewidth=0.9, zorder=2)
    ax.axhline(LINE, color=c["ink"], linewidth=1.2, zorder=3)
    ax.annotate(f"{LINE:.0f}%", (series[0][0], LINE), xytext=(2, 4), textcoords="offset points",
                fontsize=10.5, color=c["ink"], va="bottom")
    ax.plot([d for d, _ in series], [g for _, g in series], color=c["series"][0], linewidth=1.4, zorder=4)
    last = series[-1]
    ax.annotate(f"{last[1]:.1f}".replace("-", "−"), last, xytext=(5, 0), textcoords="offset points",
                va="center", fontsize=10.5, color=c["text_2"])
    ax.set_xlim(date(1800, 1, 1), date(series[-1][0].year + 4, 1, 1))
    ax.set_xticks([date(y, 1, 1) for y in range(1800, series[-1][0].year + 1, 20)])
    ax.xaxis.set_major_formatter(__import__("matplotlib.dates", fromlist=["DateFormatter"]).DateFormatter("%Y"))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}".replace("-", "−"))
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
    OUT.mkdir(parents=True, exist_ok=True)
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
