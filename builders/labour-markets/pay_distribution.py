"""Pay at the 10th, 50th and 90th percentiles: UK (HMRC PAYE RTI) vs US (BLS CPS).

The two most current sources of pay by percentile, but they measure different things:
  UK  RTI monthly pay of all payrolled employees, full and part time, from tax
      records; seasonally adjusted, three-month moving averages. No hours, so no
      hourly pay. Converted to weekly as monthly x 12 / 52.
  US  CPS usual weekly earnings of full-time wage and salary workers, from the
      household survey; quarterly, seasonally adjusted (BLS, via FRED).
Because RTI includes part-timers, its lower percentiles are far below a full-time
measure, so the levels can't be compared directly. The charts compare growth since
2019 instead, in cash terms and after consumer price inflation (UK CPI, US CPI-U).
"""

from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

import composition as lfs  # noqa: E402
import composition_rti as rti  # noqa: E402
import openpyxl  # noqa: E402
from ukmacro import ons  # noqa: E402
from ukmacro.http import get, get_text  # noqa: E402

RTI_SHEET = "5. Pay distribution (UK)"
PERCENTILES = {"p10": ("10th percentile", "10th percentile"),
               "p50": ("50th percentile", "Median"),
               "p90": ("90th percentile", "90th percentile")}   # key: (RTI column, label)
# FRED copies of BLS series LEU0252911200, LEU0252881500, LEU0252911500 (quarterly)
US_SERIES = {"p10": "LEU0252911200Q", "p50": "LEU0252881500Q", "p90": "LEU0252911500Q"}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
BASE_YEAR = "2019"
SOURCE = ("HMRC PAYE Real Time Information (ONS); BLS Current Population Survey via FRED; "
          "ONS CPI; BLS CPI-U; ukmacro calculations")
NOTE = ("UK: monthly pay of all payrolled employees (full and part time), HMRC PAYE RTI. "
        "US: usual weekly earnings of full-time wage and salary workers, CPS. Both seasonally "
        "adjusted. Coverage differs, so compare growth, not levels.")


