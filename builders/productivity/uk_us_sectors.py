#!/usr/bin/env python3
"""Productivity by sector, UK and US: Resolution Foundation's "Yanked away" (April 2025)
figures 6 and 10, rebuilt on the latest data.

  uk-productivity-by-sector        figure 6: change in real GVA per hour by sector, UK,
                                   2019 to the latest four quarters; bar widths are each
                                   sector's share of 2019 GVA, so a bar's area is roughly
                                   its contribution to aggregate productivity growth
  uk-us-productivity-contributions figure 10: average annual within-industry contribution
                                   to GVA-per-hour growth from 2019 (growth in 2020 onwards),
                                   by sector, UK vs US

UK hours follow RF's method (their Annex 1), which avoids leaning on the Labour Force
Survey for the level of employment:
  jobs   payrolled employees by section (HMRC PAYE RTI, seasonally adjusted, quarterly
         averages) + self-employment jobs by section (ONS Workforce Jobs, JOBS02)
  hours  jobs x average hours per job (ONS hours / ONS jobs by section, from the
         productivity release)
RF also rescaled RTI to their aggregate employee estimate (+0.1% on average) and
self-employment to HMRC self-assessment counts; neither is done here. UK GVA (chained
volume and current price, by section, real estate excluding imputed rent) comes from
the ONS productivity release. The ONS's own output per hour is written to the CSV for
comparison.

US: BEA value added by industry (real chain-type quantity indexes and current prices)
and BLS Employment Projections total hours of all persons by industry, aggregated to
RF's 14 comparable sectors (their Table 1: waste management goes to utilities,
management of companies to finance, rental and leasing and lessors of intangible
assets to admin and support). Merged sectors' real growth is the previous-year current
price weighted average of their parts.

Contribution of sector i in year t = its share of nominal GVA in t-1 x growth in its
GVA per hour in t. Shares are of whole-economy GVA excluding imputed rent (UK) and GDP
excluding housing (US). Education, health, public administration and real estate are
left out of the comparison, as in RF.

bls.gov turns away scripted downloads, so the BLS file is read from
~/.cache/ukmacro/bls/industry.zip: download it from the BLS page "Industry output and
employment" (published each August/September) and save it there.

Run:  .venv/bin/python builders/productivity/uk_us_sectors.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from pathlib import Path

import openpyxl
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "chart-house-style"))

import house_style as hs  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from ukmacro.http import get, get_text  # noqa: E402

ONS = "https://www.ons.gov.uk"
PROD = ONS + "/economy/economicoutputandproductivity/productivitymeasures/datasets/{}"
RTI_PAGE = (ONS + "/employmentandlabourmarket/peopleinwork/earningsandworkinghours/datasets/"
            "realtimeinformationstatisticsreferencetableseasonallyadjusted")
JOBS02_PAGE = (ONS + "/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/datasets/"
               "workforcejobsbyindustryjobs02")
BEA_VA = "https://apps.bea.gov/industry/Release/XLS/GDPxInd/ValueAdded.xlsx"
BLS_EP = "https://www.bls.gov/emp/industry-employment/industry.zip"
BLS_ZIP = Path.home() / ".cache" / "ukmacro" / "bls" / "industry.zip"   # saved by hand: see us_data()
OUT, IMG = REPO / "data" / "productivity", REPO / "img" / "productivity"
BASE_YEAR, START = 2019, 2020   # figure 6 base year; figure 10's first growth year

# UK sections as the ONS productivity tables label them: (short name, figure 6 group)
SECTIONS = {
    "A": ("Agriculture", "Non-service sectors"), "B": ("Mining & quarrying", "Non-service sectors"),
    "C": ("Manufacturing", "Non-service sectors"), "D": ("Electricity & gas", "Non-service sectors"),
    "E": ("Water & waste", "Non-service sectors"), "F": ("Construction", "Non-service sectors"),
    "G": ("Wholesale & retail", "Other services"), "H": ("Transport", "Other services"),
    "I": ("Hospitality", "Other services"), "J": ("Info & comms", "Professional services"),
    "K": ("Finance & insurance", "Professional services"), "L": ("Real estate", "Professional services"),
    "M": ("PSTA", "Professional services"), "N": ("Admin & support", "Professional services"),
    "O": ("Public admin", "Public services"), "P": ("Education", "Public services"),
    "Q": ("Health", "Public services"), "R": ("Arts & recreation", "Other services"),
    "S and T": ("Other services", "Other services"),
}
GROUPS = ["Non-service sectors", "Public services", "Professional services", "Other services"]
# figure 10 sectors: UK sections, BEA value-added line numbers, BLS EP sector numbers
COMPARE = {
    "Agriculture": (["A"], [3], range(1, 7)),
    "Mining & quarrying": (["B"], [6], range(7, 12)),
    "Manufacturing": (["C"], [12], range(16, 80)),
    "Utilities": (["D", "E"], [10, 73], [*range(12, 15), 129]),
    "Construction": (["F"], [11], [15]),
    "Wholesale & retail": (["G"], [34, 35], range(80, 85)),
    "Transport": (["H"], [40], range(85, 94)),
    "Hospitality": (["I"], [85], range(154, 157)),
    "Info & comms": (["J"], [49], range(94, 100)),
    "Finance & insurance": (["K"], [55, 70], [*range(100, 105), 120]),
    "PSTA": (["M"], [66], range(109, 120)),
    "Admin. & support": (["N"], [72, 64], [*range(121, 129), *range(106, 109)]),
    "Arts & recreation": (["R"], [82], range(146, 154)),
    "Other services": (["S and T"], [88], range(157, 169)),
}
BEA_TOTAL, BEA_HOUSING = 1, 62

SOURCE_UK = ("Source: ONS Output per hour and Output per job (productivity flash estimate); HMRC PAYE RTI; "
             "ONS Workforce Jobs (JOBS02); ukmacro calculations following Resolution Foundation, "
             "Yanked away (2025), Annex 1.")
SOURCE_US = ("Source: ONS productivity release, HMRC PAYE RTI and Workforce Jobs (UK hours as RF's Annex 1); "
             "BEA value added by industry; BLS Employment Projections industry hours; ukmacro calculations "
             "following Resolution Foundation, Yanked away (2025).")


# ---- UK -------------------------------------------------------------------------------

def _workbook(page: str, ext: str = "xlsx") -> bytes:
    link = re.search(rf'/file\?uri=[^"]+\.{ext}', get_text(page)).group(0)
    return get(ONS + link, timeout=180)


def _ons_table(wb, sheet: str) -> dict[str, dict[str, float]]:
    """A productivity-release table as {section: {'YYYY Qn' or 'YYYY': value}}."""
    rows = list(wb[sheet].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "SIC 2007 section")
    cols = {j: str(c).strip() for j, c in enumerate(rows[hi]) if j and c}
    out: dict[str, dict[str, float]] = {c: {} for c in cols.values()}
    for r in rows[hi + 1:]:
        if r and re.fullmatch(r"\d{4}( Q\d)?", str(r[0]).strip()):
            for j, c in cols.items():
                if isinstance(r[j], (int, float)):
                    out[c][str(r[0]).strip()] = float(r[j])
    return out


def fetch_rti() -> dict[str, dict[str, float]]:
    """Payrolled employees by section as {section: {'YYYY Qn': quarterly average}}."""
    wb = openpyxl.load_workbook(io.BytesIO(_workbook(RTI_PAGE)), read_only=True, data_only=True)
    rows = list(wb["23. Employees (Industry)"].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Date")
    codes = {j: str(c).strip() for j, c in enumerate(rows[hi - 1]) if c}
    months = ["january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december"]
    by: dict[str, dict[str, list[float]]] = {}
    for r in rows[hi + 1:]:
        m = re.match(r"([A-Za-z]+) (\d{4})", str(r[0] or "").strip())
        if not m or m.group(1).lower() not in months:
            continue
        q = f"{m.group(2)} Q{months.index(m.group(1).lower()) // 3 + 1}"
        for j, code in codes.items():
            sec = "S and T" if code in ("S", "T-U") else code
            if sec in SECTIONS and r[j] is not None:
                by.setdefault(sec, {}).setdefault(q, [0.0, 0.0, 0.0])[months.index(m.group(1).lower()) % 3] += r[j]
    # complete quarters only (all three months published)
    return {s: {q: sum(v) / 3 for q, v in qs.items() if all(v)} for s, qs in by.items()}


def fetch_self_employed() -> dict[str, dict[str, float]]:
    """Self-employment jobs by section (Workforce Jobs, seasonally adjusted) as
    {section: {'YYYY Qn': jobs}}. WFJ is measured in the quarter's last month."""
    d = pd.read_excel(io.BytesIO(_workbook(JOBS02_PAGE, "xls")), sheet_name="SEJ SA", header=None)
    codes = {j: str(c).strip() for j, c in enumerate(d.iloc[4]) if isinstance(c, str) and len(c.strip()) == 1}
    mon = {"Mar": 1, "Jun": 2, "Sep": 3, "Dec": 4}
    out: dict[str, dict[str, float]] = {}
    for _, r in d.iloc[5:].iterrows():
        m = re.match(r"(Mar|Jun|Sep|Dec) (\d{2})", str(r[0]).strip())
        if not m:
            continue
        yy = int(m.group(2))
        q = f"{1900 + yy if yy > 50 else 2000 + yy} Q{mon[m.group(1)]}"
        for j, code in codes.items():
            sec = "S and T" if code in ("S", "T") else code
            if sec in SECTIONS and pd.notna(r[j]):
                out.setdefault(sec, {})[q] = out.get(sec, {}).get(q, 0.0) + float(r[j]) * 1000
    return out


