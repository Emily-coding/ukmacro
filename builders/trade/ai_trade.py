"""AI-relevant trade: goods and services tiers (EU / non-EU) and a product layer.

Definitions (what is counted) live in definitions/ai_trade.yaml, built on the ONS AI
thematic account's product list (definitions/ai_cpa.yaml). Everything is an UPPER
BOUND: whole product groups containing AI and non-AI output.

1. Goods tiers: ONS MQ10, trade in goods by CPA, seasonally adjusted. Exact CPA codes,
   EU and non-EU ("rest of world"), current prices (CP) and chained volume measures
   (CVM). A tier's volume is the sum of its codes' CVM (chained volumes aren't exactly
   additive, so this is a close approximation); its price is CP / CVM.
2. Services tiers: ONS trade in services by broad type (QNA), EU / non-EU, CP and CVM,
   seasonally adjusted. Broad types only, so the tiers approximate the CPA ones.
3. Products: HMRC Overseas Trade Statistics for selected commodity codes, EU / non-EU,
   not seasonally adjusted. Values, quantities and value per unit; no official volumes.
   Products are goods: a narrow subset INSIDE the goods tiers, so the two are never added.
4. By country: services tiers and products by partner group (definitions/ai_trade.yaml
   `country_groups`), values only. Services: partner shares from the ONS by-country file
   applied to the latest QNA EU / non-EU totals. Products: HMRC. Both are charted as
   rolling four-quarter totals. Goods tiers stay EU / non-EU (no crosswalk).
   Products also come "origin-adjusted": imports recorded from EU distribution hubs
   (Netherlands, Belgium, Ireland) reassigned to likely origins using the hubs' own imports by
   origin (Eurostat Comext). An estimate, shown alongside the data as recorded.
Key AI dates (definitions/ai_events.yaml) are drawn as vertical lines on the charts.

All quarterly from 2016 Q1. Values in £m; volumes and prices as indices, 2019 = 100.

Outputs:
    data/trade/ai/ai_trade_tiers.csv      goods and services tiers, long format
    data/trade/ai/ai_trade_products.csv   product layer, long format
    data/trade/ai/ai_trade_by_country.csv services tiers and products by partner group
    data/trade/ai/ai_trade_by_country_rolling.csv  by-partner chart series, quarterly and rolling 4Q
    data/trade/ai/ai_products_summary.csv / .md   product changes 2019-2025 and ONS coverage
    data/trade/ai/ai_hardware_prices.csv  IMF basket prices: official implied prices, server unit values
    data/trade/ai/ai_hardware_components.csv  IMF basket by component, calendar years
    data/trade/ai/ai_top_partners.csv     top ten partners by AI product group, latest two years
    data/trade/ai/ai_hub_origins.csv      EU hubs: estimated made-in-hub share and top origins
    data/trade/ai/ai_chip_supply_chain.csv  an AI chip's supply chain in Dutch and Irish trade
    data/trade/ai/ai_stack.csv            AI stack: IMF basket, other AI products, rest of extended goods tier, AI services (values and volumes)
    data/trade/ai/<slug>.json + img/trade/ai/<slug>.png   charts
"""

from __future__ import annotations

import csv
import datetime
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from ukmacro import charts, comext, hmrc_trade, ons  # noqa: E402
from ukmacro.http import get_json, get_text  # noqa: E402

DEFS = yaml.safe_load((REPO / "definitions" / "ai_trade.yaml").read_text())
EVENTS = [{"date": str(e["date"]), "label": e["label"]}
          for e in yaml.safe_load((REPO / "definitions" / "ai_events.yaml").read_text())["events"]]
OUT = REPO / "data" / "trade" / "ai"
IMG = REPO / "img" / "trade" / "ai"
START = "2016-Q1"
BASE_YEAR = "2019"
MQ10_PAGE = ("https://www.ons.gov.uk/businessindustryandtrade/internationaltrade/datasets/"
             "uktradeingoodsbyclassificationofproductbyactivity")
HMRC_OTS = "https://api.uktradeinfo.com/OTS"
HMRC_COUNTRY = "https://api.uktradeinfo.com/Country"
SVC_PAGE = ("https://www.ons.gov.uk/businessindustryandtrade/internationaltrade/datasets/"
            "uktradeinservicesservicetypebypartnercountrynonseasonallyadjusted")
SVC_EU, SVC_WORLD = "B5", "W1"   # "Total EU27" and "World total" rows in the services file
FLOWS = {1: ("EU", "imports"), 2: ("EU", "exports"), 3: ("NonEU", "imports"), 4: ("NonEU", "exports")}
LINES = [("EU", "exports", "EU exports"), ("NonEU", "exports", "Non-EU exports"),
         ("EU", "imports", "EU imports"), ("NonEU", "imports", "Non-EU imports")]
UPPER_BOUND = ("Upper bound: whole product groups, which contain AI and non-AI products "
               "(ONS has not yet published AI shares). ")
ORIGIN_NOTE = ("Origin-adjusted: UK imports recorded from the Netherlands, Belgium and Ireland (EU "
               "distribution hubs; HMRC records EU imports by country of dispatch) are reassigned to likely countries "
               "of origin in proportion to those countries' own imports of the same products (Eurostat "
               "Comext). Goods the hubs genuinely make (chips, chip-making machines, medical scanners) "
               "are not reassigned. An estimate. ")
EU27 = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
        "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
EU_BREAK = ("EU imports have a break in 2022 Q1, when HMRC moved them from Intrastat to "
            "customs declarations. ")


def quarter(label: str) -> str:
    """'2016 Q1' -> '2016-Q1'."""
    y, q = label.split()
    return f"{y}-{q}"


def to_index(series: dict[str, float]) -> dict[str, float]:
    """Index with the base-year average = 100."""
    base = [v for q, v in series.items() if q.startswith(BASE_YEAR)]
    b = sum(base) / len(base)
    return {q: round(v / b * 100, 1) for q, v in series.items()}


# ---------------------------------------------------------------- 1. goods (MQ10)

def mq10() -> dict[str, dict[str, float]]:
    """{title: {quarter: £m}} for every seasonally adjusted series in MQ10."""
    link = re.search(r'/file\?uri=[^"]+mq10\.csv', get_text(MQ10_PAGE)).group(0)
    rows = list(csv.reader(io.StringIO(get_text("https://www.ons.gov.uk" + link, timeout=180))))
    titles = rows[0]
    out = {t: {} for t in titles[1:] if ":SA:" in t}
    for r in rows:
        if r and re.match(r"^\d{4} Q[1-4]$", r[0]) and quarter(r[0]) >= START:
            for j, t in enumerate(titles[1:], start=1):
                if t in out and j < len(r) and r[j] not in ("", "x"):
                    out[t][quarter(r[0])] = float(r[j])
    return out


def mq10_series(data: dict, code: str, group: str, flow: str, measure: str) -> dict[str, float]:
    """One CPA code's series, e.g. code '26.1', group 'EU'|'RW', flow 'EX'|'IM', measure 'CP'|'CVM'."""
    prefix = f"CPA 08:{group}:{flow}:{measure}:BOP:SA: {code}. "
    hits = [t for t in data if t.startswith(prefix)]
    if len(hits) != 1:
        raise LookupError(f"MQ10: expected one series for {prefix!r}, found {len(hits)}")
    return data[hits[0]]


def goods_tiers(data: dict) -> list[dict]:
    rows = []
    for tier, spec in DEFS["goods_tiers"].items():
        for partner, flow, _ in LINES:
            g, f = ("EU" if partner == "EU" else "RW"), ("EX" if flow == "exports" else "IM")
            cp = [mq10_series(data, c, g, f, "CP") for c in spec["cpa"]]
            cvm = [mq10_series(data, c, g, f, "CVM") for c in spec["cpa"]]
            qs = sorted(set.intersection(*(set(s) for s in cp + cvm)))
            value = {q: sum(s[q] for s in cp) for q in qs}
            volume = {q: sum(s[q] for s in cvm) for q in qs}
            rows += tier_rows("goods", tier, partner, flow, value, volume)
    return rows


