"""HMRC uktradeinfo API client (OData, keyless).

Overseas Trade Statistics (OTS) give monthly goods trade by 8-digit CN commodity
code and partner country — the planned source for critical minerals. Lookups for
codes and countries are separate endpoints (/Commodity, /Country).
Docs: https://www.uktradeinfo.com/api-documentation/
"""

from __future__ import annotations

import urllib.parse

from .http import get_json

BASE = "https://api.uktradeinfo.com"


def query(entity: str, filter: str, top: int | None = None) -> list[dict]:
    """Run an OData query, following @odata.nextLink pages."""
    params = {"$filter": filter}
    if top:
        params["$top"] = str(top)
    url = f"{BASE}/{entity}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
    rows: list[dict] = []
    while url:
        page = get_json(url)
        rows.extend(page.get("value", []))
        url = page.get("@odata.nextLink") if not top else None
    return rows


def ots(commodity_id: int, month_from: int, month_to: int) -> list[dict]:
    """Trade rows for one CN8 code between two YYYYMM months (inclusive).
    FlowTypeId: 1/3 = EU/non-EU imports, 2/4 = EU/non-EU exports."""
    return query("OTS", f"CommodityId eq {commodity_id} and MonthId ge {month_from} and MonthId le {month_to}")
