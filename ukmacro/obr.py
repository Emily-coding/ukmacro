"""OBR client. The OBR has no API: files are spreadsheets linked from
https://obr.uk/data/ as stable `https://obr.uk/download/<slug>/` URLs, and slugs
change with every forecast (e.g. march-2026-economic-and-fiscal-outlook-...).

So we list the download links on the data page and match on a pattern, then save
each new file under its slug — never overwrite an old vintage.
"""

from __future__ import annotations

import re
from pathlib import Path

from .http import get, get_text

DATA_PAGE = "https://obr.uk/data/"
LINK = re.compile(r'href="(https://obr\.uk/download/([a-z0-9-]+)/)[^"]*"')


def download_links(page: str = DATA_PAGE) -> dict[str, str]:
    """Return {slug: url} for every /download/ link on the page."""
    return {slug: url for url, slug in LINK.findall(get_text(page))}


def find(pattern: str, page: str = DATA_PAGE) -> dict[str, str]:
    """Download links whose slug matches a regex, e.g. 'historical-official-forecasts'."""
    rx = re.compile(pattern)
    return {s: u for s, u in download_links(page).items() if rx.search(s)}


def save_new(pattern: str, dest: Path, suffix: str = ".xlsx") -> list[Path]:
    """Download any matching file not already in `dest`. Returns the new paths."""
    dest.mkdir(parents=True, exist_ok=True)
    new = []
    for slug, url in find(pattern).items():
        path = dest / f"{slug}{suffix}"
        if not path.exists():
            path.write_bytes(get(url))
            new.append(path)
    return new


# ---------------------------------------------------------------- historical forecasts

def historical_forecasts(sheet: str) -> dict[str, dict[int, float]]:
    """One variable from the OBR's Historical official forecasts database: every
    forecast (EFO) vintage's annual figures, {'March 2026': {2024: 2.5, 2025: 4.3, ...}}.

    Sheets are named by variable (e.g. 'Businessinv', 'UKGDP'); rows are forecast
    vintages, columns are years. The database's own 'Outturn data' row is left out:
    use current ONS data for outturns.
    """
    import io

    import openpyxl

    url = find("historical-official-forecasts-database")
    if not url:
        raise LookupError("OBR historical forecasts database link not found on the data page")
    wb = openpyxl.load_workbook(io.BytesIO(get(next(iter(url.values())), timeout=180)),
                                read_only=True, data_only=True)
    rows = list(wb[sheet].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and sum(str(c).isdigit() for c in r if c) > 5)
    years = {j: int(c) for j, c in enumerate(rows[hi]) if str(c or "").isdigit()}
    out = {}
    for r in rows[hi + 1:]:
        label = str(r[0] or "").strip() if r else ""
        if not re.match(r"^[A-Z][a-z]+ \d{4}$", label):  # vintages look like "March 2026"
            continue
        vals = {y: float(r[j]) for j, y in years.items() if j < len(r) and isinstance(r[j], (int, float))}
        if vals:
            out[label] = vals
    if not out:
        raise ValueError(f"OBR sheet {sheet!r}: no forecast vintages found")
    return out
