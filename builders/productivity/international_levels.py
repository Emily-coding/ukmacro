#!/usr/bin/env python3
"""Productivity levels: the UK compared with the US, Germany, France and Italy.

  international-productivity-levels          GDP per hour worked as % of the US level
  international-productivity-levels-germany  the same, as % of the German level
  international-productivity-levels-germany-constant
                                             the Germany chart at constant prices and 2020
                                             PPPs (each country's 2020 level moved with its
                                             real growth)
  uk-germany-productivity-ppp-hours          UK as % of Germany at current or constant PPPs,
                                             on new or old ONS hours: how much each choice
                                             moves the gap
  uk-hours-old-vs-new                        UK total hours worked to 2024: the ONS's new
                                             estimate, its old one, and the OECD's

GDP per hour worked is measured in each year at that year's prices and purchasing power
parities (PPPs).

Source: OECD Productivity Database (GDP per hour worked, current prices, current PPPs, in US
dollars) for every country, except that the UK's hours come from the latest ONS labour
productivity release.

Why swap the UK's hours: from November 2026 the ONS measures hours with a new "component
approach". The new hours are close to the old ones until 2009 but grow much more slowly
after it: by 2025 they are about 8% below the old estimate (51.9bn hours a year against
56.6bn), so UK productivity is correspondingly higher. For the UK we take the OECD's GDP in
PPP dollars (which is ONS GDP converted at the OECD's PPP) and divide it by the ONS's hours.
The level charts show the UK on the new hours (solid) and on the old ones (dashed).

The OECD's own UK hours are a third, separate estimate (well below both ONS series before
2020), so the OECD's published UK productivity level is not the same as the UK on either ONS
basis. It is kept in the CSVs as "UK, OECD hours" and drawn on the hours chart.

The old ONS hours come from the August 2026 release, the last on the old method. The ONS
doesn't link earlier versions of the workbook, so they are frozen in
data/productivity/uk_hours_ons_aug2026.csv (hours = current-price GVA / current-price output
per hour, from that release's Tables 2 and 6).

Current PPPs, not constant ones: a PPP converts each country's GDP into dollars of the same
buying power, so comparing levels needs the PPP for that same year. (Carrying one year's PPP
backwards with volume growth gives a smoother line but leans on the PPP of a single year.)

How far back: the US chart starts in 1987, the first year the OECD database has US hours;
Germany's line, and so the whole Germany chart, starts in 1991, after unification. The ONS's
new UK hours start in 1997, so for 1987-1996 the UK's new hours are the ONS's 1997 figure
taken back in line with the old ONS hours (the old series' growth, on the new series' level).
The latest year is the latest the OECD has for every country; the ONS has UK hours for more
recent quarters.

Run:  .venv/bin/python builders/productivity/international_levels.py
"""

from __future__ import annotations

import csv
import io
import math
import re
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "chart-house-style"))

import house_style as hs  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from ukmacro import oecd  # noqa: E402
from ukmacro.http import get, get_text  # noqa: E402

ONS = "https://www.ons.gov.uk"
ONS_HOURS_PAGE = ONS + "/economy/economicoutputandproductivity/productivitymeasures/datasets/outputperhourworkeduk"
PDB = "OECD.SDD.TPS,DSD_PDB@DF_PDB,"   # OECD Productivity Database
# OECD codes and chart names
COUNTRIES = {"GBR": "UK", "USA": "US", "DEU": "Germany", "FRA": "France", "ITA": "Italy"}
UK_OLD = "UK, old ONS hours"   # the UK on the ONS's pre-November 2026 hours
UK_OECD = "UK, OECD hours"     # the OECD's own published UK figure (its own hours estimate)
OLD_HOURS = REPO / "data" / "productivity" / "uk_hours_ons_aug2026.csv"
# one colour per country, the same on both charts (the base country is drawn as the 100 line)
COLOUR = {"UK": hs.COLOURS["series"][0], "Germany": hs.COLOURS["series"][1],
          "France": hs.COLOURS["series"][2], "Italy": hs.COLOURS["series"][3],
          "US": hs.COLOURS["ink"]}
