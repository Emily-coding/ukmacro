"""Nomis API client (keyless for modest use).

Nomis carries the Annual Population Survey (NM_17_5, rolling 12-month periods) and
other labour-market datasets with breakdowns ONS time series don't have — this is
the planned source for the age x sex composition work. Build a query at
https://www.nomisweb.co.uk/query, then use "Download data -> API link".
"""

from __future__ import annotations

import csv
import io
import urllib.parse

from .http import get_text

BASE = "https://www.nomisweb.co.uk/api/v01/dataset/{dataset}.data.csv?{query}"


def fetch(dataset: str, **params) -> list[dict]:
    """Return the CSV rows as dicts. Pass Nomis query params as keywords."""
    text = get_text(BASE.format(dataset=dataset, query=urllib.parse.urlencode(params)))
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError(f"Nomis {dataset} {params}: no rows")
    return rows
