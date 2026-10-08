"""Bank of England Interactive Statistical Database (IADB) client.

There is no JSON API; the database serves CSV from a download URL keyed by series
code (e.g. IUDBEDR = Bank Rate). It rejects requests without a browser-like
User-Agent, which `http.get` supplies. Find codes at
https://www.bankofengland.co.uk/boeapps/database/
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from .http import get_text

URL = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
       "?csv.x=yes&Datefrom={start}&Dateto=now&SeriesCodes={codes}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")


def fetch(codes: list[str], start: str = "01/Jan/2000") -> dict[str, list[tuple[str, float]]]:
    """Return {code: [(ISO date, value), ...]}. Dates are daily/monthly as published."""
    text = get_text(URL.format(start=start, codes=",".join(codes)))
    out: dict[str, list[tuple[str, float]]] = {c: [] for c in codes}
    for row in csv.DictReader(io.StringIO(text)):
        d = datetime.strptime(row["DATE"].strip(), "%d %b %Y").date().isoformat()
        for c in codes:
            v = (row.get(c) or "").strip()
            if v:
                out[c].append((d, float(v)))
    if not any(out.values()):
        raise ValueError(f"BoE {codes}: no observations (body starts {text[:120]!r})")
    return out