def tier_rows(kind, tier, partner, flow, value, volume) -> list[dict]:
    """Long rows with value (£m), volume (CVM £m and index) and implied price index."""
    price = {q: value[q] / volume[q] for q in value if volume.get(q)}
    vol_i, price_i = to_index(volume), to_index(price)
    return [{"kind": kind, "tier": tier, "partner": partner, "flow": flow, "quarter": q,
             "value_gbp_m": round(value[q], 1), "volume_cvm_gbp_m": round(volume[q], 1),
             "volume_index": vol_i[q], "price_index": price_i.get(q)} for q in sorted(value)]


# ---------------------------------------------------------------- 2. services (QNA)

_QNA: dict[str, dict[str, float]] = {}


def qna(cdid: str) -> dict[str, float]:
    """A quarterly QNA series from START, fetched once per run."""
    if cdid not in _QNA:
        _QNA[cdid] = {q: v for q, v in ons.fetch(cdid, "QNA", "Q")["obs"] if q >= START}
    return _QNA[cdid]


def services_tiers() -> list[dict]:
    series = DEFS["services_series"]
    get = qna
    rows = []
    for tier, spec in DEFS["services_tiers"].items():
        for partner, flow, _ in LINES:
            cp = [get(series[t][f"{partner}_{flow}_CP"]) for t in spec["types"]]
            cvm = [get(series[t][f"{partner}_{flow}_CVM"]) for t in spec["types"]]
            qs = sorted(set.intersection(*(set(s) for s in cp + cvm)))
            rows += tier_rows("services", tier, partner, flow,
                              {q: sum(s[q] for s in cp) for q in qs},
                              {q: sum(s[q] for s in cvm) for q in qs})
    return rows


# ---------------------------------------------------------------- 3. products (HMRC)

def hmrc_product(hs6_codes: list[str]) -> dict[tuple[str, str, str], dict[str, float]]:
    """{(partner, flow, quarter): {value, units, mass}} for a set of HS6 codes, summed
    on HMRC's side by month and flow (values in £)."""
    ranges = " or ".join(f"(CommodityId ge {c}00 and CommodityId le {c}99)" for c in hs6_codes)
    apply = (f"filter(MonthId ge {START[:4]}01 and ({ranges}))/groupby((MonthId,FlowTypeId),"
             "aggregate(Value with sum as Value,SuppUnit with sum as Units,NetMass with sum as Mass))")
    rows = hmrc_trade.apply("OTS", apply)
    out: dict = {}
    for r in rows:
        m = r["MonthId"]
        q = f"{m // 100}-Q{(m % 100 - 1) // 3 + 1}"
        partner, flow = FLOWS[r["FlowTypeId"]]
        cell = out.setdefault((partner, flow, q), {"value": 0.0, "units": 0.0, "mass": 0.0, "months": set()})
        cell["value"] += r["Value"] or 0
        cell["units"] += r["Units"] or 0
        cell["mass"] += r["Mass"] or 0
        cell["months"].add(m)
    return out


def products() -> list[dict]:
    rows = []
    for p in DEFS["products"]:
        data = hmrc_product(p["hs6"])
        for (partner, flow, q), c in sorted(data.items()):
            if len(c["months"]) < 3:
                continue  # incomplete quarter
            if p.get("from") and int(q[:4]) < p["from"]:
                continue
            rows.append({"product": p["id"], "label": p["label"], "cpa": p["cpa"], "hs6": " ".join(p["hs6"]),
                         "partner": partner, "flow": flow, "quarter": q,
                         "value_gbp_m": round(c["value"] / 1e6, 2), "units": c["units"],
                         "net_mass_kg": c["mass"],
                         "value_per_unit_gbp": round(c["value"] / c["units"], 2) if c["units"] else None})
        print(f"[ai-trade] product {p['id']}: {sum(1 for r in rows if r['product'] == p['id'])} rows")
    return rows


# ---------------------------------------------------------------- 3b. origins (EU hubs)

_HUBS: dict = {}


def hub_trade() -> dict | None:
    """Each hub's (definitions/ai_trade.yaml `origin_hubs`) imports and exports of every
    code used here, by partner and year, from Eurostat Comext; fetched once per run.
    None if Comext can't be reached: origin-adjusted outputs are then skipped and their
    last published versions kept."""
    if not _HUBS:
        codes = sorted({c for p in DEFS["products"] for c in p["hs6"]} | set(DEFS["imf_hardware"]["hs6"]))
        years = [str(y) for y in range(int(START[:4]), datetime.date.today().year)]
        try:
            for hub in DEFS["origin_hubs"]["countries"]:
                _HUBS[hub] = comext.annual(hub, codes, years)
        except Exception as e:  # noqa: BLE001 - any failure: skip, keep what's published
            print(f"[ai-trade] Comext unavailable, origin-adjusted outputs skipped: {e}")
            _HUBS.clear()
            return None
    return _HUBS


def _is_origin(code: str, hub: str) -> bool:
    """A real partner country in Comext: not an aggregate (WORLD, EXT_EU27_2020...) or a
    special code (Q...), and not the hub itself or the UK (UK goods coming back)."""
    return len(code) == 2 and code.isalpha() and not code.startswith("Q") and code not in ("EU", "EA", "GB", "XI", hub)


def hub_split(hub: str, codes: list[str], year: str) -> tuple[float, dict[str, float]] | None:
    """(share made in the hub, {origin: share of the rest}) for a set of codes in a year.
    Made in the hub ~ net exports / exports, floored at 0: a pure distribution hub exports
    about what it imports, so this is near zero; where the hub makes the goods (e.g. Dutch
    medical scanners) exports exceed imports. Origins = the hub's own imports by partner.
    A year Comext doesn't have yet uses the latest one it has."""
    data = _HUBS.get(hub, {})
    have = sorted({k[3] for k in data})
    if not have:
        return None
    y = year if year in have else (have[-1] if year > have[-1] else have[0])
    codes = set(codes)
    x = sum(v for (f, c, p, yy), v in data.items() if f == "exports" and c in codes and p == "WORLD" and yy == y)
    m = sum(v for (f, c, p, yy), v in data.items() if f == "imports" and c in codes and p == "WORLD" and yy == y)
    made = min(1.0, max(0.0, (x - m) / x)) if x else 0.0
    origins: dict = {}
    for (f, c, p, yy), v in data.items():
        if f == "imports" and c in codes and yy == y and _is_origin(p, hub):
            origins[p] = origins.get(p, 0.0) + v
    total = sum(origins.values())
    return made, ({p: v / total for p, v in origins.items()} if total else {})


def reassign(by_partner: dict[str, float], codes: list[str], year: str) -> dict[str, float]:
    """UK imports by partner {country code: £} with each hub's trade reassigned: the part
    made in the hub stays, the rest is spread over the hub's own import origins. Products
    the hubs genuinely make (`keep_with_hub`: chips, chip-making machines, medical
    scanners) aren't reassigned at all, since net exports understate production where a
    hub both makes and redistributes a product. Hubs import from each other, so passes
    repeat until almost nothing is left labelled as passing through a hub (the order of
    hubs then doesn't matter). Call it for ONE code at a time (see `reassign_by_code`):
    pooling codes would let one the hub really makes keep others it only distributes."""
    out = dict(by_partner)
    if any(c.startswith(tuple(DEFS["origin_hubs"]["keep_with_hub"])) for c in codes):
        return out   # a product the hubs genuinely make: kept as recorded
    hubs = DEFS["origin_hubs"]["countries"]
    splits = {h: hub_split(h, codes, year) for h in hubs}
    splits = {h: sp for h, sp in splits.items() if sp and sp[1]}   # hubs with origin data
    made: dict = {}   # £ estimated as made in each hub: final, not passed on again
    total = sum(out.values())
    for _ in range(20):
        for hub, (share_made, origins) in splits.items():
            v = out.pop(hub, 0.0)
            made[hub] = made.get(hub, 0.0) + v * share_made
            for p, sh in origins.items():
                out[p] = out.get(p, 0.0) + v * (1 - share_made) * sh
        if sum(out.get(h, 0.0) for h in splits) <= 1e-4 * max(total, 1.0):
            break
    for hub, v in made.items():
        out[hub] = out.get(hub, 0.0) + v
    return out


def reassign_by_code(by_code: dict[str, dict[str, float]], year: str) -> dict[str, float]:
    """{hs6: {partner code: £}} -> {partner code: £}, each code reassigned on its own."""
    out: dict = {}
    for code, vals in by_code.items():
        for c, v in reassign(vals, [code], year).items():
            out[c] = out.get(c, 0.0) + v
    return out


