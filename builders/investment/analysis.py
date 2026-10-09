"""Business investment analyses (charts beyond plotting a single series).

1. investment-asset-contributions
   Which assets drove the change in business investment since 2019 Q4. Each asset's
   contribution = (asset now - asset in 2019 Q4) / business investment in 2019 Q4,
   in % points. The four assets add up to business investment to within about 0.2%
   (chained volume measures aren't exactly additive), so the bars sum to the total
   change to within a fraction of a point.

2. investment-obr-forecasts
   Each spring OBR forecast's path for business investment against the outturn, as an
   index (2019 = 100). The OBR publishes forecasts as annual growth rates. A forecast made
   in year Y starts from today's ONS outturn for year Y-1, and its growth rates for Y
   onwards are chained on. (Its figures for earlier years were estimates of the past at
   the time, so they are not used.) Each line therefore starts on the outturn, and the
   gap that opens up is the forecast error in growth, separate from later data revisions.

3. investment-dmp-expectations
   Firms' expected growth in their capital spending over the next year (Decision Maker
   Panel), plotted at the quarter the expectation refers to (four quarters after the
   survey), next to actual year-on-year growth in business investment (ONS). The DMP is
   firms' own nominal spending; the ONS series is the real national total. So compare
   direction and turning points, not levels.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from ukmacro import charts, dmp, obr, ons  # noqa: E402

DATA = REPO / "data" / "investment"
IMG = REPO / "img" / "investment"
BASE_Q = "2019-Q4"          # pre-pandemic base quarter (as in the headline investment charts)
BASE_YEAR = 2019            # base year for the annual OBR comparison
FIRST_VINTAGE_YEAR = 2020   # spring forecasts from this year on are shown

ASSETS = {  # key: (label, CDID in the CXNV dataset)
    "ipp": ("Intellectual property", "EDRA"),
    "buildings": ("Buildings and structures", "EDQZ"),
    "ict_machinery": ("ICT and machinery", "EDOP"),
    "transport": ("Transport equipment", "EDOH"),
}


def chart(slug, title, units, kind, freq, series, data, source, note) -> dict:
    """A chart in the repo's common JSON format (see ukmacro/charts.py)."""
    return {"slug": slug, "category": "investment", "title": title, "type": kind, "freq": freq,
            "units": units, "source": source, "note": note, "series": series,
            "data_through": data[-1]["date"] if data else None, "status": "ok", "data": data}


def publish(c: dict) -> None:
    charts.publish(c, DATA / f"{c['slug']}.json", IMG / f"{c['slug']}.png")


def quarterly(cdid: str, dataset: str = "CXNV") -> dict[str, float]:
    return dict(ons.fetch(cdid, dataset, "Q")["obs"])


# ---------------------------------------------------------------- 1. asset contributions

def asset_contributions() -> None:
    bi = quarterly("NPEL")
    assets = {k: quarterly(cdid) for k, (_, cdid) in ASSETS.items()}
    base = bi[BASE_Q]
    quarters = [q for q in sorted(bi) if q >= "2019-Q1" and all(q in a for a in assets.values())]
    data = [{"date": q,
             **{k: round((a[q] - a[BASE_Q]) / base * 100, 2) for k, a in assets.items()},
             "total": round((bi[q] / base - 1) * 100, 2)} for q in quarters]
    publish(chart(
        "investment-asset-contributions",
        f"Change in business investment since {BASE_Q.replace('-', ' ')}, by asset",
        f"% points of {BASE_Q.replace('-', ' ')} business investment", "stacked-bar", "Q",
        [{"key": k, "label": label} for k, (label, _) in ASSETS.items()]
        + [{"key": "total", "label": "Total change", "mark": "line"}],
        data, "ONS Business investment (non-government investment by asset); ukmacro calculations",
        "Chained volume measures, seasonally adjusted. Each bar is the change in that asset's "
        f"investment as a share of {BASE_Q.replace('-', ' ')} business investment. Chained "
        "volumes aren't exactly additive, so bars can differ from the total by a fraction of a point."))
    last = data[-1]
    print(f"[investment] asset contributions {last['date']}: total {last['total']:+.1f}% = "
          + ", ".join(f"{k} {last[k]:+.1f}" for k in ASSETS))


