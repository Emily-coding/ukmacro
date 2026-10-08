"""How much of the change in the employment rate is compositional?

The aggregate employment rate is a population-weighted average of the rates of
age x sex groups:  E_t = sum_i s_it * e_it,  where s_i is group i's share of the
population and e_i its employment rate. Against a base period 0 (the 2019 average),
the change splits exactly into two parts (midpoint / Shapley weights, so there is
no leftover interaction term):

    composition  = sum_i (s_it - s_i0) * (e_i0 + e_it) / 2   population mix shifting (ageing, sex)
                 = sum_i (s_it - s_i0) * ((e_i0 + e_it) / 2 - E_0)
                   (same total, because the share changes sum to zero; this second form is
                   used for each group, so a growing group with a below-average employment
                   rate shows as a negative contribution)
    within-group = sum_i (e_it - e_i0) * (s_i0 + s_it) / 2   rates changing inside each group

Groups: men and women x 16-17, 18-24, 25-34, 35-49, 50-64, 65+ (LFS, seasonally
adjusted, quarterly). Population per group = employment level / employment rate.
ONS publishes no age-band series for women 65+, so that group is the 16+ total
minus the other five bands.

The same machinery is reused by composition_rti.py (HMRC RTI) and neet.py (NEET
rate): anything shaped like `cells` below can be decomposed.

    cells = {(group, age): {"emp": {quarter: count}, "pop": {quarter: population}}}

Writes chart JSON to data/labour-markets/, PNGs to img/labour-markets/, and a
group-by-group workings CSV for checking the arithmetic by hand.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from ukmacro import charts, ons  # noqa: E402

BASE_YEAR = "2019"   # the base is the average of this year's quarters
START = "2015-Q1"    # first quarter shown in the charts
DATA = REPO / "data" / "labour-markets"
IMG = REPO / "img" / "labour-markets"
SOURCE = "ONS Labour Force Survey (LMS), seasonally adjusted; ukmacro calculations"

AGES = ["16-17", "18-24", "25-34", "35-49", "50-64", "65+"]
# (employment rate, employment level) CDIDs in the LMS dataset
CELLS = {
    ("Men", "16-17"): ("YBUB", "YBTP"), ("Women", "16-17"): ("YBUC", "YBTQ"),
    ("Men", "18-24"): ("YBUE", "YBTS"), ("Women", "18-24"): ("YBUF", "YBTT"),
    ("Men", "25-34"): ("YBUH", "YBTV"), ("Women", "25-34"): ("YBUI", "YBTW"),
    ("Men", "35-49"): ("YBUK", "YBTY"), ("Women", "35-49"): ("YBUL", "YBTZ"),
    ("Men", "50-64"): ("YBUN", "MGUX"), ("Women", "50-64"): ("LF2V", "LF27"),
    ("Men", "65+"): ("YBUQ", "MGVA"),
}
# women 16+ employment level and population, to derive the missing women 65+ group
WOMEN_16PLUS = {"level": "MGSB", "pop": "MGSN"}


# ---------------------------------------------------------------- data

def fetch_cells() -> dict:
    """LFS cells: {(sex, age): {'emp': {quarter: thousands}, 'pop': {quarter: thousands}}}."""
    def get(cdid):
        return dict(ons.fetch(cdid, "LMS", "Q")["obs"])

    cells = {}
    for key, (rate_id, level_id) in CELLS.items():
        rate, level = get(rate_id), get(level_id)
        cells[key] = {"emp": level,
                      "pop": {q: level[q] / rate[q] * 100 for q in level if rate.get(q)}}

    # women 65+ = women 16+ minus the five younger bands (quarters all of them have)
    w_level, w_pop = get(WOMEN_16PLUS["level"]), get(WOMEN_16PLUS["pop"])
    others = [cells[("Women", a)] for a in AGES[:-1]]
    qs = set(w_level) & set(w_pop)
    for c in others:
        qs &= set(c["emp"]) & set(c["pop"])
    cells[("Women", "65+")] = {
        "emp": {q: w_level[q] - sum(c["emp"][q] for c in others) for q in qs},
        "pop": {q: w_pop[q] - sum(c["pop"][q] for c in others) for q in qs},
    }
    return cells


# ---------------------------------------------------------------- the decomposition

def _keys(cells: dict, ages: list[str]) -> list:
    """The groups in the age range being analysed (e.g. all ages for 16+, no 65+ for 16-64)."""
    return [k for k in cells if k[1] in ages]


def _quarters(cells: dict, keys: list) -> list[str]:
    """Quarters for which every group has both a count and a population."""
    return sorted(set.intersection(*(set(cells[k]["pop"]) & set(cells[k]["emp"]) for k in keys)))


def _mix(cells: dict, keys: list, q: str) -> tuple[dict, dict]:
    """(population share as a fraction, rate in %) for each group in quarter q."""
    total_pop = sum(cells[k]["pop"][q] for k in keys)
    share = {k: cells[k]["pop"][q] / total_pop for k in keys}
    rate = {k: cells[k]["emp"][q] / cells[k]["pop"][q] * 100 for k in keys}
    return share, rate


def _base(cells: dict, keys: list) -> tuple[dict, dict, float]:
    """Base-year average shares, rates and aggregate rate (s0, e0, E0)."""
    base_qs = [q for q in _quarters(cells, keys) if q.startswith(BASE_YEAR)]
    if not base_qs:
        raise ValueError(f"no {BASE_YEAR} quarters available for every group")
    mixes = [_mix(cells, keys, q) for q in base_qs]
    s0 = {k: sum(m[0][k] for m in mixes) / len(mixes) for k in keys}
    e0 = {k: sum(m[1][k] for m in mixes) / len(mixes) for k in keys}
    return s0, e0, sum(s0[k] * e0[k] for k in keys)


def decompose(cells: dict, ages: list[str]) -> list[dict]:
    """Quarterly decomposition of the change in the rate since the base year.

    Each row: actual rate, the rate at the base-year population mix, the total change,
    its composition and within-group parts (pp), and both parts by group."""
    keys = _keys(cells, ages)
    s0, e0, rate0 = _base(cells, keys)
    out = []
    for q in _quarters(cells, keys):
        if q < START:
            continue
        s, e = _mix(cells, keys, q)
        comp = {k: (s[k] - s0[k]) * ((e0[k] + e[k]) / 2 - rate0) for k in keys}
        within = {k: (e[k] - e0[k]) * (s0[k] + s[k]) / 2 for k in keys}
        actual = sum(s[k] * e[k] for k in keys)
        out.append({
            "date": q,
            "actual": round(actual, 2),
            "fixed_mix": round(sum(s0[k] * e[k] for k in keys), 2),  # today's rates, base-year mix
            "change": round(actual - rate0, 2),
            "composition": round(sum(comp.values()), 2),
            "within": round(sum(within.values()), 2),
            "_within_by_group": {f"{k[0]} {k[1]}": round(v, 3) for k, v in within.items()},
            "_composition_by_group": {f"{k[0]} {k[1]}": round(v, 3) for k, v in comp.items()},
        })
    return out


def workings(cells: dict, ages: list[str], quarter: str, measure: str = "emp_rate") -> list[dict]:
    """Group-by-group calculation for one quarter vs the base year, in percent, so the
    arithmetic can be checked by hand. Uses the same base as decompose()."""
    keys = _keys(cells, ages)
    s0, e0, rate0 = _base(cells, keys)
    st, et = _mix(cells, keys, quarter)
    return [{
        "group": f"{k[0]} {k[1]}",
        f"pop_share_{BASE_YEAR}_%": round(s0[k] * 100, 2), f"pop_share_{quarter}_%": round(st[k] * 100, 2),
        f"{measure}_{BASE_YEAR}_%": round(e0[k], 1), f"{measure}_{quarter}_%": round(et[k], 1),
        "composition_pp": round((st[k] - s0[k]) * ((e0[k] + et[k]) / 2 - rate0), 3),
        "within_pp": round((et[k] - e0[k]) * (s0[k] + st[k]) / 2, 3),
    } for k in keys]


# ---------------------------------------------------------------- output helpers

def chart(slug: str, title: str, units: str, kind: str, series: list[dict], data: list[dict],
          note: str, source: str = SOURCE) -> dict:
    """A chart in the repo's common JSON format (see ukmacro/charts.py)."""
    return {"slug": slug, "category": "labour-markets", "title": title, "type": kind, "freq": "Q",
            "units": units, "source": source, "note": note, "series": series,
            "data_through": data[-1]["date"] if data else None, "status": "ok", "data": data}


