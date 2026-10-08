"""The employment-rate composition analysis again, using HMRC PAYE RTI instead of the LFS.

RTI counts payrolled employees from tax records, so it avoids the LFS's falling
response rates. But it differs from the LFS in three ways:
  - age only (RTI has no split by sex): six groups, 0-17 ... 65+
  - employees only: no self-employed, so "rates" are payrolled employees / population
    and sit well below LFS employment rates
  - population comes from ONS mid-year estimates (Nomis), interpolated between mid-years
    and, after the latest estimate, extended at that year's growth rate per age band
The "0 to 17" RTI group is divided by the population aged 16-17 (very few under-16s
are on payrolls).

For a like-for-like comparison the LFS is also decomposed by age only. Everything is
quarterly (RTI months averaged) against the 2019 average, using the same midpoint
decomposition as composition.py.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import composition as lfs  # noqa: E402
from ukmacro import nomis  # noqa: E402
from ukmacro.http import get, get_text  # noqa: E402

RTI_PAGE = ("https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/"
            "datasets/realtimeinformationstatisticsreferencetableseasonallyadjusted")
RTI_SHEET = "28. Employees (Age)"
# RTI age band -> our group label (RTI's "0 to 17" is set against the 16-17 population)
RTI_BANDS = {"0 to 17": "16-17", "18 to 24": "18-24", "25 to 34": "25-34",
             "35 to 49": "35-49", "50 to 64": "50-64", "65 and over": "65+"}
# Nomis NM_2002_1 (mid-year population estimates) age codes making up each band
POP_CODES = {"16-17": [204], "18-24": [205], "25-34": [7, 8], "35-49": [9, 10, 11],
             "50-64": [208], "65+": [209]}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
SOURCE = ("HMRC PAYE Real Time Information (ONS, seasonally adjusted); ONS mid-year population "
          "estimates (Nomis); ONS Labour Force Survey; ukmacro calculations")


def fetch_rti() -> dict[str, dict[str, float]]:
    """{band: {'YYYY-MM': payrolled employees}} from the latest RTI reference table."""
    link = re.search(r'/file\?uri=[^"]+\.xlsx', get_text(RTI_PAGE)).group(0)
    wb = openpyxl.load_workbook(io.BytesIO(get("https://www.ons.gov.uk" + link, timeout=180)),
                                read_only=True, data_only=True)
    rows = list(wb[RTI_SHEET].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Date")
    cols = {j: RTI_BANDS[str(h).strip()] for j, h in enumerate(rows[hi]) if str(h).strip() in RTI_BANDS}
    out: dict[str, dict[str, float]] = {b: {} for b in RTI_BANDS.values()}
    for r in rows[hi + 1:]:
        if not r or not r[0]:
            continue
        m = re.match(r"([A-Za-z]+) (\d{4})", str(r[0]).strip())  # e.g. "August 2026"
        if not m or m.group(1).lower() not in MONTHS:
            continue
        key = f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}"
        for j, band in cols.items():
            if r[j] not in (None, ""):
                out[band][key] = float(r[j])
    return out


def fetch_population() -> tuple[dict[str, dict[int, float]], int]:
    """({band: {year: mid-year population}}, latest year) from Nomis."""
    codes = sorted({c for cs in POP_CODES.values() for c in cs})
    rows = nomis.fetch("NM_2002_1", geography="2092957697", date="latestMINUS12-latest", gender="0",
                       c_age=",".join(map(str, codes)), measures="20100",
                       select="date_name,c_age,obs_value")
    by: dict[int, dict[int, float]] = {}
    for r in rows:
        by.setdefault(int(r["DATE_NAME"]), {})[int(r["C_AGE"])] = float(r["OBS_VALUE"])
    pop = {b: {y: sum(v[c] for c in cs) for y, v in by.items()} for b, cs in POP_CODES.items()}
    return pop, max(by)


def monthly_population(pop: dict[int, float], months: list[str]) -> dict[str, float]:
    """Population for each month: linear between mid-year estimates (taken as June),
    and after the latest estimate, extended at that last year's growth rate."""
    years = sorted(pop)
    out = {}
    for m in months:
        y, mo = int(m[:4]), int(m[5:])
        t = y + (mo - 6) / 12  # time in years, with June of year y = y
        lo = max([yy for yy in years if yy <= t], default=years[0])  # estimate at or before t
        if lo == years[-1]:  # beyond the latest estimate: project
            g = pop[years[-1]] / pop[years[-2]]
            out[m] = pop[lo] * g ** (t - lo)
        else:
            hi = lo + 1
            out[m] = pop[lo] + (pop[hi] - pop[lo]) * (t - lo)
    return out