def uk_data() -> dict:
    """Quarterly UK series by section: real GVA index, current-price GVA, RF-method
    hours and ONS hours, plus the whole-economy current-price total."""
    hours_wb, jobs_wb = (openpyxl.load_workbook(io.BytesIO(_workbook(PROD.format(d))), read_only=True)
                         for d in ("outputperhourworkeduk", "outputperjobuk"))
    cvm, cp = _ons_table(hours_wb, "Table_20"), _ons_table(hours_wb, "Table_21")
    ons_hours, ons_jobs = _ons_table(hours_wb, "Table_23"), _ons_table(jobs_wb, "Table_23")
    rti, sej = fetch_rti(), fetch_self_employed()
    quarters = sorted(set.intersection(*(set(s[sec]) for s in (cvm, ons_hours, ons_jobs, rti, sej)
                                         for sec in SECTIONS)))
    rf_hours = {sec: {q: (rti[sec][q] + sej[sec][q]) * ons_hours[sec][q] / ons_jobs[sec][q]
                      for q in quarters} for sec in SECTIONS}
    total = next(c for c in cp if c.startswith("A to T"))
    return {"quarters": quarters, "cvm": cvm, "cp": cp, "hours": rf_hours, "ons_hours": ons_hours,
            "total_cp": cp[total]}