def publish(c: dict) -> None:
    """Write the chart JSON and its PNG. The PNG is only re-rendered when the JSON
    changed: PNG bytes vary slightly between machines, and an unchanged chart
    shouldn't produce a daily commit. The theme is stored in the JSON so that a
    theme change also counts as a change."""
    c["theme"] = charts.DEFAULT_THEME
    js, png = DATA / f"{c['slug']}.json", IMG / f"{c['slug']}.png"
    text = json.dumps(c, indent=1) + "\n"
    if png.exists() and js.exists() and js.read_text() == text:
        return
    js.write_text(text)
    charts.render(c, png)


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


# ---------------------------------------------------------------- build

def build(cells: dict | None = None) -> dict:
    """Build the LFS composition charts. Returns the LFS cells so other analyses
    (composition_rti) can reuse them without fetching again."""
    cells = cells or fetch_cells()
    for ages, label, slug in [(AGES, "aged 16 and over", "16plus"), (AGES[:-1], "aged 16-64", "16-64")]:
        rows = decompose(cells, ages)
        last = rows[-1]
        note = (f"Groups: men and women by age band. Base = {BASE_YEAR} average. "
                "Midpoint (Shapley) weights, so composition + within-group = total change exactly.")

        # 1. actual rate vs the rate with the population mix held at the base year
        publish(chart(f"emp-composition-{slug}", f"Employment rate {label}: actual vs {BASE_YEAR} population mix",
                      "%", "line",
                      [{"key": "actual", "label": "Actual"},
                       {"key": "fixed_mix", "label": f"Holding the age/sex mix at {BASE_YEAR}"}],
                      [{k: r[k] for k in ("date", "actual", "fixed_mix")} for r in rows], note))

        # 2. change since the base year, split into composition and within-group.
        # For 16+, within-group is shown separately for 16-64 and 65+: they often move
        # in opposite directions, and a near-zero total would otherwise hide that.
        def within_65plus(r):
            return round(sum(v for g, v in r["_within_by_group"].items() if g.endswith("65+")), 2)

        within_series = ([{"key": "within_16_64", "label": "Within-group: aged 16-64"},
                          {"key": "within_65plus", "label": "Within-group: aged 65+"}] if "65+" in ages
                         else [{"key": "within", "label": "Within-group employment rates"}])
        publish(chart(f"emp-decomposition-{slug}",
                      f"Change in the employment rate {label} since {BASE_YEAR}: composition vs within-group",
                      "Percentage points", "stacked-bar",
                      [{"key": "composition", "label": "Composition (age/sex mix)"}] + within_series
                      + [{"key": "change", "label": "Total change", "mark": "line"}],
                      [{"date": r["date"], "composition": r["composition"], "within": r["within"],
                        "within_16_64": round(r["within"] - within_65plus(r), 2),
                        "within_65plus": within_65plus(r), "change": r["change"]}
                       for r in rows if r["date"] >= f"{BASE_YEAR}-Q1"], note))

        # 3. within-group contributions by group, latest quarter
        by_group = last["_within_by_group"]
        publish(chart(f"emp-within-by-group-{slug}",
                      f"Contributions to the change in the employment rate {label}, "
                      f"{BASE_YEAR} to {last['date'].replace('-', ' ')}",
                      "Percentage points", "grouped-hbar",
                      [{"key": "Men", "label": "Men"}, {"key": "Women", "label": "Women"}],
                      [{"date": a, "Men": by_group[f"Men {a}"], "Women": by_group[f"Women {a}"]} for a in ages],
                      note + " Within-group contributions only: each group's rate change "
                             "weighted by its population share."))

        write_csv(workings(cells, ages, last["date"]), DATA / f"emp-composition-workings-{slug}.csv")
        print(f"[composition] {label}: {last['date']} change {last['change']:+.2f}pp = "
              f"composition {last['composition']:+.2f} + within {last['within']:+.2f}")
    return cells


if __name__ == "__main__":
    build()
