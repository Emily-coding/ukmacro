"""How much of the change in the NEET rate (16-24) is compositional?

Same method as composition.py, for young people not in education, employment or
training. Four groups: men and women x 16-17 and 18-24 (ONS NEET table 1, seasonally
adjusted, quarterly). The NEET rate = NEET / population in each group, and

    change = composition (age/sex mix of 16-24s) + within-group (NEET rates)

Because NEET = unemployed NEET + economically inactive NEET, the within-group part
splits exactly into those two reasons.

ONS reweighted the data from Jan-Mar 2019, so the 2019 base sits after that break.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import composition as lfs  # noqa: E402
from ukmacro import charts  # noqa: E402
from ukmacro.http import get, get_text  # noqa: E402

PAGE = ("https://www.ons.gov.uk/employmentandlabourmarket/peoplenotinwork/unemployment/datasets/"
        "youngpeoplenotineducationemploymentortrainingneettable1")
SHEETS = {"Men": "Men - SA", "Women": "Women - SA"}
# column offsets of each age block: NEET total, unemployed, inactive, population, rate
BLOCKS = {"16-17": 6, "18-24": 11}
QUARTER = {"Jan-Mar": 1, "Apr-Jun": 2, "Jul-Sep": 3, "Oct-Dec": 4}
AGES = list(BLOCKS)
SOURCE = "ONS Young people not in education, employment or training (NEET) table 1, seasonally adjusted; ukmacro calculations"


def fetch_cells() -> dict[str, dict]:
    """{'total'|'unemployed'|'inactive': {(sex, age): {'emp': {q: NEET}, 'pop': {q: population}}}}
    ('emp' holds the NEET count so composition.decompose() can be reused unchanged.)"""
    link = re.search(r'/file\?uri=[^"]+\.xlsx', get_text(PAGE)).group(0)
    wb = openpyxl.load_workbook(io.BytesIO(get("https://www.ons.gov.uk" + link)), read_only=True, data_only=True)
    out = {k: {} for k in ("total", "unemployed", "inactive")}
    for sex, sheet in SHEETS.items():
        for age in AGES:
            for k in out:
                out[k][(sex, age)] = {"emp": {}, "pop": {}}
        for r in wb[sheet].iter_rows(values_only=True):
            m = re.match(r"^([A-Z][a-z]{2}-[A-Z][a-z]{2}) (\d{4})", str(r[0] or ""))
            if not m or m.group(1) not in QUARTER:
                continue
            q = f"{m.group(2)}-Q{QUARTER[m.group(1)]}"
            for age, c in BLOCKS.items():
                total, unemp, inact, pop = r[c:c + 4]
                if not isinstance(pop, (int, float)):
                    continue
                # '..' = not available, '*' = suppressed by ONS. A suppressed part is left
                # out (not derived as total minus the other part, which would undo it).
                for k, v in (("total", total), ("unemployed", unemp), ("inactive", inact)):
                    if isinstance(v, (int, float)):
                        out[k][(sex, age)]["emp"][q] = v
                        out[k][(sex, age)]["pop"][q] = pop
    return out


def build() -> None:
    cells = fetch_cells()
    rows = lfs.decompose(cells["total"], AGES)
    by_q = {k: {r["date"]: r for r in lfs.decompose(cells[k], AGES)} for k in ("unemployed", "inactive")}
    data = []
    for r in rows:
        if r["date"] < "2019-Q1":
            continue
        u, i = by_q["unemployed"].get(r["date"]), by_q["inactive"].get(r["date"])
        split = u is not None and i is not None
        data.append({"date": r["date"], "composition": r["composition"],
                     "within_unemployed": u["within"] if split else None,
                     "within_inactive": i["within"] if split else None,
                     "within_suppressed": None if split else r["within"],
                     "change": r["change"]})
    note = ("Groups: men and women aged 16-17 and 18-24. Base = 2019 average. Midpoint weights, so the "
            "parts add up to the total change. The within-group part splits exactly into unemployed "
            "and economically inactive NEETs, except in quarters where ONS suppressed one part (grey).")
    decomp = lfs.chart("neet-decomposition", "Change in the NEET rate aged 16-24 since 2019: composition vs within-group",
                       "Percentage points", "stacked-bar",
                       [{"key": "composition", "label": "Composition (age/sex mix)"},
                        {"key": "within_unemployed", "label": "Within-group: unemployed NEETs"},
                        {"key": "within_inactive", "label": "Within-group: inactive NEETs"},
                        {"key": "within_suppressed", "label": "Within-group (split suppressed)", "color": "neutral"},
                        {"key": "change", "label": "Total change", "mark": "line"}],
                       data, note)
    line = lfs.chart("neet-composition", "NEET rate aged 16-24: actual vs 2019 age/sex mix", "% of 16-24s", "line",
                     [{"key": "actual", "label": "Actual"},
                      {"key": "fixed_mix", "label": "Holding the age/sex mix at 2019"}],
                     [{k: r[k] for k in ("date", "actual", "fixed_mix")} for r in rows], note)
    last = rows[-1]
    within = {k: by_q[k][last["date"]]["_within_by_group"] for k in ("unemployed", "inactive")}
    groups = lfs.chart("neet-within-by-group",
                       f"Contributions to the change in the NEET rate aged 16-24, 2019 to {last['date'].replace('-', ' ')}",
                       "Percentage points", "grouped-hbar",
                       [{"key": "unemployed", "label": "Unemployed NEETs", "slot": 1},   # same colours as
                        {"key": "inactive", "label": "Economically inactive NEETs", "slot": 2}],  # the decomposition
                       [{"date": g, "unemployed": within["unemployed"][g], "inactive": within["inactive"][g]}
                        for g in last["_within_by_group"]],
                       note + " Within-group contributions only, by group.")
    for c in (decomp, line, groups):
        c["source"] = SOURCE
        c["theme"] = charts.DEFAULT_THEME
        js, png = lfs.DATA / f"{c['slug']}.json", lfs.IMG / f"{c['slug']}.png"
        text = json.dumps(c, indent=1) + "\n"
        if png.exists() and js.exists() and js.read_text() == text:
            continue
        js.write_text(text)
        charts.render(c, png)

    rows_w = lfs.workings(cells["total"], AGES, last["date"], measure="neet_rate")
    with (lfs.DATA / "neet-composition-workings.csv").open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows_w[0]))
        wr.writeheader()
        wr.writerows(rows_w)
    d = data[-1]
    print(f"[neet] quarters: {len(data)} since 2019, {sum(x['within_suppressed'] is not None for x in data)} without a reason split")
    print(f"[neet] {last['date']}: NEET rate {last['actual']:.1f}%, change {d['change']:+.2f}pp = composition "
          f"{d['composition']:+.2f} + within unemployed {d['within_unemployed']:+.2f} "
          f"+ within inactive {d['within_inactive']:+.2f}")


if __name__ == "__main__":
    build()