# ---- US -------------------------------------------------------------------------------

def us_data() -> dict:
    """Annual US series by BEA line: real quantity index and current-price value added;
    and BLS total hours by EP sector."""
    wb = openpyxl.load_workbook(io.BytesIO(get(BEA_VA, timeout=180)), read_only=True)

    def table(sheet: str) -> dict[int, dict[int, float]]:
        rows = list(wb[sheet].iter_rows(values_only=True))
        hi = next(i for i, r in enumerate(rows) if r and r[0] == "Line")
        years = {j: int(c) for j, c in enumerate(rows[hi]) if c and str(c).isdigit()}
        return {int(r[0]): {y: float(r[j]) for j, y in years.items() if isinstance(r[j], (int, float))}
                for r in rows[hi + 1:] if r and str(r[0]).isdigit()}

    if not BLS_ZIP.exists():
        sys.exit(f"Download {BLS_EP} in a browser (bls.gov refuses scripted requests) and save it as {BLS_ZIP}")
    with zipfile.ZipFile(BLS_ZIP) as z:
        name = next(n for n in z.namelist() if re.fullmatch(r"emp\d{4}\.csv", n.lower()))
        rows = list(csv.reader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))
    years = [int(y) for y in rows[0][2:]]
    hours = {int(r[1]): dict(zip(years, map(float, r[2:]))) for r in rows[1:] if r and r[0] == "5"}
    return {"real": table("TVA103-A"), "cp": table("TVA105-A"), "hours": hours}


# ---- calculations -------------------------------------------------------------------------

def _avg(s: dict[str, float], periods: list[str]) -> float:
    return sum(s[p] for p in periods) / len(periods)


def fig6_rows(uk: dict) -> tuple[list[dict], list[str]]:
    """Change in GVA per hour by section, 2019 to the latest four quarters."""
    base = [f"{BASE_YEAR} Q{i}" for i in range(1, 5)]
    latest = uk["quarters"][-4:]
    total_2019 = _avg(uk["total_cp"], base)
    rows = []
    for sec, (name, group) in SECTIONS.items():
        def change(hours):
            return 100 * ((_avg(uk["cvm"][sec], latest) / _avg(hours, latest)) /
                          (_avg(uk["cvm"][sec], base) / _avg(hours, base)) - 1)
        rows.append({"section": sec, "sector": name, "group": group,
                     "gva_share_2019": round(100 * _avg(uk["cp"][sec], base) / total_2019, 2),
                     "change_gva_per_hour": round(change(uk["hours"][sec]), 1),
                     "change_ons_output_per_hour": round(change(uk["ons_hours"][sec]), 1),
                     "change_gva": round(100 * (_avg(uk["cvm"][sec], latest) / _avg(uk["cvm"][sec], base) - 1), 1),
                     "change_hours": round(100 * (_avg(uk["hours"][sec], latest) / _avg(uk["hours"][sec], base) - 1), 1)})
    return rows, latest