def _quarter(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def fetch_uk() -> dict[str, dict[str, float]]:
    """{key: {'YYYY-Qn': £ per week}}. RTI's figures are three-month moving averages,
    so the quarter's last month is the quarter average."""
    link = re.search(r'/file\?uri=[^"]+\.xlsx', get_text(rti.RTI_PAGE)).group(0)
    wb = openpyxl.load_workbook(io.BytesIO(get("https://www.ons.gov.uk" + link, timeout=180)),
                                read_only=True, data_only=True)
    rows = list(wb[RTI_SHEET].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Date")
    cols = {k: [str(h).strip() for h in rows[hi]].index(col) for k, (col, _) in PERCENTILES.items()}
    out: dict[str, dict[str, float]] = {k: {} for k in PERCENTILES}
    for r in rows[hi + 1:]:
        m = re.match(r"([A-Za-z]+) (\d{4})", str(r[0] or "").strip())
        if not m or m.group(1).lower() not in rti.MONTHS:
            continue
        month = rti.MONTHS.index(m.group(1).lower()) + 1
        if month % 3:
            continue
        for k, j in cols.items():
            out[k][f"{m.group(2)}-Q{month // 3}"] = float(r[j]) * 12 / 52
    return out


def _fred(series_id: str) -> dict[str, float]:
    """A FRED series as {'YYYY-Qn': value}, monthly values averaged over complete quarters."""
    by: dict[str, list[float]] = {}
    for row in list(csv.reader(io.StringIO(get_text(FRED.format(series_id)))))[1:]:
        if row[1] not in ("", "."):
            by.setdefault(_quarter(row[0]), []).append(float(row[1]))
    # a quarterly series has one value a quarter; a monthly one needs at least two months
    # (US CPI for October 2025 was never collected, because of the federal shutdown)
    n = min(2, max(len(v) for v in by.values()))
    return {q: sum(v) / len(v) for q, v in by.items() if len(v) >= n}


def fetch_prices() -> dict[str, dict[str, float]]:
    """Consumer price indices by quarter: UK CPI (ONS D7BT), US CPI-U (CPIAUCSL)."""
    uk = {d: v for d, v in ons.fetch("D7BT", "MM23", "Q")["obs"]}
    return {"uk": uk, "us": _fred("CPIAUCSL")}


def _base(s: dict[str, float]) -> float:
    vals = [v for q, v in s.items() if q.startswith(BASE_YEAR)]
    return sum(vals) / len(vals)


def build() -> None:
    pay = {"uk": fetch_uk(), "us": {k: _fred(s) for k, s in US_SERIES.items()}}
    cpi = fetch_prices()
    def since_base(qs) -> list[str]:
        return sorted(q for q in qs if q >= f"{BASE_YEAR}-Q1")

    # the US CPS has no 2025 Q4: October 2025 wasn't surveyed during the federal shutdown
    own = {c: since_base(set.intersection(*(set(s) for s in pay[c].values()))) for c in pay}
    quarters = since_base(set(own["uk"]) & set(own["us"]) & set(cpi["uk"]) & set(cpi["us"]))
    latest = quarters[-1]

    # 1. cash pay by percentile, 2019 = 100, one chart per country
    for c, name, desc in (("uk", "UK", "monthly pay, all payrolled employees (RTI)"),
                          ("us", "US", "weekly earnings, full-time workers (CPS)")):
        bases = {k: _base(pay[c][k]) for k in PERCENTILES}
        lfs.publish(lfs.chart(
            f"pay-percentiles-{c}", f"{name} pay by percentile, {desc}",
            f"Index, {BASE_YEAR} = 100 (cash terms)", "line",
            [{"key": k, "label": lab} for k, (_, lab) in PERCENTILES.items()],
            [{"date": q, **{k: round(100 * pay[c][k][q] / bases[k], 2) for k in PERCENTILES}}
             for q in own[c]], NOTE + (" No 2025 Q4: the CPS wasn't collected in October 2025 "
                                       "(federal shutdown)." if c == "us" else ""), source=SOURCE))

    # 2. growth since 2019 by percentile, UK vs US, in cash and real terms
    def growth(c: str, k: str, real: bool) -> float:
        g = pay[c][k][latest] / _base(pay[c][k])
        if real:
            g /= cpi[c][latest] / _base(cpi[c])
        return round(100 * (g - 1), 1)

    series = [{"key": "uk_cash", "label": "UK, cash"}, {"key": "us_cash", "label": "US, cash"},
              {"key": "uk_real", "label": "UK, after inflation"},
              {"key": "us_real", "label": "US, after inflation"}]
    rows = [{"date": lab, **{s["key"]: growth(s["key"][:2], k, s["key"].endswith("real")) for s in series}}
            for k, (_, lab) in PERCENTILES.items()]
    q = latest.replace("-", " ")
    lfs.publish(lfs.chart(
        "pay-percentiles-uk-vs-us", f"Pay growth by percentile, {BASE_YEAR} to {q}: UK vs US",
        f"% change since {BASE_YEAR} average", "grouped-hbar", series, rows,
        NOTE + " Deflated by UK CPI and US CPI-U.", source=SOURCE) | {"decimals": 1})

    # workings: levels (£ or $ per week), indices and prices
    lfs.write_csv([{"quarter": q, **{f"{c}_{k}_per_week": round(pay[c][k][q], 1)
                                     for c in pay for k in PERCENTILES},
                    "uk_cpi": cpi["uk"][q], "us_cpi": round(cpi["us"][q], 3)} for q in quarters],
                  lfs.DATA / "pay-percentiles-workings.csv")
    for r in rows:
        print(f"[pay-percentiles] {r['date']:16s} " + "  ".join(f"{s['label']} {r[s['key']]:+.1f}%" for s in series))


if __name__ == "__main__":
    build()
