"""US: is weekly pay growth at the 10th, 50th and 90th percentiles more hours, or higher hourly pay?

From the CPS microdata (Census basic monthly public-use files, outgoing rotation groups,
the people asked about earnings). For full-time wage and salary workers, the same group
as BLS's published weekly earnings deciles, it finds each quarter's 10th, 50th and 90th
percentiles of usual weekly earnings, then the usual weekly hours (main job) of the people
within 2.5 percentiles either side of each. Weekly pay growth then splits into hours
growth and hourly pay growth (weekly pay / hours) for those people.

The microdata isn't seasonally adjusted, so growth is 2022 (four-quarter average) to the
latest four quarters. 2025 Q4 has only November and December: October 2025 wasn't
surveyed during the federal shutdown.

Not part of build.py: it downloads about 10MB per month of microdata (cached in
~/.cache/ukmacro/cps). Run it on its own:  python builders/labour-markets/us_hours.py
"""

from __future__ import annotations

import sys
import urllib.error
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import composition as lfs  # noqa: E402
from ukmacro.http import get  # noqa: E402

CACHE = Path.home() / ".cache" / "ukmacro" / "cps"
URL = "https://www2.census.gov/programs-surveys/cps/datasets/{y}/basic/{m}{yy}pub.zip"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
START = 2022
# (first, last) columns in the fixed-width file; the same in every layout 2022-2026
POS = {"HRMONTH": (16, 17), "HRYEAR4": (18, 21), "PEHRUSL1": (218, 219), "PEHRFTPT": (222, 223),
       "PEHRUSLT": (224, 226), "PEIO1COW": (432, 433), "PRERELG": (498, 499), "PTERNWA": (527, 534),
       "PWORWGT": (603, 612)}
PERCENTILES = {10: "10th percentile", 50: "Median", 90: "90th percentile"}
BAND = 0.025   # people within 2.5 percentiles either side
SOURCE = "US Census Bureau / BLS Current Population Survey microdata; ukmacro calculations"
NOTE = ("Full-time wage and salary workers (usually 35+ hours), outgoing rotation groups. "
        "Hours = usual weekly hours at the main job of people within 2.5 percentiles of each "
        "point of the weekly earnings distribution. Not seasonally adjusted.")


def download() -> list[Path]:
    """Every monthly file from START on, cached; months not published (or never
    collected, like October 2025) are skipped."""
    CACHE.mkdir(parents=True, exist_ok=True)
    today, out = date.today(), []
    for y in range(START, today.year + 1):
        for i, m in enumerate(MONTHS):
            if (y, i + 1) >= (today.year, today.month):
                break
            path = CACHE / f"{m}{y % 100:02d}pub.zip"
            if not path.exists():
                try:
                    path.write_bytes(get(URL.format(y=y, m=m, yy=f"{y % 100:02d}"), timeout=300, retries=1))
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise
                    continue
            out.append(path)
    return out


def earners(paths: list[Path]) -> pd.DataFrame:
    """Full-time wage and salary workers with weekly earnings, one row each."""
    frames = []
    for p in paths:
        with zipfile.ZipFile(p) as z:
            d = pd.read_fwf(z.open(z.namelist()[0]), colspecs=[(a - 1, b) for a, b in POS.values()],
                            names=list(POS), header=None)
        full_time = (d.PEHRUSLT >= 35) | ((d.PEHRUSLT == -4) & (d.PEHRFTPT == 1))  # -4 = hours vary
        frames.append(d[(d.PRERELG == 1) & d.PEIO1COW.between(1, 5) & (d.PTERNWA > 0) & full_time])
    d = pd.concat(frames)
    d["weekly"], d["weight"] = d.PTERNWA / 100, d.PWORWGT / 1e4   # implied decimals
    d["quarter"] = d.HRYEAR4.astype(str) + "-Q" + ((d.HRMONTH - 1) // 3 + 1).astype(str)
    return d


def quarter_stats(g: pd.DataFrame) -> dict[str, float]:
    """Weekly earnings at each percentile, and the hours and hourly pay of people near it."""
    order = np.argsort(g.weekly.values)
    cum = np.cumsum(g.weight.values[order]) / g.weight.sum()
    rank = np.empty_like(cum)
    rank[order] = cum
    out = {}
    for p in PERCENTILES:
        out[f"weekly_p{p}"] = float(np.interp(p / 100, cum, g.weekly.values[order]))
        near = g[(rank > p / 100 - BAND) & (rank <= p / 100 + BAND) & (g.PEHRUSL1 > 0)]
        out[f"hours_p{p}"] = float(np.average(near.PEHRUSL1, weights=near.weight))
        out[f"hourly_p{p}"] = float(np.average(near.weekly / near.PEHRUSL1, weights=near.weight))
    return out


def build() -> None:
    d = earners(download())
    stats = pd.DataFrame({q: quarter_stats(g) for q, g in d.groupby("quarter")}).T.sort_index()
    quarters = list(stats.index)
    base = stats.loc[[q for q in quarters if q.startswith(str(START))]].mean()
    latest4 = quarters[-4:]
    last = stats.loc[latest4].mean()
    period = f"{latest4[0].replace('-', ' ')} to {latest4[-1].replace('-', ' ')}"

    # 1. hours near each percentile, quarterly
    lfs.publish(lfs.chart(
        "us-hours-by-weekly-pay-percentile",
        "US full-time workers: usual weekly hours near each point of the weekly pay distribution",
        "Hours per week", "line",
        [{"key": f"p{p}", "label": lab} for p, lab in PERCENTILES.items()],
        [{"date": q, **{f"p{p}": round(stats.loc[q, f"hours_p{p}"], 2) for p in PERCENTILES}} for q in quarters],
        NOTE + " 2025 Q4 is November and December only (no October survey, federal shutdown).",
        source=SOURCE))

    # 2. weekly pay growth = hours growth + hourly pay growth (in logs, so the parts add up)
    def pct(k: str, p: int) -> float:
        return round(100 * np.log(last[f"{k}_p{p}"] / base[f"{k}_p{p}"]), 1)

    rows = [{"date": lab, "weekly": pct("weekly", p), "hours": pct("hours", p),
             "hourly": round(pct("weekly", p) - pct("hours", p), 1)} for p, lab in PERCENTILES.items()]
    lfs.publish(lfs.chart(
        "us-weekly-pay-hours-vs-hourly",
        f"US weekly pay growth by percentile, {START} to the year to {latest4[-1].replace('-', ' ')}: hours vs hourly pay",
        "Log % change (hours + hourly pay = weekly pay)", "grouped-hbar",
        [{"key": "weekly", "label": "Weekly pay"}, {"key": "hours", "label": "Usual hours"},
         {"key": "hourly", "label": "Hourly pay"}], rows,
        NOTE + f" {START} average vs the latest four quarters ({period}).", source=SOURCE) | {"decimals": 1})

    lfs.write_csv([{"quarter": q, **{k: round(v, 2) for k, v in stats.loc[q].items()}} for q in quarters],
                  lfs.DATA / "us-hours-by-weekly-pay-percentile.csv")
    for r in rows:
        print(f"[us-hours] {r['date']:16s} weekly {r['weekly']:+.1f}  hours {r['hours']:+.1f}  hourly {r['hourly']:+.1f}")


if __name__ == "__main__":
    build()