def _contributions(real, cp, hours, total, years) -> dict[int, tuple[float, float]]:
    """{year: (contribution in ppts, share of GVA in the year before)} for one merged sector.
    real/cp: lists of {year: value} for the sector's parts; hours: {year: total hours}."""
    out = {}
    for t in years:
        weights = [c[t - 1] for c in cp]
        real_growth = sum(w * r[t] / r[t - 1] for w, r in zip(weights, real)) / sum(weights)
        share = sum(weights) / total[t - 1]
        out[t] = (100 * share * (real_growth / (hours[t] / hours[t - 1]) - 1), 100 * share)
    return out


def fig10_rows(uk: dict, us: dict) -> tuple[list[dict], int]:
    """Average annual within-industry contributions over the growth years START (on START - 1)
    to the latest year both have."""
    def annual(s: dict[str, float], how=sum) -> dict[int, float]:
        by: dict[int, list[float]] = {}
        for q, v in s.items():
            by.setdefault(int(q[:4]), []).append(v)
        return {y: how(v) for y, v in by.items() if len(v) == 4}

    mean = lambda v: sum(v) / len(v)  # noqa: E731
    uk_years = set(annual(uk["hours"]["A"]))
    us_years = set(us["hours"][1]) & set(us["real"][BEA_TOTAL])
    last = max(uk_years & us_years)
    years = list(range(START, last + 1))
    uk_total = annual(uk["total_cp"])
    us_total = {y: us["cp"][BEA_TOTAL][y] - us["cp"][BEA_HOUSING][y] for y in us["cp"][BEA_TOTAL]}
    rows = []
    for name, (secs, lines, bls) in COMPARE.items():
        uk_c = _contributions([annual(uk["cvm"][s], mean) for s in secs], [annual(uk["cp"][s]) for s in secs],
                              {y: sum(annual(uk["hours"][s])[y] for s in secs) for y in uk_years},
                              uk_total, years)
        us_c = _contributions([us["real"][ln] for ln in lines], [us["cp"][ln] for ln in lines],
                              {y: sum(us["hours"][n][y] for n in bls) for y in us_years}, us_total, years)
        row = {"sector": name}
        for c, con in (("uk", uk_c), ("us", us_c)):
            row[f"{c}_contribution"] = round(mean([con[t][0] for t in years]), 3)
            row[f"{c}_gva_share"] = round(mean([con[t][1] for t in years]), 2)
            row[f"{c}_contribution_2020_2023"] = round(mean([con[t][0] for t in range(START, 2024)]), 3)
            for t in years:
                row[f"{c}_{t}"] = round(con[t][0], 3)
        rows.append(row)
    return rows, last


# ---- charts -------------------------------------------------------------------------------

def _sign(v: float, d: int = 0) -> str:
    return f"{v:+.{d}f}".replace("-", "−")