def to_quarters(series: dict[str, float]) -> dict[str, float]:
    """Average complete quarters of a monthly series."""
    groups: dict[str, list[float]] = {}
    for m, v in series.items():
        groups.setdefault(f"{m[:4]}-Q{(int(m[5:]) - 1) // 3 + 1}", []).append(v)
    return {q: sum(v) / 3 for q, v in groups.items() if len(v) == 3}


def rti_cells() -> tuple[dict, int]:
    """RTI cells in the same shape as composition.fetch_cells(), by age only, quarterly;
    plus the latest mid-year population estimate year (later months are projected)."""
    rti = fetch_rti()
    pop, latest_year = fetch_population()
    cells = {}
    for band, emp in rti.items():
        months = sorted(emp)
        cells[("All", band)] = {"emp": to_quarters(emp),
                                "pop": to_quarters(monthly_population(pop[band], months))}
    return cells, latest_year


def lfs_age_only(cells: dict) -> dict:
    """Merge the LFS men/women cells into age-only cells."""
    out = {}
    for age in lfs.AGES:
        m, w = cells[("Men", age)], cells[("Women", age)]
        qs = set(m["emp"]) & set(w["emp"]) & set(m["pop"]) & set(w["pop"])
        out[("All", age)] = {"emp": {q: m["emp"][q] + w["emp"][q] for q in qs},
                             "pop": {q: m["pop"][q] + w["pop"][q] for q in qs}}
    return out


def build(lcells: dict | None = None) -> None:
    """Build the RTI charts. `lcells` are the LFS cells, if composition.build() has
    already fetched them."""
    rcells, latest_pop_year = rti_cells()
    lcells = lcells or lfs.fetch_cells()
    lage = lfs_age_only(lcells)
    projected = f"Population after mid-{latest_pop_year} is projected at that year's growth rate."
    for ages, label, slug in [(lfs.AGES, "aged 16 and over", "16plus"), (lfs.AGES[:-1], "aged 16-64", "16-64")]:
        rti_rows = lfs.decompose(rcells, ages)
        note = ("RTI counts payrolled employees only (no self-employed) and has no split by sex, so "
                "groups are six age bands. Base = 2019 average; months averaged to quarters. "
                + projected)
        lfs.publish(lfs.chart(
            f"rti-decomposition-{slug}",
            f"Change in the payrolled employee rate {label} since 2019 (RTI): composition vs within-group",
            "Percentage points", "stacked-bar",
            [{"key": "composition", "label": "Composition (age mix)"},
             {"key": "within", "label": "Within-group payroll rates"},
             {"key": "change", "label": "Total change", "mark": "line"}],
            [{k: r[k] for k in ("date", "composition", "within", "change")}
             for r in rti_rows if r["date"] >= f"{lfs.BASE_YEAR}-Q1"], note, source=SOURCE))

        # like-for-like comparison at the latest quarter all three versions have
        lfs_rows = {r["date"]: r for r in lfs.decompose(lcells, ages)}
        lage_rows = {r["date"]: r for r in lfs.decompose(lage, ages)}
        rti_by_q = {r["date"]: r for r in rti_rows}
        q = max(set(lfs_rows) & set(lage_rows) & set(rti_by_q))
        versions = [("LFS, age x sex (12 groups)", lfs_rows[q]), ("LFS, age only (6 groups)", lage_rows[q]),
                    ("RTI, age only (6 groups)", rti_by_q[q])]
        lfs.publish(lfs.chart(
            f"composition-lfs-vs-rti-{slug}",
            f"Change in the employment rate {label}, 2019 to {q.replace('-', ' ')}: LFS vs RTI",
            "Percentage points", "grouped-hbar",
            [{"key": "lfs_age_sex", "label": versions[0][0]},
             {"key": "lfs_age", "label": versions[1][0]},
             {"key": "rti_age", "label": versions[2][0]}],
            [{"date": part, **{k: v[1][field] for k, v in zip(("lfs_age_sex", "lfs_age", "rti_age"), versions)}}
             for part, field in (("Total change", "change"), ("Composition", "composition"),
                                 ("Within-group", "within"))],
            "LFS = employment (employees + self-employed) / LFS population. RTI = payrolled "
            "employees / ONS mid-year population. Base = 2019 average. " + projected, source=SOURCE))

        lfs.write_csv(lfs.workings(rcells, ages, rti_rows[-1]["date"]),
                      lfs.DATA / f"rti-composition-workings-{slug}.csv")
        last = rti_rows[-1]
        print(f"[composition-rti] {label}: {last['date']} change {last['change']:+.2f}pp = "
              f"composition {last['composition']:+.2f} + within {last['within']:+.2f}")
        for name, r in versions:
            print(f"    {q} {name:28s} total {r['change']:+.2f}  composition {r['composition']:+.2f}  "
                  f"within {r['within']:+.2f}")


if __name__ == "__main__":
    build()
