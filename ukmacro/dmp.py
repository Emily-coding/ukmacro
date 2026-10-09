"""Decision Maker Panel (Bank of England / Nottingham / Stanford) client.

The DMP publishes monthly and quarterly spreadsheets on its data page; links change
with each release, so the newest file is found by scanning the page. The quarterly
file holds the investment questions.
"""

from __future__ import annotations

import io
import re

import openpyxl

from .http import get, get_text

DATA_PAGE = "https://www.decisionmakerpanel.co.uk/data/"


def latest_file(kind: str = "quarterly") -> str:
    """URL of the newest '<kind>-dmp-data-<month>-<year>.xlsx' on the data page
    (the page lists newest first)."""
    links = re.findall(r'href="([^"]+/' + kind + r'-dmp-data-[^"]+\.xlsx)"', get_text(DATA_PAGE))
    if not links:
        raise LookupError(f"no {kind} DMP data file linked from {DATA_PAGE}")
    return links[0]


def table_row(sheet: str, code: str, row_label: str, kind: str = "quarterly") -> dict[str, float]:
    """One row of one numbered table, by period: e.g. sheet 'Investment', code 'C.2b'
    (average expected capex growth over the next year), row 'Total' -> {'2026-Q1': 0.49, ...}."""
    url = latest_file(kind)
    wb = openpyxl.load_workbook(io.BytesIO(get(url, timeout=120)), read_only=True, data_only=True)
    rows = list(wb[sheet].iter_rows(values_only=True))
    start = next(i for i, r in enumerate(rows) if r and str(r[0] or "").strip() == code)
    periods = next(r for r in rows[start:] if r and str(r[1] or "").startswith("Period data refer to"))
    target = next(r for r in rows[start:] if r and str(r[1] or "").strip() == row_label)
    out = {}
    for p, v in zip(periods[2:], target[2:]):
        m = re.match(r"(\d{4})\s*Q([1-4])", str(p or ""))
        if m and isinstance(v, (int, float)):
            out[f"{m.group(1)}-Q{m.group(2)}"] = float(v)
    if not out:
        raise ValueError(f"DMP {sheet} {code} {row_label!r}: no values found")
    return out