START = 1987   # first year of US hours in the OECD database
HOURS_LAST = 2024   # the hours chart stops here
CONSTANT_PPP_YEAR = 2020   # the OECD's base year for its constant-PPP series

OUT, IMG = REPO / "data" / "productivity", REPO / "img" / "productivity"


def oecd_series(prices: str = "V") -> tuple[dict[str, dict[int, float]], dict[int, float], dict[int, float]]:
    """GDP per hour worked (US$ at PPPs) for each country, UK GDP (US$ million at PPPs) and UK
    total hours on the OECD's basis, as {country: {year: value}}, {year: value} and {year: value}.
    prices: "V" = current prices and current PPPs; "LR" = constant prices at 2020 PPPs."""
    areas = "+".join(COUNTRIES)
    # key slots: country.frequency.measure.industry.unit.prices.transformation.asset.conversion
    per_hour = oecd.fetch(PDB, f"{areas}.A.GDPHRS._T.USD_PPP_H.{prices}.N..PPP", str(START))
    gdp = oecd.fetch(PDB, f"GBR.A.GDP._T.USD_PPP.{prices}.N..PPP", str(START))["GBR"]
    uk_hours = oecd.fetch(PDB, "GBR.A.HRSTO._T.H._Z.N..", str(START))["GBR"]
    years = lambda obs: {int(y): v for y, v in obs}  # noqa: E731
    return {c: years(obs) for c, obs in per_hour.items()}, years(gdp), years(uk_hours)


def ons_hours() -> tuple[dict[int, float], str]:
    """UK total hours worked per year implied by the ONS 'Output per hour' dataset, and the
    dataset's publication date.

    Hours = current-price GVA (Table 2, £ million) / current-price output per hour (Table 6,
    £). This gives exactly the annual hours behind the ONS's own productivity figure. (Table 4's
    average weekly hours x 52.18 weeks comes out about 0.35% higher, so the ONS evidently
    annualises slightly differently.)"""
    link = re.search(r'/file\?uri=[^"]+\.xlsx', get_text(ONS_HOURS_PAGE)).group(0)
    wb = openpyxl.load_workbook(io.BytesIO(get(ONS + link, timeout=180)), read_only=True)

    def table(sheet: str, expect: str) -> dict[int, float]:
        title = str(wb[sheet]["A1"].value)
        if expect not in title:   # the ONS reshuffled these tables in Nov 2026
            raise ValueError(f"ONS Output per hour {sheet} is no longer {expect!r}: {title!r}")
        return {int(r[0]): float(r[1]) for r in wb[sheet].iter_rows(values_only=True)
                if r and isinstance(r[0], int) and isinstance(r[1], (int, float))}

    gva = table("Table_2", "Annual Gross value added")
    per_hour = table("Table_6", "Annual Output per hour worked")
    hours = {y: gva[y] * 1e6 / per_hour[y] for y in gva if y in per_hour}
    cover = [r[0] for r in wb["Cover_sheet"].iter_rows(values_only=True) if r and r[0]]
    published = cover[cover.index("Publication date") + 1]
    return hours, re.sub(r"(\d)(st|nd|rd|th)", r"\1", str(published))


def old_ons_hours() -> dict[int, float]:
    """UK total hours per year on the ONS's old method (August 2026 release), frozen in the repo."""
    with open(OLD_HOURS) as f:
        return {int(r["year"]): float(r["hours"]) for r in csv.DictReader(f)}


