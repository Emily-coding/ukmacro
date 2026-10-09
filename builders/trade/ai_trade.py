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
   applied to the latest QNA EU / non-EU totals (seasonally adjusted). Products: HMRC,
   seasonally adjusted here with STL. Goods tiers stay EU / non-EU (no crosswalk).
Key AI dates (definitions/ai_events.yaml) are drawn as vertical lines on the charts.

All quarterly from 2016 Q1. Values in £m; volumes and prices as indices, 2019 = 100.

Outputs:
    data/trade/ai/ai_trade_tiers.csv      goods and services tiers, long format
    data/trade/ai/ai_trade_products.csv   product layer, long format
    data/trade/ai/ai_trade_by_country.csv services tiers and products by partner group
    data/trade/ai/ai_trade_products_by_country_sa.csv  products total, unadjusted and adjusted
    data/trade/ai/<slug>.json + img/trade/ai/<slug>.png   charts
"""

from __future__ import annotations

import csv
import io
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from ukmacro import charts, ons  # noqa: E402
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
    url = f"{HMRC_OTS}?$apply={urllib.parse.quote(apply)}"
    rows = get_json(url, timeout=180)["value"]
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
            for option in ("option1", "option2"):
                parts = [by_type(t, flow, option) for t in spec["types"]]
                for group in group_members(option):
                    qs = sorted(set.intersection(*(set(p.get(group, {})) for p in parts)))
                    out += [{"kind": "services", "item": tier, "option": option, "group": group, "flow": flow,
                             "quarter": q, "value_gbp_m": round(sum(p[group][q] for p in parts), 1)} for q in qs]
    return out


def products_by_country() -> list[dict]:
    """HMRC product values by partner group (£m). EU vs non-EU comes from the flow type;
    non-EU partners from HMRC country codes."""
    alpha = {c["CountryId"]: (c["CountryCodeAlpha"] or "").strip()
             for c in get_json(f"{HMRC_COUNTRY}?$select=CountryId,CountryCodeAlpha", timeout=120)["value"]}
    out = []
    for p in DEFS["products"]:
        ranges = " or ".join(f"(CommodityId ge {c}00 and CommodityId le {c}99)" for c in p["hs6"])
        apply = (f"filter(MonthId ge {START[:4]}01 and ({ranges}))/groupby((MonthId,FlowTypeId,CountryId),"
                 "aggregate(Value with sum as Value))")
        data = get_json(f"{HMRC_OTS}?$apply={urllib.parse.quote(apply)}", timeout=180)["value"]
        cells: dict = {}   # (flow, country code or 'EU', quarter) -> £; plus months seen per quarter
        months: dict = {}
        for r in data:
            m = r["MonthId"]
            q = f"{m // 100}-Q{(m % 100 - 1) // 3 + 1}"
            partner, flow = FLOWS[r["FlowTypeId"]]
            code = "EU" if partner == "EU" else alpha.get(r["CountryId"], "")
            cells[(flow, code, q)] = cells.get((flow, code, q), 0.0) + (r["Value"] or 0)
            months.setdefault(q, set()).add(m)
        quarters = sorted(q for q, ms in months.items() if len(ms) == 3
                          and not (p.get("from") and int(q[:4]) < p["from"]))
        for flow in ("exports", "imports"):
            for option in ("option1", "option2"):
                named = {}
                for group, members in group_members(option).items():
                    if members == ["REST"]:
                        continue
                    named[group] = {q: sum(v for (f, c, qq), v in cells.items()
                                           if f == flow and qq == q and c in members) for q in quarters}
                if "Rest of world" in group_members(option):
                    total = {q: sum(v for (f, c, qq), v in cells.items() if f == flow and qq == q) for q in quarters}
                    named["Rest of world"] = {q: total[q] - sum(v[q] for v in named.values()) for q in quarters}
                for group, vals in named.items():
                    out += [{"kind": "product", "item": p["id"], "option": option, "group": group,
                             "flow": flow, "quarter": q, "value_gbp_m": round(v / 1e6, 2)} for q, v in vals.items()]
        print(f"[ai-trade] by country: {p['id']}")
    return out


def seasonal_adjust(series: dict[str, float]) -> dict[str, float]:
    """STL seasonal adjustment of a quarterly series (statsmodels STL, period 4,
    robust to outliers), on logs when all values are positive (multiplicative
    seasonality, as in trade data), otherwise on levels."""
    import numpy as np
    from statsmodels.tsa.seasonal import STL

    qs = sorted(series)
    y = np.array([series[q] for q in qs], dtype=float)
    if len(y) < 12:
        return dict(series)  # too short to estimate seasonality reliably
    use_log = (y > 0).all()
    fit = STL(np.log(y) if use_log else y, period=4, robust=True).fit()
    adj = (np.log(y) if use_log else y) - fit.seasonal
    return {q: float(np.exp(v) if use_log else v) for q, v in zip(qs, adj)}


def country_charts(rows: list[dict]) -> list[dict]:
    """Services tiers and the selected-products total, by partner group: one chart per
    (tier or products) x flow x grouping option, values in £bn, quarterly. Services are
    seasonally adjusted (via the QNA totals); the products total is seasonally adjusted
    here with STL. Returns the products-total rows (unadjusted and adjusted) for a CSV."""
    titles = {"option1": "by partner", "option2": "East Asia by country"}
    sources = {"services": "ONS trade in services by type (QNA, seasonally adjusted), split by partner using "
                           "shares from ONS trade in services by partner country; ukmacro calculations",
               "product": "HMRC Overseas Trade Statistics; seasonally adjusted by ukmacro (STL); "
                          "ukmacro calculations"}
    groups_of = {o: list(group_members(o)) for o in ("option1", "option2")}
    # products total: products with a full series only (smartphones are inside mobile
    # phones; codes created in 2022 would put a break in the total)
    total_products = [p["id"] for p in DEFS["products"] if p["id"] != "smartphones" and not p.get("from")]
    blocks = [("services", t, "AI-relevant services, " + DEFS["services_tiers"][t]["label"].split(":")[0].lower()
               + " tier", [t]) for t in DEFS["services_tiers"]]
    blocks.append(("product", "total", "selected AI-relevant products (goods)", total_products))
    sa_rows = []
    for kind, slug_part, what, items in blocks:
        for flow in ("exports", "imports"):
            for option in ("option1", "option2"):
                sums: dict = {}
                for r in rows:
                    if r["kind"] == kind and r["item"] in items and r["flow"] == flow and r["option"] == option:
                        sums.setdefault(r["group"], {})
                        sums[r["group"]][r["quarter"]] = sums[r["group"]].get(r["quarter"], 0.0) + r["value_gbp_m"]
                if kind == "product":
                    adjusted = {g: seasonal_adjust(v) for g, v in sums.items()}
                    sa_rows += [{"option": option, "group": g, "flow": flow, "quarter": q,
                                 "value_gbp_m": round(v[q], 1), "value_sa_gbp_m": round(adjusted[g][q], 1)}
                                for g, v in sums.items() for q in sorted(v)]
                    sums = adjusted
                quarters = sorted({q for v in sums.values() for q in v})
                data = [{"date": q, **{g: round(sums.get(g, {}).get(q, 0.0) / 1000, 2) for g in groups_of[option]}}
                        for q in quarters]
                note = UPPER_BOUND + "Seasonally adjusted. "
                if option == "option1":
                    note += "East Asia = China, Hong Kong, Macao, Japan, South Korea, Taiwan. "
                if kind == "services":
                    note += ("Partner shares from the by-country file are applied to the latest QNA EU and "
                             "non-EU totals, so these match the EU / non-EU charts; suppressed partner values "
                             "are interpolated. ")
                else:
                    note += ("Products: chips, servers, storage, graphics cards, mobile phones, network "
                             "equipment, cameras, medical scanners, industrial robots. EU trade is recorded by "
                             "country of dispatch, so goods routed via the EU count as EU. " + EU_BREAK)
                publish(chart(f"ai-trade-{kind}-{slug_part}-{flow}-{option}",
                              f"UK {flow} of {what}, {titles[option]}",
                              "£ billion per quarter", "line",
                              [{"key": g, "label": g} for g in groups_of[option]],
                              data, note, sources[kind]))
    return sa_rows


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
    tiers = goods_tiers(mq10()) + services_tiers()
    write_csv(tiers, OUT / "ai_trade_tiers.csv")
    tier_charts(tiers)
    prods = products()
    write_csv(prods, OUT / "ai_trade_products.csv")
    product_charts(prods)
    by_country = services_by_country() + products_by_country()
    write_csv(by_country, OUT / "ai_trade_by_country.csv")
    write_csv(country_charts(by_country), OUT / "ai_trade_products_by_country_sa.csv")
    for kind in ("goods", "services"):
        for tier in DEFS[f"{kind}_tiers"]:
            last = [r for r in tiers if r["kind"] == kind and r["tier"] == tier]
            q = max(r["quarter"] for r in last)
            vals = {f"{r['partner']} {r['flow']}": r["value_gbp_m"] for r in last if r["quarter"] == q}
            print(f"[ai-trade] {kind} {tier} {q}: " + ", ".join(f"{k} £{v / 1000:.1f}bn" for k, v in vals.items()))


if __name__ == "__main__":
    build()