def _summed(by_code: dict[str, dict[str, float]]) -> dict[str, float]:
    """{hs6: {partner code: £}} -> {partner code: £}, as recorded."""
    out: dict = {}
    for vals in by_code.values():
        for c, v in vals.items():
            out[c] = out.get(c, 0.0) + v
    return out


def hub_summary() -> list[dict]:
    """For the CSV: each hub's estimated made-in-hub share and top five origins, for the
    IMF basket and each partner category, in the latest year Comext has, for the codes
    that are reassigned (pooled, as a description; the reassignment works code by code),
    plus the codes kept as recorded."""
    products = {p["id"]: p["hs6"] for p in DEFS["products"]}
    rows = []
    for hub in DEFS["origin_hubs"]["countries"]:
        year = max(k[3] for k in _HUBS[hub])
        keep = tuple(DEFS["origin_hubs"]["keep_with_hub"])
        for cat in DEFS["partner_categories"]:
            codes = DEFS["imf_hardware"]["hs6"] if cat.get("imf") else [c for pid in cat["products"] for c in products[pid]]
            moved = [c for c in codes if not c.startswith(keep)]
            row = {"hub": hub, "year": year, "category": cat["label"],
                   "kept_as_recorded": " ".join(c for c in codes if c.startswith(keep))}
            if moved:
                made, origins = hub_split(hub, moved, year)
                top = sorted(origins.items(), key=lambda kv: -kv[1])[:5]
                row["made_in_hub_pct_reassigned_codes"] = round(100 * made, 1)
                row.update({f"origin_{i + 1}": f"{o} {100 * sh:.1f}%" for i, (o, sh) in enumerate(top)})
            rows.append(row)
    return rows


# ---------------------------------------------------------------- 4. by country

def group_members(option: str) -> dict[str, list[str]]:
    return DEFS["country_groups"][option]