def build(prices: str = "V") -> tuple[list[dict], list[dict], str]:
    """Two tables, one row per year (prices as in oecd_series).
    levels: each country's GDP per hour in US$ at PPPs (blank before its data start),
            with the UK on the ONS's new hours, its old hours, and as the OECD publishes it.
    hours:  UK total hours on the three bases."""
    per_hour, uk_gdp, oecd_uk_hours = oecd_series(prices)
    hours, published = ons_hours()
    old = old_ons_hours()
    first_ons = min(hours)
    new = dict(hours)   # as published, for the hours chart
    # before the new series starts, take its first year back in line with the old ONS hours
    for y in range(START, first_ons):
        hours[y] = hours[first_ons] * old[y] / old[first_ons]
    last = min(min(max(s) for s in per_hour.values()), max(uk_gdp), max(hours), max(old))
    levels = []
    for y in range(START, last + 1):
        row = {"year": y, "UK": round(uk_gdp[y] * 1e6 / hours[y], 2)}   # GDP / new ONS hours
        for code, name in list(COUNTRIES.items())[1:]:
            row[name] = round(per_hour[code][y], 2) if y in per_hour[code] else None
        row[UK_OLD] = round(uk_gdp[y] * 1e6 / old[y], 2)                # GDP / old ONS hours
        row[UK_OECD] = round(per_hour["GBR"][y], 2)
        row["uk_new_hours_basis"] = "ONS" if y >= first_ons else "ONS 1997 level with old ONS growth"
        levels.append(row)
    hours_rows = [{"year": y,
                   "ons_new_bn": round(new[y] / 1e9, 2) if y in new else None,
                   "ons_old_bn": round(old[y] / 1e9, 2),
                   "oecd_bn": round(oecd_uk_hours[y] / 1e3, 2) if y in oecd_uk_hours else None}
                  for y in range(first_ons, last + 1)]   # OECD hours are in millions
    return levels, hours_rows, published


def relative(rows: list[dict], base: str) -> list[dict]:
    """Each series as % of `base` in the same year, from the first year `base` has data."""
    names = [*COUNTRIES.values(), UK_OLD, UK_OECD]
    return [{"year": r["year"], **{n: None if r[n] is None else round(100 * r[n] / r[base], 1)
                                   for n in names}}
            for r in rows if r[base] is not None]


