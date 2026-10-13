"""Eurostat Comext: EU member states' trade by HS6 product and partner country.

Dataset DS-045409 ("EU trade since 1988 by HS2-4-6 and CN8"), through the Comext
dissemination API. No key needed. Values are in euros, on the EU's "community
concept" (goods cleared through a country's customs count as its trade).
"""

from __future__ import annotations

import urllib.error
import urllib.parse

from .http import get_json

API = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/ds-045409"
FLOWS = {"1": "imports", "2": "exports"}


def _query(reporter: str, hs6: list[str], years: list[str]) -> dict[tuple[str, str, str, str], float]:
    params = [("format", "JSON"), ("lang", "en"), ("freq", "A"), ("reporter", reporter),
              ("flow", "1"), ("flow", "2"), ("indicators", "VALUE_IN_EUROS")]
    params += [("product", c) for c in hs6] + [("time", y) for y in years]
    d = get_json(f"{API}?{urllib.parse.urlencode(params)}", timeout=300)
    dims, size = d["id"], d["size"]
    # JSON-stat: one flat index over all dimensions, last dimension fastest
    cats = {k: {i: c for c, i in d["dimension"][k]["category"]["index"].items()} for k in dims}
    strides, s = [], 1
    for n in reversed(size):
        strides.insert(0, s)
        s *= n
    out: dict = {}
    for flat, v in d["value"].items():
        pos = {k: (int(flat) // strides[i]) % size[i] for i, k in enumerate(dims)}
        key = (FLOWS[cats["flow"][pos["flow"]]], cats["product"][pos["product"]],
               cats["partner"][pos["partner"]], cats["time"][pos["time"]])
        out[key] = out.get(key, 0.0) + v
    return out


def annual(reporter: str, hs6: list[str], years: list[str], chunk: int = 15) -> dict[tuple[str, str, str, str], float]:
    """{(flow, hs6, partner, year): €} for one reporting country (e.g. "NL"), imports and
    exports, every partner, including aggregates such as WORLD and EXT_EU27_2020 (callers
    filter those). Codes are fetched `chunk` at a time to keep responses small. A year
    Eurostat hasn't published yet is dropped (latest first) rather than failing."""
    years = list(years)
    while years:
        try:
            out: dict = {}
            for i in range(0, len(hs6), chunk):
                out.update(_query(reporter, hs6[i:i + chunk], years))
            return out
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404) or len(years) == 1:
                raise
            years = years[:-1]   # most likely the latest year isn't out yet
    return {}