def services_by_country() -> list[dict]:
    """Services tiers by partner group, quarterly (£m), consistent with the EU / non-EU
    tier charts. The by-country file (published earlier, before the latest revisions)
    gives each partner's SHARE of non-EU trade; those shares are applied to the latest
    QNA totals, which are seasonally adjusted:
        EU            = QNA EU
        non-EU group  = QNA non-EU x (group / (world - EU) in the by-country file)
        rest of world = QNA non-EU - named non-EU groups
    Done for each service type, then summed into tiers. Where ONS suppressed a partner's
    value ('C'), its share is interpolated from the neighbouring quarters (rest of world
    absorbs the difference). Quarters run to the latest one both sources have."""
    import openpyxl

    from ukmacro.http import get

    link = re.search(r'/file\?uri=[^"]+\.xlsx', get_text(SVC_PAGE)).group(0)
    wb = openpyxl.load_workbook(io.BytesIO(get("https://www.ons.gov.uk" + link, timeout=180)),
                                read_only=True, data_only=True)
    rows = list(wb["Sheet 1. Time Series"].iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Direction")
    qcols = {j: f"{h[:4]}-{h[4:]}" for j, h in enumerate(rows[hi])
             if isinstance(h, str) and re.match(r"^\d{4}Q[1-4]$", h) and f"{h[:4]}-{h[4:]}" >= START}
    cells: dict = {}   # (flow, type code, country code) -> {quarter: £m}
    for r in rows[hi + 1:]:
        if not r or not r[0]:
            continue
        flow, typ, country = str(r[0]).lower(), str(r[1]).strip(), str(r[3]).strip()
        # None = suppressed ('C') or not available, kept distinct from a true zero
        cells[(flow, typ, country)] = {q: (float(r[j]) if isinstance(r[j], (int, float)) else None)
                                       for j, q in qcols.items()}
    series = DEFS["services_series"]

    def interpolate(shares: dict[str, float | None]) -> dict[str, float]:
        """Fill missing shares linearly from the nearest known quarters (flat at the ends)."""
        qs = sorted(shares)
        known = [i for i, q in enumerate(qs) if shares[q] is not None]
        out = {}
        for i, q in enumerate(qs):
            if shares[q] is not None or not known:
                out[q] = shares[q] or 0.0
                continue
            lo = max((k for k in known if k < i), default=None)
            hi = min((k for k in known if k > i), default=None)
            if lo is None or hi is None:
                out[q] = shares[qs[lo if hi is None else hi]]
            else:
                w = (i - lo) / (hi - lo)
                out[q] = shares[qs[lo]] * (1 - w) + shares[qs[hi]] * w
        return out

    def by_type(t: str, flow: str, option: str) -> dict[str, dict[str, float]]:
        """{group: {quarter: £m}} for one service type, benchmarked to QNA."""
        code, cdids = series[t]["ebops"], series[t]
        eu_q, non_q = qna(cdids[f"EU_{flow}_CP"]), qna(cdids[f"NonEU_{flow}_CP"])
        cf = lambda c: cells.get((flow, code, c), {})  # noqa: E731
        quarters = sorted(set(qcols.values()) & set(eu_q) & set(non_q))
        groups = group_members(option)
        # each named non-EU group's share of non-EU trade; suppressed -> interpolated
        shares = {}
        for group, members in groups.items():
            if members in (["EU"], ["REST"]):
                continue
            raw = {}
            for q in quarters:
                world, eu = cf(SVC_WORLD).get(q), cf(SVC_EU).get(q)
                vals = [cf(m).get(q) for m in members]
                ok = world is not None and eu is not None and world - eu > 0
                # a member absent from the file (e.g. Macao, inside "Other Asia") counts as zero;
                # a suppressed member makes the whole group's share unknown for that quarter
                suppressed = any(v is None and (flow, code, m) in cells for v, m in zip(vals, members))
                raw[q] = (sum(v or 0.0 for v in vals) / (world - eu)) if ok and not suppressed else None
            shares[group] = interpolate(raw)
        out: dict = {}
        for q in quarters:
            named = 0.0
            for group, members in groups.items():
                if members == ["EU"]:
                    out.setdefault(group, {})[q] = eu_q[q]
                elif members != ["REST"]:
                    out.setdefault(group, {})[q] = non_q[q] * shares[group][q]
                    named += non_q[q] * shares[group][q]
            if "Rest of world" in groups:
                out.setdefault("Rest of world", {})[q] = non_q[q] - named
        return out

    out = []
    for tier, spec in DEFS["services_tiers"].items():
        for flow in ("exports", "imports"):
            for option in DEFS["country_groups"]:
                parts = [by_type(t, flow, option) for t in spec["types"]]
                for group in group_members(option):
                    qs = sorted(set.intersection(*(set(p.get(group, {})) for p in parts)))
                    out += [{"kind": "services", "item": tier, "option": option, "group": group, "flow": flow,
                             "quarter": q, "value_gbp_m": round(sum(p[group][q] for p in parts), 1)} for q in qs]
    return out


def _partner_code(alpha: str, partner: str) -> str:
    """HMRC country code, with HMRC's special codes in EU flows (e.g. estimates for small
    traders) marked "EU-..." so they stay in the EU group whatever the basis."""
    return alpha if partner != "EU" or alpha in EU27 else f"EU-{alpha}"


def _is_eu(code: str) -> bool:
    return code in EU27 or code.startswith("EU-")


def _grouped(values: dict[str, float], option: str) -> dict[str, float]:
    """{group: £} from {partner code: £} for a grouping option (EU = EU members)."""
    groups = group_members(option)
    out = {}
    for group, members in groups.items():
        if members == ["EU"]:
            out[group] = sum(v for c, v in values.items() if _is_eu(c))
        elif members != ["REST"]:
            out[group] = sum(v for c, v in values.items() if c in members)
    if "Rest of world" in groups:
        out["Rest of world"] = sum(values.values()) - sum(out.values())
    return out


def products_by_country() -> list[dict]:
    """HMRC product values by partner group (£m), quarterly, on two bases:
      as recorded (option "option1"): EU members by country of dispatch, others by HMRC
        country code;
      origin-adjusted ("option1-origin", imports only): imports recorded from EU hubs
        reassigned to likely origins (see `reassign`).
    The IMF AI hardware basket is included as one extra item, "imf_hardware" (its codes
    summed), for its own chart."""
    alpha = {c["CountryId"]: (c["CountryCodeAlpha"] or "").strip()
             for c in get_json(f"{HMRC_COUNTRY}?$select=CountryId,CountryCodeAlpha", timeout=120)["value"]}
    hubs_ok = hub_trade() is not None
    out = []
    imf = {"id": "imf_hardware", "hs6": DEFS["imf_hardware"]["hs6"]}
    for p in DEFS["products"] + [imf]:
        ranges = " or ".join(f"(CommodityId ge {c}00 and CommodityId le {c}99)" for c in p["hs6"])
        apply = (f"filter(MonthId ge {START[:4]}01 and ({ranges}))/groupby((MonthId,FlowTypeId,CountryId,"
                 "CommodityId),aggregate(Value with sum as Value))")
        data = hmrc_trade.apply("OTS", apply)
        cells: dict = {}   # (flow, quarter) -> {hs6: {partner code: £}}
        months: dict = {}
        for r in data:
            m = r["MonthId"]
            q = f"{m // 100}-Q{(m % 100 - 1) // 3 + 1}"
            partner, flow = FLOWS[r["FlowTypeId"]]
            code = _partner_code(alpha.get(r["CountryId"], ""), partner)
            cell = cells.setdefault((flow, q), {}).setdefault(str(r["CommodityId"])[:6], {})
            cell[code] = cell.get(code, 0.0) + (r["Value"] or 0)
            months.setdefault(q, set()).add(m)
        quarters = sorted(q for q, ms in months.items() if len(ms) == 3
                          and not (p.get("from") and int(q[:4]) < p["from"]))
        for flow in ("exports", "imports"):
            for option in DEFS["country_groups"]:
                bases = [(option, False)] + ([(f"{option}-origin", True)] if flow == "imports" and hubs_ok else [])
                for name, adjust in bases:
                    for q in quarters:
                        by_code = cells.get((flow, q), {})
                        vals = reassign_by_code(by_code, q[:4]) if adjust else _summed(by_code)
                        out += [{"kind": "product", "item": p["id"], "option": name, "group": g, "flow": flow,
                                 "quarter": q, "value_gbp_m": round(v / 1e6, 2)}
                                for g, v in _grouped(vals, option).items()]
        print(f"[ai-trade] by country: {p['id']}")
    return out


def rolling4(series: dict[str, float]) -> dict[str, float]:
    """Rolling four-quarter total (this quarter and the three before), from the fourth
    quarter on. Removes seasonal swings without a seasonal model, and isn't thrown by
    one-off timing shifts such as phone launches moving between quarters."""
    qs = sorted(series)
    return {qs[i]: sum(series[q] for q in qs[i - 3:i + 1]) for i in range(3, len(qs))}


def country_charts(rows: list[dict]) -> list[dict]:
    """Services tiers and the selected-products total, by partner group: one chart per
    (tier or products) x flow x grouping option, as ROLLING FOUR-QUARTER TOTALS (£bn) so
    that services and products are treated the same way. Returns rows (quarterly value
    and rolling total) for a CSV."""
    sources = {"services": "ONS trade in services by type (QNA), split by partner using shares from ONS trade "
                           "in services by partner country; ukmacro calculations",
               "product": "HMRC Overseas Trade Statistics; ukmacro calculations"}
    def groups_of(option: str) -> list[str]:
        return list(group_members(option.removesuffix("-origin")))
    # products total: products with a full series only (smartphones are inside mobile
    # phones; codes created in 2022 would put a break in the total)
    total_products = [p["id"] for p in DEFS["products"] if p["id"] != "smartphones" and not p.get("from")]
    blocks = [("services", t, "AI-relevant services, " + DEFS["services_tiers"][t]["label"].split(":")[0].lower()
               + " tier", [t]) for t in DEFS["services_tiers"]]
    blocks.append(("product", "total", "selected AI-relevant products (goods)", total_products))
    blocks.append(("product", "imf-hardware", DEFS["imf_hardware"]["label"], ["imf_hardware"]))
    out_rows = []
    for kind, slug_part, what, items in blocks:
        for flow in ("exports", "imports"):
            # as recorded, plus origin-adjusted where built (product imports)
            options = sorted({r["option"] for r in rows if r["kind"] == kind and r["flow"] == flow})
            for option in options:
                origin = option.endswith("-origin")
                sums: dict = {}
                for r in rows:
                    if r["kind"] == kind and r["item"] in items and r["flow"] == flow and r["option"] == option:
                        sums.setdefault(r["group"], {})
                        sums[r["group"]][r["quarter"]] = sums[r["group"]].get(r["quarter"], 0.0) + r["value_gbp_m"]
                rolled = {g: rolling4(v) for g, v in sums.items()}
                out_rows += [{"kind": kind, "item": slug_part, "option": option, "group": g, "flow": flow,
                              "quarter": q, "value_gbp_m": round(v[q], 1),
                              "rolling_4q_gbp_m": round(rolled[g][q], 1) if q in rolled[g] else None}
                             for g, v in sums.items() for q in sorted(v)]
                quarters = sorted({q for v in rolled.values() for q in v})
                data = [{"date": q, **{g: round(rolled.get(g, {}).get(q, 0.0) / 1000, 1) for g in groups_of(option)}}
                        for q in quarters]
                note = UPPER_BOUND + "Rolling four-quarter totals (each point = the latest four quarters), which remove seasonal swings. "
                if option.startswith("option1"):
                    note += "East Asia = China, Hong Kong, Macao, Japan, South Korea, Taiwan. "
                if kind == "services":
                    note += ("Partner shares from the by-country file are applied to the latest QNA EU and "
                             "non-EU totals; suppressed partner values are interpolated. ")
                elif slug_part == "imf-hardware":
                    note = ("IMF AI hardware basket (HS 847150, 847170, 847180, 847330, 848610, 848620, "
                            "848640, 848690, 854231, 854232): servers and other computer units, storage, "
                            "computer assemblies (incl. graphics cards), processor and memory chips, and "
                            "semiconductor manufacturing equipment. Whole codes, so an upper bound. "
                            "Rolling four-quarter totals (each point = the latest four quarters). "
                            "East Asia = China, Hong Kong, Macao, Japan, South Korea, Taiwan. "
                            + ("" if origin else "EU trade is recorded by country of dispatch, so goods routed "
                               "via the EU count as EU. ") + EU_BREAK)
                else:
                    note += ("Products: chips, computers and servers, storage, graphics cards, laptops and tablets, "
                             "mobile phones, network equipment, cameras, medical scanners and diagnostics, "
                             "vacuum cleaners (incl. robotic), industrial robots. "
                             + ("" if origin else "EU trade is recorded by country of dispatch, so goods routed "
                                "via the EU count as EU. ") + EU_BREAK)
                if origin:
                    note += ORIGIN_NOTE
                publish(chart(f"ai-trade-{kind}-{slug_part}-{flow}-{option}",
                              f"UK {flow} of {what}, by partner" + (" (origin-adjusted)" if origin else ""),
                              "£ billion, rolling four-quarter total", "line",
                              [{"key": g, "label": g} for g in groups_of(option)],
                              data, note,
                              "HMRC Overseas Trade Statistics; Eurostat Comext; ukmacro calculations"
                              if origin else sources[kind]))
    return out_rows


# ---------------------------------------------------------------- 4b. prices (IMF basket)

def imf_price_charts(mq: dict, prods: list[dict]) -> list[dict]:
    """Two views of prices for AI compute hardware (the IMF basket), returning rows for a CSV.
    1. Official: ONS implied prices (current prices / chained volumes, seasonally adjusted)
       for CPA 26.2 computers and 26.1 electronic components, EU + non-EU combined: the
       closest official match to the IMF basket (servers, storage, chips). Quarterly.
    2. Servers (HS 847150): average value per unit from HMRC, rolling four quarters. Not a
       like-for-like price: it moves with the MIX of servers (e.g. towards GPU servers).
    Most other IMF codes have no usable unit counts (processors and chip-making machines
    report weight only), so no unit-value index is built for the whole basket."""
    rows, series, data = [], [], {}
    for code, name in (("26.2", "Computers"), ("26.1", "Electronic components")):
        for flow, f in (("imports", "IM"), ("exports", "EX")):
            cp = [mq10_series(mq, code, g, f, "CP") for g in ("EU", "RW")]
            cvm = [mq10_series(mq, code, g, f, "CVM") for g in ("EU", "RW")]
            qs = sorted(set.intersection(*(set(x) for x in cp + cvm)))
            price = to_index({q: sum(x[q] for x in cp) / sum(x[q] for x in cvm) for q in qs})
            key = f"{code}_{flow}"
            series.append({"key": key, "label": f"{name}, {flow}"})
            for q in qs:
                data.setdefault(q, {"date": q})[key] = price[q]
                rows.append({"measure": "official_price_index", "item": f"CPA {code}", "flow": flow,
                             "quarter": q, "value": price[q]})
    publish(chart("ai-trade-imf-hardware-prices-official",
                  "Prices of computers and electronic components in UK trade",
                  f"Implied price index, {BASE_YEAR} = 100", "line", series,
                  [data[q] for q in sorted(data)],
                  "Implied prices = current-price value / chained volume, EU and non-EU combined. "
                  "CPA 26.2 (computers, incl. servers and storage) and 26.1 (electronic components, "
                  "incl. processors and memory) are the closest official match to the IMF AI hardware "
                  "basket; they also contain non-AI products. In sterling, so exchange-rate moves count. ",
                  "ONS UK trade in goods by CPA (MQ10), seasonally adjusted; ukmacro calculations"))
    # servers: value per unit, rolling four quarters (EU + non-EU)
    agg: dict = {}
    for r in prods:
        if r["product"] == "servers":
            a = agg.setdefault((r["flow"], r["quarter"]), [0.0, 0.0])
            a[0] += r["value_gbp_m"] * 1e6
            a[1] += r["units"] or 0
    data = {}
    for (flow, q), (v, u) in sorted(agg.items(), key=lambda kv: kv[0][1]):
        if u:
            data.setdefault(q, {"date": q})[flow] = round(v / u)
            rows.append({"measure": "server_value_per_unit_gbp", "item": "HS 847150", "flow": flow,
                         "quarter": q, "value": round(v / u)})
    publish(chart("ai-trade-imf-hardware-server-unit-values",
                  "Average value per server in UK trade",
                  "£ per unit, quarterly", "line",
                  [{"key": "imports", "label": "Imports"}, {"key": "exports", "label": "Exports"}],
                  [data[q] for q in sorted(data)],
                  "HS 847150 (processing units, incl. servers), the largest item in the IMF AI hardware "
                  "basket. Value / supplementary units each quarter; not seasonally adjusted (HMRC publishes "
                  "no seasonally adjusted series at this level). Not a like-for-like "
                  "price: it rises when the mix shifts towards expensive units such as GPU servers. ",
                  "HMRC Overseas Trade Statistics; ukmacro calculations"))
    return rows


def imf_component_charts() -> tuple[list[dict], dict]:
    """IMF AI hardware basket by component (definitions/ai_trade.yaml `imf_hardware.components`):
    stacked bars of calendar-year totals (£bn), complete years only, one chart each for
    imports and exports. Returns rows for a CSV, and quarterly values
    {(component index, flow, quarter): £} (EU + non-EU) for the AI stack."""
    comps = DEFS["imf_hardware"]["components"]
    annual: dict = {}   # (component index, flow, year) -> £
    quarterly: dict = {}
    for k, comp in enumerate(comps):
        for (partner, flow, q), c in hmrc_product(comp["hs6"]).items():
            if len(c["months"]) == 3:
                quarterly[(k, flow, q)] = quarterly.get((k, flow, q), 0.0) + c["value"]
                key = (k, flow, q[:4])
                annual.setdefault(key, [0.0, 0])
                annual[key][0] += c["value"]
                annual[key][1] += 1   # quarter-partner cells: 8 = a complete year (4 quarters x EU/non-EU)
    rows = []
    for flow in ("imports", "exports"):
        years = sorted({y for (k, f, y), (v, n) in annual.items() if f == flow and n == 8})
        data = [{"date": y, **{f"c{k}": round(annual.get((k, flow, y), [0.0])[0] / 1e9, 2)
                               for k in range(len(comps))}} for y in years]
        rows += [{"component": comps[k]["label"], "flow": flow, "year": d["date"], "value_gbp_bn": d[f"c{k}"]}
                 for d in data for k in range(len(comps))]
        series = [{"key": f"c{k}", "label": c["label"]} for k, c in enumerate(comps)]
        series[-1]["color"] = "neutral"   # small; five components, four palette colours
        publish(chart(f"ai-trade-imf-hardware-components-{flow}",
                      f"UK {flow} of AI compute hardware (IMF basket), by component",
                      "£ billion, calendar year", "stacked-bar", series, data,
                      UPPER_BOUND + "IMF AI hardware basket. Servers and processing units = HS 847150 (also "
                      "includes desktop PC base units); storage and other units = 847170, 847180; assemblies "
                      "= 847330; chips = 854231, 854232; chip-making equipment = 848610-848690. Complete "
                      "calendar years only. " + (EU_BREAK if flow == "imports" else ""),
                      "HMRC Overseas Trade Statistics; ukmacro calculations", freq="A"))
    return rows, quarterly


def ai_stack_charts(mq: dict, prods: list[dict], imf_q: dict, tiers: list[dict]) -> list[dict]:
    """The "AI stack" in UK trade, narrowest to broadest, as stacked calendar-year bars
    (£bn): one chart each for imports and exports, in values and in volumes. Layers:
      1. IMF AI hardware basket (HMRC, by component)
      2. other AI products on the ONS-based product list (HMRC; codes not in layer 1;
         full-series products only, as in the products total)
      3. the rest of the ONS extended goods tier, CPA 26-28 (MQ10, EU + non-EU) minus
         layers 1 and 2, so layers 1-3 add up to the extended goods tier
      4. AI services, core tier (QNA: telecoms, computer and information services; IP charges)
    Volumes are at 2019 prices: each piece is deflated by the ONS implied price of its
    CPA group (layer 1 by component, layer 2 by product), normalised so 2019 volume =
    2019 value. ONS chained volumes aren't strictly additive, and HMRC values aren't
    seasonally adjusted while MQ10 and QNA are; for calendar-year totals both matter little."""
    imf_codes = set(DEFS["imf_hardware"]["hs6"])
    others = {p["id"]: p["cpa"] for p in DEFS["products"]
              if p["id"] != "smartphones" and not p.get("from") and not set(p["hs6"]) & imf_codes}
    comps = DEFS["imf_hardware"]["components"]

    def to_2019_prices(cp: dict, cvm: dict) -> dict:
        """Chained volumes rescaled so that the 2019 total equals the 2019 value."""
        k = sum(v for q, v in cp.items() if q[:4] == BASE_YEAR) / sum(v for q, v in cvm.items() if q[:4] == BASE_YEAR)
        return {q: cvm[q] * k for q in cvm}

    def ons_goods(codes: list[str], f: str) -> tuple[dict, dict]:
        """MQ10 value and volume at 2019 prices (£m), EU + non-EU, for a list of CPA codes."""
        cp = [mq10_series(mq, c, g, f, "CP") for c in codes for g in ("EU", "RW")]
        cvm = [mq10_series(mq, c, g, f, "CVM") for c in codes for g in ("EU", "RW")]
        qs = set.intersection(*(set(x) for x in cp + cvm))
        val = {q: sum(x[q] for x in cp) for q in qs}
        return val, to_2019_prices(val, {q: sum(x[q] for x in cvm) for q in qs})

    rows = []
    for flow, f in (("imports", "IM"), ("exports", "EX")):
        price = {}   # CPA code -> {quarter: price relative to 2019}

        def deflate(value_m: float, cpa: str, q: str) -> float | None:
            if cpa not in price:
                val, vol = ons_goods([cpa], f)
                price[cpa] = {qq: val[qq] / vol[qq] for qq in val if vol[qq]}
            return value_m / price[cpa][q] if q in price[cpa] else None

        layers = {name: ({}, {}) for name in ("imf", "ons_products", "rest", "services")}  # (value, volume) by quarter, £m

        def add(name: str, q: str, value_m: float, volume_m: float | None) -> None:
            val, vol = layers[name]
            val[q] = val.get(q, 0.0) + value_m
            if volume_m is None or (q in vol and vol[q] is None):
                vol[q] = None   # no price for this quarter: the quarter has no volume
            else:
                vol[q] = vol.get(q, 0.0) + volume_m
        for (k, fl, q), v in imf_q.items():
            if fl == flow:
                add("imf", q, v / 1e6, deflate(v / 1e6, comps[k]["cpa"], q))
        for r in prods:
            if r["flow"] == flow and r["product"] in others:
                add("ons_products", r["quarter"], r["value_gbp_m"], deflate(r["value_gbp_m"], others[r["product"]], r["quarter"]))
        ext_val, ext_vol = ons_goods(DEFS["goods_tiers"]["extended"]["cpa"], f)
        for q in ext_val:
            parts = [layers[n] for n in ("imf", "ons_products")]
            if all(q in pv for pv, _ in parts) and all(pvol.get(q) is not None for _, pvol in parts):
                add("rest", q, ext_val[q] - sum(pv[q] for pv, _ in parts),
                    ext_vol[q] - sum(pvol[q] for _, pvol in parts))
        svc = [r for r in tiers if r["kind"] == "services" and r["tier"] == "core" and r["flow"] == flow]
        s_val, s_cvm = {}, {}
        for r in svc:
            s_val[r["quarter"]] = s_val.get(r["quarter"], 0.0) + r["value_gbp_m"]
            s_cvm[r["quarter"]] = s_cvm.get(r["quarter"], 0.0) + r["volume_cvm_gbp_m"]
        s_vol = to_2019_prices(s_val, s_cvm)
        for q in s_val:
            add("services", q, s_val[q], s_vol[q])

        # calendar years in which every layer has four quarters with a volume
        years = sorted({q[:4] for q in layers["rest"][0]})
        years = [y for y in years if all(
            sum(1 for q, v in layers[n][1].items() if q[:4] == y and v is not None) == 4 for n in layers)]
        series = [{"key": "imf", "label": "AI compute hardware (IMF definition)"},
                  {"key": "ons_products", "label": "Other AI products, e.g. phones, laptops, network kit (ONS definition)"},
                  {"key": "rest", "label": "Wider electronics, electrical and machinery goods (ONS extended tier)",
                   "color": "neutral"},
                  {"key": "services", "label": "AI services, e.g. computing, telecoms, IP charges (ONS definition)"}]
        for measure, idx, units, what in (("value", 0, "£ billion, current prices, calendar year", ""),
                                          ("volume", 1, f"£ billion at {BASE_YEAR} prices, calendar year", " in volume terms")):
            data = []
            for y in years:
                d = {"date": y}
                for n in layers:
                    d[n] = round(sum(v for q, v in layers[n][idx].items() if q[:4] == y) / 1000, 2)
                data.append(d)
                rows.append({"flow": flow, "measure": measure, "year": y, **{f"{n}_gbp_bn": d[n] for n in layers}})
            note = (UPPER_BOUND + "Layers nest from narrowest to broadest: the IMF hardware basket and other AI "
                    "products (HMRC, by commodity code) are inside the ONS extended goods tier (CPA 26-28, "
                    "MQ10), and the grey layer is the rest of that tier. AI services = ONS core services "
                    "tier (QNA). Other AI products exclude codes created in 2022 (sensors, handling robots, "
                    "drones). ")
            if measure == "volume":
                note += (f"Volumes at {BASE_YEAR} prices: HMRC values deflated by the ONS implied price of "
                         "each product's CPA group; ONS chained volumes rescaled to 2019 values. Chained "
                         "volumes aren't strictly additive, so the layers are approximate. ")
            note += EU_BREAK if flow == "imports" else ""
            publish(chart(f"ai-trade-ai-stack-{flow}" + ("-volume" if measure == "volume" else ""),
                          f"The AI stack in UK {flow}{what}", units, "stacked-bar", series, data, note,
                          "HMRC Overseas Trade Statistics; ONS UK trade in goods by CPA (MQ10); ONS trade in "
                          "services (QNA); ukmacro calculations", freq="A"))
    # the latest complete year: imports and exports side by side, in value and volume
    year = max(r["year"] for r in rows if r["flow"] == "exports" and
               any(x["year"] == r["year"] and x["flow"] == "imports" for x in rows))
    for measure, units, what in (("value", f"£ billion, current prices, {year}", ""),
                                 ("volume", f"£ billion at {BASE_YEAR} prices, {year}", " in volume terms")):
        data = [{"date": flow.capitalize(), **{n: r[f"{n}_gbp_bn"] for n in layers}}
                for flow in ("imports", "exports")
                for r in rows if r["flow"] == flow and r["measure"] == measure and r["year"] == year]
        c = chart(f"ai-trade-ai-stack-{year}" + ("-volume" if measure == "volume" else ""),
                  f"The AI stack in UK trade{what}: imports and exports, {year}", units, "stacked-bar",
                  series, data,
                  UPPER_BOUND + "Layers as in the AI stack charts: the IMF hardware basket and other AI "
                  "products (HMRC) are inside the ONS extended goods tier (CPA 26-28), and AI services are "
                  "the ONS core services tier. " + ("Volumes at 2019 prices; approximate, as chained volumes "
                  "aren't strictly additive. " if measure == "volume" else ""),
                  "HMRC Overseas Trade Statistics; ONS UK trade in goods by CPA (MQ10); ONS trade in "
                  "services (QNA); ukmacro calculations", freq="A")
        c["events"] = None
        publish(c)
    return rows


def top_partner_charts(n_top: int = 3) -> list[dict]:
    """Top partners for each product group (definitions/ai_trade.yaml `partner_categories`)
    over the latest two complete calendar years: each partner's share of UK imports, and
    of exports, of the group; plus imports origin-adjusted (EU hub trade reassigned to
    likely origins, see `reassign`). EU members are named individually. Shares are of
    all trade in the group, including trade whose country HMRC suppresses, which is never
    ranked. Returns rows (top ten per group and basis) for a CSV."""
    countries = get_json(f"{HMRC_COUNTRY}?$select=CountryId,CountryCodeAlpha,CountryName", timeout=120)["value"]
    alpha = {c["CountryId"]: (c["CountryCodeAlpha"] or "").strip() for c in countries}
    name_by_id = {c["CountryId"]: c["CountryName"].strip() for c in countries}
    name: dict = {}   # partner code -> name; ids seen in the data first (HMRC has several ids for
    for c in countries:   # some codes, e.g. "United States" and the historical "USA")
        name.setdefault((c["CountryCodeAlpha"] or "").strip(), c["CountryName"].strip())
    products = {p["id"]: p["hs6"] for p in DEFS["products"]}
    # the latest two complete calendar years in HMRC (any product's quarters will do)
    probe = hmrc_product(DEFS["imf_hardware"]["hs6"][:1])
    done = {q for (partner, flow, q), c in probe.items()
            if partner == "EU" and flow == "imports" and len(c["months"]) == 3}   # complete quarters
    full = sorted(y for y in {q[:4] for q in done} if sum(1 for q in done if q[:4] == y) == 4)
    years = full[-2:]
    period = f"{years[0]}-{years[-1]}"
    hubs_ok = hub_trade() is not None
    bases = [("imports", False), ("exports", False)] + ([("imports", True)] if hubs_ok else [])
    seen_name: dict = {}   # partner code -> name of the HMRC country id used in the data
    rows, data = [], {b: [] for b in bases}
    for cat in DEFS["partner_categories"]:
        codes = DEFS["imf_hardware"]["hs6"] if cat.get("imf") else [c for pid in cat["products"] for c in products[pid]]
        cells: dict = {}   # (flow, year) -> {hs6: {partner code: £}}
        for code in codes:
            apply = (f"filter(MonthId ge {years[0]}01 and MonthId le {years[-1]}12 and CommodityId ge {code}00 "
                     f"and CommodityId le {code}99)/groupby((MonthId,FlowTypeId,CountryId),aggregate(Value with sum as V))")
            for r in hmrc_trade.apply("OTS", apply):
                partner, flow = FLOWS[r["FlowTypeId"]]
                c = _partner_code(alpha.get(r["CountryId"], ""), partner)
                if r["V"] and r["CountryId"] in name_by_id:
                    seen_name.setdefault(c, name_by_id[r["CountryId"]])
                cell = cells.setdefault((flow, str(r["MonthId"] // 100)), {}).setdefault(code, {})
                cell[c] = cell.get(c, 0.0) + (r["V"] or 0)
        for flow, adjust in bases:
            totals: dict = {}
            for y in years:
                by_code = cells.get((flow, y), {})
                vals = reassign_by_code(by_code, y) if adjust else _summed(by_code)
                for c, v in vals.items():
                    totals[c] = totals.get(c, 0.0) + v
            total = sum(totals.values())
            # rank real countries only: HMRC's special codes (suppressed, estimates, stores...)
            # are blank, start with Q or are marked EU-
            name.update(seen_name)
            ranked = sorted(((c, v) for c, v in totals.items() if c in name and c and not c.startswith("Q")),
                            key=lambda cv: -cv[1])
            basis = "origin-adjusted" if adjust else "as recorded"
            for i, (c, v) in enumerate(ranked[:10]):
                rows.append({"category": cat["label"], "flow": flow, "basis": basis, "period": period,
                             "rank": i + 1, "country": name[c], "eu": c in EU27,
                             "value_gbp_m": round(v / 1e6, 1), "share_pct": round(100 * v / total, 1)})
            data[(flow, adjust)].append({"date": cat["label"],
                                         "ranks": [{"label": name[c], "value": round(100 * v / total, 1),
                                                    "key": "EU" if c in EU27 else "nonEU"} for c, v in ranked[:n_top]]})
    for (flow, adjust), d in data.items():
        word = "sources" if flow == "imports" else "destinations"
        if adjust:
            where = ORIGIN_NOTE
        elif flow == "imports":
            where = ("EU imports are recorded by country of dispatch (so goods routed via e.g. Dutch distribution "
                     "hubs count as the Netherlands); non-EU imports by country of origin. ")
        else:
            where = "Exports are recorded by country of destination. "
        c = chart(f"ai-trade-top-partners-{flow}" + ("-origin" if adjust else ""),
                  f"Top {n_top} {word} of UK AI {flow}, by product group, {period}"
                  + (" (origin-adjusted)" if adjust else ""),
                  f"Share of UK {flow} of each product group, %", "ranked-bars",
                  [{"key": "EU", "label": "EU member state"}, {"key": "nonEU", "label": "Outside the EU"}], d,
                  UPPER_BOUND + "AI compute hardware = IMF AI hardware basket; the other groups are the "
                  "ONS-based AI products by type. " + where + "Shares are of all trade, including trade whose "
                  "partner HMRC suppresses for confidentiality.",
                  "HMRC Overseas Trade Statistics; " + ("Eurostat Comext; " if adjust else "") + "ukmacro calculations",
                  freq="A")
        c["events"] = None
        c["value_format"] = "{:.1f}%"
        publish(c)
    return rows


# ---------------------------------------------------------------- 4c. chip supply chain

SHORT_NAMES = {"CN": "China", "TW": "Taiwan", "KR": "Korea", "US": "US", "DE": "Germany", "MX": "Mexico",
               "MY": "Malaysia", "VN": "Vietnam", "IL": "Israel", "JP": "Japan", "GB": "UK", "CZ": "Czechia",
               "PL": "Poland", "HU": "Hungary", "CR": "Costa Rica", "SE": "Sweden", "ES": "Spain", "FR": "France",
               "CA": "Canada", "NO": "Norway", "BR": "Brazil", "DK": "Denmark", "BE": "Belgium", "NL": "Netherlands",
               "IE": "Ireland", "IT": "Italy", "AT": "Austria", "SG": "Singapore", "TH": "Thailand", "HK": "Hong Kong",
               "IN": "India", "PH": "Philippines", "CH": "Switzerland"}


def chip_supply_chain_chart() -> list[dict]:
    """"Following an AI chip": each supply-chain stage (definitions/ai_trade.yaml
    `chip_supply_chain`) and what Dutch and Irish trade (Eurostat Comext, latest year)
    shows at it: imports, exports, the top sources and destinations, and whether the
    country is a net exporter (largely makes it), a net importer (uses it or passes it
    on) or trades both ways (a hub). Returns rows for a CSV."""
    spec = DEFS["chip_supply_chain"]
    codes = [c for st in spec["stages"] for c in st["hs6"]]
    years = [str(y) for y in range(datetime.date.today().year - 3, datetime.date.today().year)]
    try:
        trade = {cc: comext.annual(cc, codes, years) for cc in spec["countries"]}
    except Exception as e:  # noqa: BLE001 - skip, keep the last published version
        print(f"[ai-trade] Comext unavailable, chip supply chain skipped: {e}")
        return []
    year = min(max(k[3] for k in d) for d in trade.values())
    rows, grid = [], []

    def name(code: str) -> str:
        return SHORT_NAMES.get(code, code)
    for cc, country in spec["countries"].items():
        d, cells = trade[cc], []
        for st in spec["stages"]:
            codes_ = set(st["hs6"])
            tot = {f: sum(v for (ff, c, p, y), v in d.items() if ff == f and c in codes_ and p == "WORLD" and y == year)
                   for f in ("imports", "exports")}
            partners = {}
            for f in ("imports", "exports"):
                agg: dict = {}
                for (ff, c, p, y), v in d.items():
                    if ff == f and c in codes_ and y == year and _is_origin(p, cc) or (
                            ff == f and c in codes_ and y == year and p == "GB"):
                        agg[p] = agg.get(p, 0.0) + v
                partners[f] = sorted(agg.items(), key=lambda kv: -kv[1])[:3]
                rows += [{"country": country, "stage": st["label"], "year": year, "flow": f, "partner": name(p),
                          "eur_bn": round(v / 1e9, 2)} for p, v in partners[f]]
            m, x = tot["imports"], tot["exports"]
            key = "makes" if x >= 1.5 * m else ("uses" if m >= 1.5 * x else "hub")
            def fmt(ps):   # partners of at least €0.05bn
                big = [f"{name(p)} {v / 1e9:.1f}" for p, v in ps if v >= 5e7]
                return ", ".join(big) if big else "all small"
            cells.append({"headline": f"In {m / 1e9:.1f} · Out {x / 1e9:.1f}", "key": key,
                          "lines": [f"From: {fmt(partners['imports'])}", f"To: {fmt(partners['exports'])}"]})
            rows.append({"country": country, "stage": st["label"], "year": year, "flow": "total",
                         "partner": f"imports {m / 1e9:.2f}, exports {x / 1e9:.2f}", "eur_bn": None})
        grid.append({"date": country, "label": country, "cells": cells})
    grid.append({"date": "context", "label": "Who makes it worldwide", "weight": 0.75,
                 "cells": [{"lines": [st["context"]]} for st in spec["stages"]]})
    c = chart("ai-chip-supply-chain", f"Following an AI chip through Dutch and Irish trade, {year}",
              f"€ billion, {year}: imports (in) and exports (out), with the top three sources and destinations",
              "flow-grid",
              [{"key": "makes", "label": "Net exporter: largely made here"},
               {"key": "hub", "label": "Two-way trade: distribution hub"},
               {"key": "uses", "label": "Net importer: used here or passed on"}],
              grid,
              "Each stage is a set of HS6 trade codes: 1. 280461, 381800, 280429, 811292, 370790; 2. 848620, "
              "848690; 3. 854231, 854232; 4. 847330; 5. 847150. Whole codes, so they include non-AI products. "
              "Partners as recorded by the Netherlands and Ireland (EU trade by member state of dispatch or "
              "arrival, non-EU imports by origin). 'Who makes it worldwide' is background, not trade data.",
              "Eurostat Comext; ukmacro calculations", freq="A")
    c["columns"] = [{"label": st["label"], "sub": st["sub"]} for st in spec["stages"]]
    c["events"] = None
    publish(c)
    return rows


# ---------------------------------------------------------------- 5. summary tables

def product_summary(rows: list[dict], base: str = "2019", latest: str = "2025") -> list[dict]:
    """Calendar-year change for each product: imports and exports (£bn), units and value
    per unit. Products created in 2022 use 2022 as their base year."""
    out = []
    for p in DEFS["products"]:
        b = str(p["from"]) if p.get("from") and int(p["from"]) > int(base) else base

        def year(flow, y, field):
            return sum((r[field] or 0) for r in rows if r["product"] == p["id"] and r["flow"] == flow
                       and r["quarter"].startswith(y))

        imp_b, imp_l = year("imports", b, "value_gbp_m"), year("imports", latest, "value_gbp_m")
        exp_b, exp_l = year("exports", b, "value_gbp_m"), year("exports", latest, "value_gbp_m")
        u_b, u_l = year("imports", b, "units"), year("imports", latest, "units")
        pct = lambda a, z: round((z / a - 1) * 100) if a else None  # noqa: E731
        out.append({
            "product": p["label"], "hs6": " ".join(p["hs6"]), "cpa": p["cpa"], "base_year": b,
            "imports_base_gbp_bn": round(imp_b / 1000, 2), f"imports_{latest}_gbp_bn": round(imp_l / 1000, 2),
            "imports_change_pct": pct(imp_b, imp_l),
            "import_units_change_pct": pct(u_b, u_l) if u_b and u_l else None,
            "import_value_per_unit_base_gbp": round(imp_b * 1e6 / u_b) if u_b else None,
            f"import_value_per_unit_{latest}_gbp": round(imp_l * 1e6 / u_l) if u_l else None,
            "exports_base_gbp_bn": round(exp_b / 1000, 2), f"exports_{latest}_gbp_bn": round(exp_l / 1000, 2),
            "exports_change_pct": pct(exp_b, exp_l),
        })
    return out


def write_markdown_tables(summary: list[dict], path: Path) -> None:
    """Human-readable product summary and ONS coverage, for checking and sharing."""
    lines = ["# AI-relevant products: summary of changes", "",
             "Calendar years; imports and exports in £bn (HMRC). Upper bounds: each code also contains "
             "non-AI items. Products created in the 2022 code revision compare 2022 with 2025.", "",
             "| Product | Codes | Base | Imports base | Imports 2025 | Change | Units change | £/unit base | £/unit 2025 | Exports base | Exports 2025 | Change |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, suf="": "–" if v is None else f"{v:,}{suf}"  # noqa: E731
    for r in summary:
        lines.append(f"| {r['product']} | {r['hs6']} | {r['base_year']} | {r['imports_base_gbp_bn']:.2f} | "
                     f"{r['imports_2025_gbp_bn']:.2f} | {f(r['imports_change_pct'], '%')} | "
                     f"{f(r['import_units_change_pct'], '%')} | {f(r['import_value_per_unit_base_gbp'])} | "
                     f"{f(r['import_value_per_unit_2025_gbp'])} | {r['exports_base_gbp_bn']:.2f} | "
                     f"{r['exports_2025_gbp_bn']:.2f} | {f(r['exports_change_pct'], '%')} |")
    lines += ["", "# Coverage of the ONS AI product list", "",
              "| ONS AI product | Covered by | Note |", "|---|---|---|"]
    labels = {p["id"]: p["label"] for p in DEFS["products"]}
    for c in DEFS["coverage"]:
        lines.append(f"| {c['ons']} | {', '.join(labels[i] for i in c['products']) or '–'} | {c.get('note', '')} |")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- charts

def chart(slug, title, units, kind, series, data, note, source, freq="Q") -> dict:
    return {"slug": slug, "category": "trade", "title": title, "type": kind, "freq": freq,
            "units": units, "source": source, "note": note, "series": series,
            "events": EVENTS if kind != "grouped-hbar" else None,
            "data_through": data[-1]["date"] if data else None, "status": "ok", "data": data}


def publish(c: dict) -> None:
    charts.publish(c, OUT / f"{c['slug']}.json", IMG / f"{c['slug']}.png")


def tier_charts(rows: list[dict]) -> None:
    measures = [("value", "value_gbp_m", "£ billion, current prices", 1 / 1000),
                ("volume", "volume_index", f"Volume index, {BASE_YEAR} = 100", 1),
                ("price", "price_index", f"Implied price index, {BASE_YEAR} = 100", 1)]
    sources = {"goods": "ONS UK trade in goods by CPA (MQ10), seasonally adjusted; ukmacro calculations",
               "services": "ONS trade in services by type (QNA), seasonally adjusted; ukmacro calculations"}
    for kind in ("goods", "services"):
        defs = DEFS[f"{kind}_tiers"]
        for tier, spec in defs.items():
            sub = [r for r in rows if r["kind"] == kind and r["tier"] == tier]
            for m, field, units, scale in measures:
                by_q: dict[str, dict] = {}
                for r in sub:
                    v = r[field]
                    by_q.setdefault(r["quarter"], {})[f"{r['partner']}_{r['flow']}"] = (
                        round(v * scale, 2) if v is not None else None)
                data = [{"date": q, **by_q[q]} for q in sorted(by_q)]
                what = {"value": "", "volume": " in volume terms", "price": ": implied prices"}[m]
                note = UPPER_BOUND + (EU_BREAK if kind == "goods" else "")
                if m != "value":
                    note += "Volumes are chained volume measures summed across codes; prices are value / volume. "
                if kind == "services":
                    note += "Services use broad ONS service types, which approximate the CPA tiers. "
                publish(chart(f"ai-trade-{kind}-{tier}-{m}",
                              f"AI-relevant {kind} trade{what}: {spec['label'].split(':')[0].lower()} tier",
                              units, "line",
                              [{"key": f"{p}_{f}", "label": lab} for p, f, lab in LINES],
                              data, note + f"Tier: {spec['label']}.", sources[kind]))


def product_charts(rows: list[dict]) -> None:
    """Latest four quarters by product, EU vs non-EU, for imports and for exports."""
    quarters = sorted({r["quarter"] for r in rows})
    last4 = quarters[-4:]
    labels = {p["id"]: p["label"] for p in DEFS["products"]}
    for flow in ("imports", "exports"):
        totals: dict[str, dict] = {}
        for r in rows:
            # smartphones are a subset of mobile phones: chart the continuous series only
            if r["flow"] == flow and r["quarter"] in last4 and r["product"] != "smartphones":
                t = totals.setdefault(r["product"], {"EU": 0.0, "NonEU": 0.0})
                t[r["partner"]] += r["value_gbp_m"] / 1000
        order = sorted(totals, key=lambda p: -(totals[p]["EU"] + totals[p]["NonEU"]))
        data = [{"date": labels[p], "EU": round(totals[p]["EU"], 2), "NonEU": round(totals[p]["NonEU"], 2)}
                for p in order]
        publish(chart(f"ai-trade-products-{flow}",
                      f"UK {flow} of selected AI-relevant products, {last4[0].replace('-', ' ')} to "
                      f"{last4[-1].replace('-', ' ')}",
                      "£ billion, last four quarters", "grouped-hbar",
                      [{"key": "EU", "label": "EU"}, {"key": "NonEU", "label": "Non-EU"}], data,
                      UPPER_BOUND + "Products selected by HMRC commodity code; each still includes "
                      "non-AI items (e.g. all processors, all phones). " + EU_BREAK,
                      "HMRC Overseas Trade Statistics; ukmacro calculations"))


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


def build() -> None:
    mq = mq10()
    tiers = goods_tiers(mq) + services_tiers()
    write_csv(tiers, OUT / "ai_trade_tiers.csv")
    tier_charts(tiers)
    prods = products()
    write_csv(prods, OUT / "ai_trade_products.csv")
    product_charts(prods)
    by_country = services_by_country() + products_by_country()
    write_csv(by_country, OUT / "ai_trade_by_country.csv")
    write_csv(country_charts(by_country), OUT / "ai_trade_by_country_rolling.csv")
    write_csv(imf_price_charts(mq, prods), OUT / "ai_hardware_prices.csv")
    components, imf_quarterly = imf_component_charts()
    write_csv(components, OUT / "ai_hardware_components.csv")
    write_csv(ai_stack_charts(mq, prods, imf_quarterly, tiers), OUT / "ai_stack.csv")
    write_csv(top_partner_charts(), OUT / "ai_top_partners.csv")
    if hub_trade() is not None:
        write_csv(hub_summary(), OUT / "ai_hub_origins.csv")
    chain = chip_supply_chain_chart()
    if chain:
        write_csv(chain, OUT / "ai_chip_supply_chain.csv")
    summary = product_summary(prods)
    write_csv(summary, OUT / "ai_products_summary.csv")
    write_markdown_tables(summary, OUT / "ai_products_summary.md")
    for kind in ("goods", "services"):
        for tier in DEFS[f"{kind}_tiers"]:
            last = [r for r in tiers if r["kind"] == kind and r["tier"] == tier]
            q = max(r["quarter"] for r in last)
            vals = {f"{r['partner']} {r['flow']}": r["value_gbp_m"] for r in last if r["quarter"] == q}
            print(f"[ai-trade] {kind} {tier} {q}: " + ", ".join(f"{k} £{v / 1000:.1f}bn" for k, v in vals.items()))


if __name__ == "__main__":
    build()
