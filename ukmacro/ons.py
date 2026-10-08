"""ONS time series client.

ONS series are identified by a four-letter CDID (e.g. ABMI = real GDP) plus the
dataset they are published in (e.g. QNA). The JSON endpoint is

    https://www.ons.gov.uk/<topic path>/timeseries/<cdid>/<dataset>/data

and the topic path is required — a wrong path 404s. We look the path up once via
the ONS search API and cache it in `ons_uris.json` (committed), so routine builds
never depend on search.

Dates are normalised to "YYYY" / "YYYY-Qn" / "YYYY-MM" so they line up with OECD.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .http import get_json

SEARCH = "https://api.beta.ons.gov.uk/v1/search?q={cdid}&content_type=timeseries&limit=50"
DATA = "https://www.ons.gov.uk{uri}/data"
URI_CACHE = Path(__file__).with_name("ons_uris.json")

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
FREQ_KEY = {"A": "years", "Q": "quarters", "M": "months"}


def _load_cache() -> dict:
    return json.loads(URI_CACHE.read_text()) if URI_CACHE.exists() else {}


def resolve_uri(cdid: str, dataset: str) -> str:
    """Return the site path for CDID/dataset, using the cache or the search API."""
    key = f"{cdid.upper()}/{dataset.upper()}"
    cache = _load_cache()
    if key in cache:
        return cache[key]
    items = get_json(SEARCH.format(cdid=cdid.lower()))["items"]
    hits = [i for i in items
            if i.get("cdid", "").upper() == cdid.upper()
            and i.get("dataset_id", "").upper() == dataset.upper()]
    if not hits:
        found = sorted({f"{i.get('cdid')}/{i.get('dataset_id')}" for i in items})
        raise LookupError(f"ONS series {key} not found; search returned {found[:10]}")
    cache[key] = hits[0]["uri"]
    URI_CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=1) + "\n")
    return cache[key]


def _norm_date(raw: str, freq: str) -> str:
    raw = raw.strip()
    if freq == "A":
        return raw
    year, part = raw.split()
    if freq == "Q":
        return f"{year}-{part}"              # "2026 Q2" -> "2026-Q2"
    return f"{year}-{MONTHS[part.upper()[:3]]:02d}"  # "2026 JUL" -> "2026-07"


def _parse_release(text: str | None) -> str | None:
    """'12 November 2026' -> '2026-11-12'; ONS sometimes leaves this blank."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def fetch(cdid: str, dataset: str, freq: str) -> dict:
    """Fetch one series. Returns {'obs': [(date, value)], 'title', 'next_release', 'url'}."""
    uri = resolve_uri(cdid, dataset)
    raw = get_json(DATA.format(uri=uri))
    rows = raw.get(FREQ_KEY[freq]) or []
    obs = []
    for r in rows:
        v = (r.get("value") or "").strip()
        if v in ("", "x", ".."):  # ONS suppression / not-available markers
            continue
        obs.append((_norm_date(r["date"], freq), float(v)))
    if not obs:
        raise ValueError(f"ONS {cdid}/{dataset} has no {FREQ_KEY[freq]} observations")
    desc = raw.get("description", {})
    return {
        "obs": obs,
        "title": desc.get("title"),
        "next_release": _parse_release(desc.get("nextRelease")),
        "url": "https://www.ons.gov.uk" + uri,
    }
