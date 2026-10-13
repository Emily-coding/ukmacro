"""UN Comtrade: countries' goods trade by HS6 product and partner, as each reports it.

Uses the public preview API (no key). It allows one period per request, returns at most
500 rows and is rate-limited, so requests are made one product at a time and spaced
out. Values are in US dollars.
"""

from __future__ import annotations

import time

from .http import get_json

API = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
REFERENCE = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"
_ISO2: dict[int, str] = {}


def partner_iso2() -> dict[int, str]:
    """Comtrade partner code -> ISO two-letter code; 0 = "WORLD". Comtrade records
    Taiwan as "Other Asia, nes" (490), which is mapped to "TW"."""
    if not _ISO2:
        for p in get_json(REFERENCE, timeout=60)["results"]:
            if p.get("PartnerCodeIsoAlpha2"):
                _ISO2[p["PartnerCode"]] = p["PartnerCodeIsoAlpha2"]
        _ISO2[0], _ISO2[490] = "WORLD", "TW"
    return _ISO2


def annual(reporter: int, hs6: list[str], year: str, pause: float = 6.0) -> dict[tuple[str, str, str, str], float]:
    """{(flow, hs6, partner ISO2 or "WORLD", year): $} for one reporter (M49 code, e.g.
    842 = US), imports and exports, every partner. Unknown partner codes are dropped."""
    iso2 = partner_iso2()
    out: dict = {}
    for flow_code, flow in (("M", "imports"), ("X", "exports")):
        for code in hs6:
            d = get_json(f"{API}?reporterCode={reporter}&flowCode={flow_code}&period={year}&cmdCode={code}"
                         "&partner2Code=0&customsCode=C00&motCode=0", timeout=120)
            for r in d.get("data", []):
                p = iso2.get(r["partnerCode"])
                if p:
                    key = (flow, code, p, year)
                    out[key] = out.get(key, 0.0) + (r["primaryValue"] or 0)
            time.sleep(pause)   # stay under the preview's rate limit
    return out
