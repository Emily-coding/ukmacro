"""OECD Data Explorer (SDMX REST) client — keyless.

A query is a dataflow id plus a dot-separated key, one slot per dimension, with
'+' to ask for several values and an empty slot as a wildcard. Easiest way to get
a key: build the table at https://data-explorer.oecd.org, then "Developer API".

We request one CSV for all countries at once (the API rate-limits per request) and
split it by REF_AREA.
"""

from __future__ import annotations

import csv
import io

from .http import get_text

BASE = "https://sdmx.oecd.org/public/rest/data/{flow}/{key}?startPeriod={start}&dimensionAtObservation=AllDimensions&format=csvfile"


def fetch(flow: str, key: str, start: str = "2000") -> dict[str, list[tuple[str, float]]]:
    """Return {REF_AREA: [(TIME_PERIOD, value), ...]} sorted by date."""
    text = get_text(BASE.format(flow=flow, key=key, start=start))
    out: dict[str, list[tuple[str, float]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        v = row.get("OBS_VALUE", "")
        if v == "":
            continue
        out.setdefault(row["REF_AREA"], []).append((row["TIME_PERIOD"], float(v)))
    if not out:
        raise ValueError(f"OECD {flow} {key}: no observations returned")
    return {area: sorted(obs) for area, obs in out.items()}