def chart_fig6(rows: list[dict], latest: list[str]) -> None:
    fig, ax = hs.figure("UK productivity growth by sector since 2019",
                        f"% change in real GVA per hour, {BASE_YEAR} to the year to {latest[-1]}; "
                        f"bar width = share of {BASE_YEAR} GVA",
                        source=SOURCE_UK + " Hours: payrolled employees (RTI) plus self-employment jobs (WFJ), "
                        "times ONS average hours per job. Real estate excludes imputed rent.")
    ax.set_position([hs._x(hs.LEFT_CM), 0.39, 1 - hs._x(hs.LEFT_CM) - hs._x(hs.RIGHT_CM), 0.40])
    colour = dict(zip(GROUPS, hs.COLOURS["series"]))
    order = [r for g in GROUPS for r in sorted((r for r in rows if r["group"] == g),
                                               key=lambda r: -r["change_gva_per_hour"])]
    x, gap, labels = 0.0, 0.25, []
    for r in order:
        w, v = r["gva_share_2019"], r["change_gva_per_hour"]
        ax.bar(x, v, width=w, align="edge", color=colour[r["group"]], linewidth=0)
        labels.append([x + w / 2, f"{r['sector']} {_sign(v) if round(v) else '0'}%"])
        x += w + gap
    # sector names under the plot, Marimekko-style; narrow neighbours are pushed apart
    min_gap = 1.9   # in % of GVA, a little over one line of 9pt text at this width
    for prev, lab in zip(labels, labels[1:]):
        lab[0] = max(lab[0], prev[0] + min_gap)
    shift = max(0.0, labels[-1][0] - x)   # pull back any run-off at the right edge
    for lab in labels:
        lab[0] -= shift * (lab[0] > x - 10)
    for lx, text in labels:
        ax.text(lx, -0.03, text, transform=ax.get_xaxis_transform(), rotation=90, ha="center", va="top",
                fontsize=9, color=hs.COLOURS["text_2"])
    lo = min(r["change_gva_per_hour"] for r in rows)
    hi = max(r["change_gva_per_hour"] for r in rows)
    ax.set_ylim(10 * (lo // 10) - 2, 10 * (hi // 10 + 1) + 2)
    ax.axhline(0, color=hs.COLOURS["grey"], linewidth=0.9)
    ax.set_xlim(-0.5, x + 0.3)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.0f}%".replace("-", "\u2212") if v else "0%")
    fig.legend(handles=[Patch(color=colour[g], label=g) for g in GROUPS], loc="upper left",
               bbox_to_anchor=(hs._x(hs.LEFT_CM - 0.2), 0.86), ncol=4, handlelength=1.2, columnspacing=1.8)
    IMG.mkdir(parents=True, exist_ok=True)
    hs.save_png(fig, IMG / "uk-productivity-by-sector.png")


def chart_fig10(rows: list[dict], last: int) -> None:
    fig, ax = hs.figure(f"Contributions to productivity growth by sector, {START - 1}–{last}: UK vs US",
                        "Average annual within-industry contribution to growth in GVA per hour, percentage points; "
                        "bubble size = share of GVA",
                        source=SOURCE_US + " Excludes education, health, public administration and real estate. "
                        "US sectors aligned to UK SIC sections as in RF's Annex 1. PSTA = professional, "
                        "scientific and technical.", left_cm=4.4)
    order = sorted(rows, key=lambda r: r["us_contribution"] - r["uk_contribution"])
    blue, amber = hs.COLOURS["series"][:2]
    for i, r in enumerate(order):
        ax.plot([r["uk_contribution"], r["us_contribution"]], [i, i], color=hs.COLOURS["grid"], linewidth=3,
                zorder=1, solid_capstyle="butt")
        for c, col in (("uk", blue), ("us", amber)):
            ax.scatter(r[f"{c}_contribution"], i, s=28 * r[f"{c}_gva_share"] + 12, color=col, alpha=0.85,
                       edgecolor="white", linewidth=0.8, zorder=3)
    ax.set_yticks(range(len(order)), [r["sector"] for r in order])
    ax.axvline(0, color=hs.COLOURS["grey"], linewidth=0.9, zorder=0)
    ax.grid(axis="x", color=hs.COLOURS["grid"], linewidth=0.6)
    ax.grid(axis="y", visible=False)
    ax.set_ylim(-0.7, len(order) - 0.3)
    ax.spines["bottom"].set_visible(False)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.2f}".replace("-", "−") if abs(v) > 1e-9 else "0")
    handles = [Line2D([], [], marker="o", linestyle="", markersize=9, color=col, label=lab)
               for col, lab in ((blue, "UK"), (amber, "US"))]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(hs._x(hs.LEFT_CM - 0.2), 0.86), ncol=2,
               handlelength=1.0, columnspacing=1.8)
    IMG.mkdir(parents=True, exist_ok=True)
    hs.save_png(fig, IMG / "uk-us-productivity-contributions.png")


def _write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    hs.apply()
    uk, us = uk_data(), us_data()
    r6, latest = fig6_rows(uk)
    chart_fig6(r6, latest)
    _write(r6, OUT / "uk_productivity_by_sector.csv")
    r10, last = fig10_rows(uk, us)
    chart_fig10(r10, last)
    _write(r10, OUT / "uk_us_productivity_contributions.csv")
    print(f"[fig6] 2019 to {latest[0]}-{latest[-1]}")
    for r in r6:
        print(f"  {r['sector']:20s} share {r['gva_share_2019']:5.1f}  RF-method {r['change_gva_per_hour']:+6.1f}  "
              f"ONS {r['change_ons_output_per_hour']:+6.1f}")
    print(f"[fig10] {START - 1}-{last}  (2019-2023 in brackets)")
    for r in r10:
        print(f"  {r['sector']:20s} UK {r['uk_contribution']:+.3f} ({r['uk_contribution_2020_2023']:+.3f})  "
              f"US {r['us_contribution']:+.3f} ({r['us_contribution_2020_2023']:+.3f})")


if __name__ == "__main__":
    main()