def _write(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def chart(rows: list[dict], base: str, published: str, slug: str, prices: str = "V") -> None:
    years = [r["year"] for r in rows]
    last = rows[-1]
    basis = ("at current prices and PPPs" if prices == "V"
             else f"at constant prices and {CONSTANT_PPP_YEAR} PPPs")
    fig, ax = hs.figure(f"Productivity levels relative to {'the US' if base == 'US' else base}, "
                        f"{years[0]}–{years[-1]}"
                        + ("" if prices == "V" else f", {CONSTANT_PPP_YEAR} PPPs"),
                        f"GDP per hour worked, {basis} ({base} = 100)",
                        source=(f"Source: OECD Productivity Database (GDP per hour worked, "
                                f"{'current PPPs' if prices == 'V' else f'constant prices, {CONSTANT_PPP_YEAR} PPPs'}); "
                                f"UK hours from ONS Output per hour, UK ({published}), which now uses the "
                                "component approach (before 1997: ONS 1997 hours moved back in line with the old "
                                "series). Old ONS hours: from the August 2026 release, the last on the old method. "
                                "ukmacro calculations."))
    # leave room on the right for the end-of-line labels
    pos = ax.get_position()
    ax.set_position([pos.x0, pos.y0, pos.width - hs._x(3.9), pos.height])
    ax.axhline(100, color=COLOUR[base], linewidth=1.2)

    # end labels: [y value, text, colour, line style of the key drawn before it (or None)]
    ends = [[100, f"{base} 100", COLOUR[base], None]]
    for name in COUNTRIES.values():
        if name in (base, "UK"):
            continue
        ax.plot(years, [math.nan if r[name] is None else r[name] for r in rows],
                color=COLOUR[name], linewidth=2)
        ends.append([last[name], f"{name} {last[name]:.0f}", COLOUR[name], None])
    blue = COLOUR["UK"]
    dashed = (0, (3, 2))
    ax.plot(years, [r[UK_OLD] for r in rows], color=blue, linewidth=1.3, linestyle=dashed, alpha=0.75)
    ax.plot(years, [r["UK"] for r in rows], color=blue, linewidth=2.4)
    # the two UK lines are labelled with a short sample of their line style
    ends.append([last[UK_OLD], f"UK, old ONS hours {last[UK_OLD]:.0f}", blue, dashed])
    ends.append([last["UK"], f"UK, new ONS hours {last['UK']:.0f}", blue, "-"])

    values = [r[k] for r in rows for k in [*COUNTRIES.values(), UK_OLD] if r[k] is not None]
    lo, hi = min(values + [100]), max(values + [100])
    ax.set_ylim(5 * (lo // 5) - 2, 5 * (hi // 5 + 1) + 2)
    ax.set_xlim(years[0], years[-1])
    ax.set_xticks([y for y in years if y % 2 == 1])   # every other year

    _end_labels(fig, ax, ends, years[-1])
    hs.save_png(fig, IMG / f"{slug}.png")


def _end_labels(fig, ax, ends: list[list], x) -> None:
    """Write end-of-line labels at x. `ends` holds [y, text, colour, line style or None]; a
    line style draws a short sample of the line before the text, to tell similar lines apart."""
    # nudge labels apart (at least 4.5% of the axis height between neighbours)
    gap = 0.045 * (ax.get_ylim()[1] - ax.get_ylim()[0])
    ends.sort(key=lambda e: e[0])
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + gap)
    # if pushing up broke the order with the line just above, push down from the top instead
    for i in range(len(ends) - 2, -1, -1):
        ends[i][0] = min(ends[i][0], ends[i + 1][0] - gap)
    for y, label, colour, style in ends:
        offset = 6
        if style is not None:   # a short line sample, then the label
            ax.add_line(Line2D([1.008, 1.04], [y, y], transform=ax.get_yaxis_transform(),
                               color=colour, linewidth=2.4 if style == "-" else 1.3,
                               linestyle=style, clip_on=False))
            offset = 6 + 0.04 * ax.get_position().width * fig.get_figwidth() * 72 - 2
        ax.annotate(label, (x, y), xytext=(offset, 0), textcoords="offset points",
                    va="center", fontsize=10.5, color=colour, annotation_clip=False)


def hours_chart(rows: list[dict], published: str) -> None:
    """UK total hours worked a year, to HOURS_LAST: the ONS's old and new estimates, and the
    OECD's (the one behind its international comparisons)."""
    rows = [r for r in rows if r["year"] <= HOURS_LAST]
    years = [r["year"] for r in rows]
    fig, ax = hs.figure(f"UK hours worked: old and new ONS estimates and the OECD's, {years[0]}–{years[-1]}",
                        "Total hours worked in the year, billions",
                        source=(f"Source: ONS Output per hour, UK, {published} (new: component approach) and "
                                "18 August 2026 (old: direct approach, from the Labour Force Survey). "
                                "Hours are current-price GVA divided by current-price output per hour. OECD: Productivity Database "
                                "total hours. ukmacro calculations."))
    pos = ax.get_position()
    ax.set_position([pos.x0, pos.y0, pos.width - hs._x(2.4), pos.height])
    series = [("ons_new_bn", "New ONS", COLOUR["UK"]), ("ons_old_bn", "Old ONS", hs.COLOURS["series"][1]),
              ("oecd_bn", "OECD", hs.COLOURS["grey"])]
    ends = []
    for key, name, colour in series:
        ax.plot(years, [r[key] for r in rows], color=colour, linewidth=2)
        v = rows[-1][key]
        # grey context line: label in the secondary text colour so it stays legible
        ends.append([v, f"{name} {v:.1f}", hs.COLOURS["text_2"] if colour == hs.COLOURS["grey"] else colour, None])
    values = [r[k] for r in rows for k, _, _ in series]
    ax.set_ylim(2 * (min(values) // 2) - 1, 2 * (max(values) // 2 + 1))   # room below the lowest line
    ax.set_xlim(years[0], years[-1])
    ax.set_xticks([y for y in years if (years[-1] - y) % 3 == 0])   # every third year, ending on the last
    _end_labels(fig, ax, ends, years[-1])
    hs.save_png(fig, IMG / "uk-hours-old-vs-new.png")


def ppp_hours_rows(rows_cur: list[dict], rows_const: list[dict]) -> list[dict]:
    """UK GDP per hour as % of Germany's on four bases: current or constant (2020) PPPs, and
    the ONS's new or old hours. Shows how much each choice moves the gap."""
    const = {r["year"]: r for r in rows_const}
    gap = lambda r, k: round(100 * r[k] / r["Germany"], 1)   # noqa: E731  (UK as % of Germany)
    return [{"year": r["year"],
             "current_ppp_new_hours": gap(r, "UK"), "current_ppp_old_hours": gap(r, UK_OLD),
             "constant_ppp_new_hours": gap(const[r["year"]], "UK"),
             "constant_ppp_old_hours": gap(const[r["year"]], UK_OLD)}
            for r in rows_cur if r["Germany"] is not None]


def ppp_hours_chart(rows: list[dict], published: str) -> None:
    years = [r["year"] for r in rows]
    last = rows[-1]
    fig, ax = hs.figure(f"UK productivity relative to Germany: PPPs and hours, {years[0]}–{years[-1]}",
                        f"UK GDP per hour worked as % of Germany's, at current or constant ({CONSTANT_PPP_YEAR}) PPPs",
                        source=("Source: OECD Productivity Database (GDP and GDP per hour worked, current PPPs and "
                                f"constant prices at {CONSTANT_PPP_YEAR} PPPs); UK hours from ONS Output per hour, UK: "
                                f"new ({published}, component approach) and old (18 August 2026). Before 1997, new "
                                "hours follow the old series' growth. ukmacro calculations."))
    pos = ax.get_position()
    ax.set_position([pos.x0, pos.y0, pos.width - hs._x(4.6), pos.height])
    ax.axhline(100, color=hs.COLOURS["ink"], linewidth=1.2)

    # colour = PPP basis, line style = hours basis (solid new, dashed old)
    blue, amber = hs.COLOURS["series"][:2]
    dashed = (0, (3, 2))
    series = [("constant_ppp_old_hours", "Constant PPPs, old hours", amber, dashed),
              ("current_ppp_old_hours", "Current PPPs, old hours", blue, dashed),
              ("constant_ppp_new_hours", "Constant PPPs, new hours", amber, "-"),
              ("current_ppp_new_hours", "Current PPPs, new hours", blue, "-")]
    ends = [[100, "Germany 100", hs.COLOURS["ink"], None]]
    for key, name, colour, style in series:
        ax.plot(years, [r[key] for r in rows], color=colour,
                linewidth=2.4 if style == "-" else 1.6, linestyle=style)
        ends.append([last[key], f"{name} {last[key]:.0f}", colour, style])

    values = [r[k] for r in rows for k, _, _, _ in series]
    ax.set_ylim(5 * (min(values) // 5) - 2, 5 * (max(values + [100]) // 5 + 1) + 2)
    ax.set_xlim(years[0], years[-1])
    ax.set_xticks([y for y in years if (years[-1] - y) % 3 == 0])   # every third year, ending on the last
    _end_labels(fig, ax, ends, years[-1])
    hs.save_png(fig, IMG / "uk-germany-productivity-ppp-hours.png")


def main() -> None:
    rows, hours_rows, published = build()
    OUT.mkdir(parents=True, exist_ok=True)
    _write(rows, OUT / "international_productivity_levels_usd_ppp.csv")
    _write(hours_rows, OUT / "uk_hours_old_vs_new.csv")
    hours_chart(hours_rows, published)
    for base, slug in (("US", "international-productivity-levels"),
                       ("Germany", "international-productivity-levels-germany")):
        rel = relative(rows, base)
        _write(rel, OUT / f"{slug.replace('-', '_')}.csv")
        chart(rel, base, published, slug)
        print(base, rel[-1])

    # constant-PPP version of the Germany chart: each country's 2020 level, carried backwards
    # and forwards with its own real growth, so year-to-year moves reflect real productivity
    # growth only (not changes in relative prices)
    rows_k, _, _ = build("LR")
    _write(rows_k, OUT / "international_productivity_levels_usd_ppp_constant.csv")
    rel = relative(rows_k, "Germany")
    slug = "international-productivity-levels-germany-constant"
    _write(rel, OUT / f"{slug.replace('-', '_')}.csv")
    chart(rel, "Germany", published, slug, prices="LR")
    print("Germany, constant PPPs", rel[-1])

    # how much do the PPP and hours choices move the UK-Germany gap?
    ph = ppp_hours_rows(rows, rows_k)
    _write(ph, OUT / "uk_germany_productivity_ppp_hours.csv")
    ppp_hours_chart(ph, published)
    print("PPPs x hours", ph[-1])


if __name__ == "__main__":
    hs.apply()
    main()