# ---------------------------------------------------------------- 2. OBR forecasts vs outturn

def obr_forecasts() -> None:
    vintages = obr.historical_forecasts("Businessinv")
    actual = dict(ons.fetch("NPEL", "QNA", "A")["obs"])  # complete years only
    actual = {int(y): v for y, v in actual.items()}
    index = {y: v / actual[BASE_YEAR] * 100 for y, v in actual.items()}

    # spring forecasts since FIRST_VINTAGE_YEAR, plus the latest if it's an autumn one
    names = [n for n in vintages if n.startswith("March") and int(n[-4:]) >= FIRST_VINTAGE_YEAR]
    latest = list(vintages)[-1]
    if latest not in names:
        names.append(latest)

    paths = {}
    for name in names:
        made = int(name[-4:])  # the year the forecast was published
        if made - 1 not in index:
            continue  # no outturn yet to start from
        level, path = index[made - 1], {made - 1: index[made - 1]}
        for y in sorted(g for g in vintages[name] if g >= made):
            level *= 1 + vintages[name][y] / 100
            path[y] = level
        paths[name] = path

    years = range(2016, max(max(p) for p in paths.values()) + 1)
    key = lambda n: n.lower().replace(" ", "_")  # noqa: E731
    data = [{"date": str(y), "outturn": round(index[y], 1) if y in index else None,
             **{key(n): round(p[y], 1) if y in p else None for n, p in paths.items()}} for y in years]
    # outturn in colour 1, the latest forecast in colour 2, older forecasts grey (labelled by name)
    series = [{"key": "outturn", "label": "Outturn (ONS, latest data)"},
              {"key": key(latest), "label": f"OBR {latest}", "slot": 1}]
    series += [{"key": key(n), "label": n, "color": "neutral"} for n in reversed(names) if n != latest]
    publish(chart(
        "investment-obr-forecasts", "Business investment: OBR forecasts vs outturn",
        f"Index, {BASE_YEAR} = 100", "line", "A", series, data,
        "OBR Historical official forecasts database; ONS Business investment; ukmacro calculations",
        "A forecast made in year Y starts from today's ONS outturn for Y-1 and applies the OBR's "
        "growth rates from Y onwards, so the gap from the outturn is the error in forecast growth "
        "(separate from later data revisions). Grey lines are earlier spring forecasts."))
    print(f"[investment] OBR forecasts: {len(paths)} vintages, latest {latest}")


# ---------------------------------------------------------------- 3. DMP expectations

def dmp_expectations() -> None:
    expected = dmp.table_row("Investment", "C.2b", "Total")  # by survey reference quarter

    def shift_year(q, n):  # the same quarter n years later ('2025-Q3', 1 -> '2026-Q3')
        return f"{int(q[:4]) + n}-{q[5:]}"

    bi = quarterly("NPEL")
    actual = {q: (v / bi[shift_year(q, -1)] - 1) * 100 for q, v in bi.items() if shift_year(q, -1) in bi}
    exp_at = {shift_year(q, 1): v for q, v in expected.items()}  # plotted at the quarter it refers to
    quarters = sorted(q for q in set(actual) | set(exp_at) if q >= "2018-Q1")
    data = [{"date": q, "actual": round(actual[q], 1) if q in actual else None,
             "expected": round(exp_at[q], 1) if q in exp_at else None} for q in quarters]
    publish(chart(
        "investment-dmp-expectations", "Business investment growth: firms' expectations vs outturn",
        "% change on a year earlier", "line", "Q",
        [{"key": "actual", "label": "Actual business investment growth (ONS)"},
         {"key": "expected", "label": "Firms' expected capital spending growth a year earlier (DMP)"}],
        data, "Decision Maker Panel; ONS Business investment; ukmacro calculations",
        "DMP: average expected growth in firms' own capital spending over the next year, plotted at "
        "the quarter it refers to. It is nominal and firm-level; ONS is the real national total, so "
        "compare direction and turning points rather than levels."))
    print(f"[investment] DMP: expectations through {max(exp_at)}, actual through {max(actual)}")


def build() -> None:
    asset_contributions()
    obr_forecasts()
    dmp_expectations()


if __name__ == "__main__":
    build()
