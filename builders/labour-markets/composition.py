"""How much of the change in the employment rate is compositional?

The aggregate employment rate is a population-weighted average of the rates of
age x sex groups:  E_t = sum_i s_it * e_it,  where s_i is group i's share of the
population and e_i its employment rate. Against a base period 0 (2019 average),
the change splits exactly into two parts (midpoint / Shapley weights, so there is
no leftover interaction term):

    composition  = sum_i (s_it - s_i0) * (e_i0 + e_it) / 2   population mix shifting (ageing, sex)
                 = sum_i (s_it - s_i0) * ((e_i0 + e_it) / 2 - E_0)   (same total, as shares sum to 1;
                   this form is used per group, so a growing group with a below-average
                   employment rate shows as a negative contribution)
    within-group = sum_i (e_it - e_i0) * (s_i0 + s_it) / 2   rates changing inside each group

Groups: men and women x 16-17, 18-24, 25-34, 35-49, 50-64, 65+ (LFS, seasonally
adjusted, quarterly). Population per group = employment level / employment rate.
ONS publishes no age-band series for women 65+, so that group is the 16+ total
minus the other five bands.

Writes chart JSON to data/labour-markets/ and PNGs to img/labour-markets/.
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

BASE_YEAR = "2019"
START = "2015-Q1"
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
WOMEN_16PLUS = {"level": "MGSB", "pop": "MGSN"}  # for the derived women 65+ group


def fetch_cells() -> dict[tuple[str, str], dict[str, dict[str, float]]]:
    """{(sex, age): {'emp': {q: thousands}, 'pop': {q: thousands}}}"""
    get = lambda cdid: dict(ons.fetch(cdid, "LMS", "Q")["obs"])  # noqa: E731
    cells = {}
    for key, (rate_id, level_id) in CELLS.items():
        rate, level = get(rate_id), get(level_id)
        cells[key] = {"emp": level,
                      "pop": {q: level[q] / rate[q] * 100 for q in level if rate.get(q)}}
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


def decompose(cells: dict, ages: list[str]) -> list[dict]:
    """Quarterly decomposition of the change in the employment rate vs the base year."""
    keys = [k for k in cells if k[1] in ages]
    quarters = sorted(set.intersection(*(set(cells[k]["pop"]) & set(cells[k]["emp"]) for k in keys)))

    def mix(q):
        total_pop = sum(cells[k]["pop"][q] for k in keys)
        share = {k: cells[k]["pop"][q] / total_pop for k in keys}
        rate = {k: cells[k]["emp"][q] / cells[k]["pop"][q] * 100 for k in keys}
        return share, rate

    base_qs = [q for q in quarters if q.startswith(BASE_YEAR)]
    mixes = [mix(q) for q in base_qs]
    s0 = {k: sum(m[0][k] for m in mixes) / len(mixes) for k in keys}
    e0 = {k: sum(m[1][k] for m in mixes) / len(mixes) for k in keys}
    rate0 = sum(s0[k] * e0[k] for k in keys)

    out = []
    for q in quarters:
        if q < START:
            continue
        s, e = mix(q)
        comp = {k: (s[k] - s0[k]) * ((e0[k] + e[k]) / 2 - rate0) for k in keys}
        within = {k: (e[k] - e0[k]) * (s0[k] + s[k]) / 2 for k in keys}
        out.append({
            "date": q,
            "actual": round(sum(s[k] * e[k] for k in keys), 2),
            "fixed_mix": round(sum(s0[k] * e[k] for k in keys), 2),   # today's rates, 2019 population mix
            "change": round(sum(s[k] * e[k] for k in keys) - rate0, 2),
            "composition": round(sum(comp.values()), 2),
            "within": round(sum(within.values()), 2),
            "_within_by_group": {f"{k[0]} {k[1]}": round(v, 3) for k, v in within.items()},
            "_composition_by_group": {f"{k[0]} {k[1]}": round(v, 3) for k, v in comp.items()},
        })
    return out


def workings(cells: dict, ages: list[str], quarter: str) -> list[dict]:
    """Group-by-group calculation for one quarter vs the base year (for checking by hand)."""
    keys = [k for k in cells if k[1] in ages]
    base_qs = [q for q in cells[keys[0]]["pop"] if q.startswith(BASE_YEAR)]

    def share_rate(q):
        tot = sum(cells[k]["pop"][q] for k in keys)
        return ({k: cells[k]["pop"][q] / tot * 100 for k in keys},
                {k: cells[k]["emp"][q] / cells[k]["pop"][q] * 100 for k in keys})

    base = [share_rate(q) for q in base_qs]
    s0 = {k: sum(b[0][k] for b in base) / len(base) for k in keys}
    e0 = {k: sum(b[1][k] for b in base) / len(base) for k in keys}
    st, et = share_rate(quarter)
    rate0 = sum(s0[k] * e0[k] for k in keys) / 100
    rows = []
    for k in keys:
        rows.append({
            "group": f"{k[0]} {k[1]}",
            "pop_share_2019_%": round(s0[k], 2), f"pop_share_{quarter}_%": round(st[k], 2),
            "emp_rate_2019_%": round(e0[k], 1), f"emp_rate_{quarter}_%": round(et[k], 1),
            "composition_pp": round((st[k] - s0[k]) / 100 * ((e0[k] + et[k]) / 2 - rate0), 3),
            "within_pp": round((et[k] - e0[k]) * (s0[k] + st[k]) / 2 / 100, 3),
        })
    return rows


def chart(slug: str, title: str, units: str, kind: str, series: list[dict], data: list[dict], note: str) -> dict:
    return {"slug": slug, "category": "labour-markets", "title": title, "type": kind, "freq": "Q",
            "units": units, "source": SOURCE, "note": note, "series": series,
            "data_through": data[-1]["date"] if data else None, "status": "ok", "data": data}


def build() -> list[Path]:
    cells = fetch_cells()
    written = []
    for ages, label, slug in [(AGES, "aged 16 and over", "16plus"), (AGES[:-1], "aged 16-64", "16-64")]:
        rows = decompose(cells, ages)
        last = rows[-1]
        note = (f"Groups: men and women by age band. Base = {BASE_YEAR} average. "
                "Midpoint (Shapley) weights, so composition + within-group = total change exactly.")
        line = chart(f"emp-composition-{slug}", f"Employment rate {label}: actual vs 2019 population mix",
                     "%", "line",
                     [{"key": "actual", "label": "Actual"},
                      {"key": "fixed_mix", "label": "Holding the age/sex mix at 2019"}],
                     [{k: r[k] for k in ("date", "actual", "fixed_mix")} for r in rows], note)
        decomp = chart(f"emp-decomposition-{slug}",
                       f"Change in the employment rate {label} since {BASE_YEAR}: composition vs within-group",
                       "Percentage points", "stacked-bar",
                       [{"key": "composition", "label": "Composition (age/sex mix)"},
                        {"key": "within", "label": "Within-group employment rates"},
                        {"key": "change", "label": "Total change", "mark": "line"}],
                       [{k: r[k] for k in ("date", "composition", "within", "change")}
                        for r in rows if r["date"] >= f"{BASE_YEAR}-Q1"], note)
        groups = [{"group": g, "within": last["_within_by_group"][g],
                   "composition": last["_composition_by_group"][g]} for g in last["_within_by_group"]]
        by_group = chart(f"emp-within-by-group-{slug}",
                         f"Contributions to the change in the employment rate {label}, {BASE_YEAR} to {last['date'].replace('-', ' ')}",
                         "Percentage points", "grouped-hbar",
                         [{"key": "Men", "label": "Men"}, {"key": "Women", "label": "Women"}],
                         [{"date": a,
                           "Men": next(g["within"] for g in groups if g["group"] == f"Men {a}"),
                           "Women": next(g["within"] for g in groups if g["group"] == f"Women {a}")}
                          for a in ages],
                         note + " Within-group contributions only: each group's rate change "
                                "weighted by its population share.")
        for c in (line, decomp, by_group):
            js, png = DATA / f"{c['slug']}.json", IMG / f"{c['slug']}.png"
            c["theme"] = charts.DEFAULT_THEME  # so a theme change also triggers a re-render
            text = json.dumps(c, indent=1) + "\n"
            # re-render only when the data changed: PNG bytes vary slightly between
            # machines, and an unchanged chart shouldn't produce a daily commit
            if png.exists() and js.exists() and js.read_text() == text:
                continue
            js.write_text(text)
            written.append(charts.render(c, png))
        rows_w = workings(cells, ages, last["date"])
        with (DATA / f"emp-composition-workings-{slug}.csv").open("w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows_w[0]))
            wr.writeheader()
            wr.writerows(rows_w)
        print(f"[composition] {label}: {last['date']} change {last['change']:+.2f}pp = "
              f"composition {last['composition']:+.2f} + within {last['within']:+.2f}")
    return written


if __name__ == "__main__":
    build()
