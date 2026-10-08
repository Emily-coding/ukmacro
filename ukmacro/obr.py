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
