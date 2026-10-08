"""Config-driven chart builder shared by every category.

A category's `config.yaml` lists charts; each chart lists series from one of the
source clients. For every chart this writes `data/<category>/<slug>.json` in one
common format, plus `data/<category>/index.json` (the chart list with freshness)
and `data/<category>/last-good.json`.

Series spec, by source:
    ons:  {source: ons, key, label, cdid, dataset}
    oecd: {source: oecd, flow, key, areas: {GBR: United Kingdom, ...}}
          `key` contains "{areas}", replaced by the '+'-joined area codes, and each
          area becomes its own series (keyed by lower-cased area code).
    boe:  {source: boe, key, label, code}

Chart options: slug, title, units, freq (A/Q/M), type (line/bar), start, rebase
(a date: divide by the value then and multiply by 100), source, note.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import date
from pathlib import Path

import yaml

from . import boe, oecd, ons
from .lastgood import LastGood

REPO = Path(__file__).resolve().parent.parent


def _fetch(spec: dict, freq: str) -> list[tuple[str, str, list, dict]]:
    """Fetch one series spec -> [(key, label, obs, meta)]. Raises on any failure."""
    src = spec["source"]
    if src == "ons":
        r = ons.fetch(spec["cdid"], spec["dataset"], freq)
        meta = {"source_url": r["url"], "next_release": r["next_release"]}
        return [(spec["key"], spec["label"], r["obs"], meta)]
    if src == "oecd":
        areas = spec["areas"]
        res = oecd.fetch(spec["flow"], spec["key"].format(areas="+".join(areas)), spec.get("start", "2000"))
        missing = [a for a in areas if a not in res]
        if missing:
            raise ValueError(f"OECD returned no data for {missing}")
        return [(a.lower(), label, res[a], {"source_url": "https://data-explorer.oecd.org"})
                for a, label in areas.items()]
    if src == "boe":
        res = boe.fetch([spec["code"]])
        return [(spec["key"], spec["label"], res[spec["code"]],
                 {"source_url": "https://www.bankofengland.co.uk/boeapps/database/"})]
    raise ValueError(f"unknown source {src!r}")


def _expected_keys(spec: dict) -> list[tuple[str, str]]:
    """The (key, label) pairs a spec should produce — used to fall back on failure."""
    if spec["source"] == "oecd":
        return [(a.lower(), label) for a, label in spec["areas"].items()]
    return [(spec["key"], spec["label"])]


def _transform(obs: list, chart: dict) -> list:
    """Apply the chart's `start` (drop earlier dates) and `rebase` (index = 100 then)."""
    if chart.get("start"):
        obs = [o for o in obs if o[0] >= chart["start"]]
    if chart.get("rebase"):
        base = dict((d, v) for d, v in obs).get(chart["rebase"])
        if base is None:
            raise ValueError(f"rebase date {chart['rebase']} not in series")
        obs = [(d, round(v / base * 100, 3)) for d, v in obs]
    return obs


def build_chart(chart: dict, category: str, lg: LastGood, failures: list[str]) -> dict:
    """Fetch every series in one chart spec and assemble the chart file. A series that
    fails is served from last-good (tagged `_source: last-good`) and the failure is
    appended to `failures`."""
    series, columns = [], {}
    releases = []
    for spec in chart["series"]:
        try:
            fetched = _fetch(spec, chart["freq"])
            for key, label, obs, meta in fetched:
                lg.put(f"{chart['slug']}/{key}", obs, meta)
            rows = [(k, l, o, m, "live") for k, l, o, m in fetched]
        except Exception as e:  # noqa: BLE001 — any failure falls back to last-good
            failures.append(f"{chart['slug']}: {spec.get('cdid') or spec.get('flow') or spec.get('code')}: {e}")
            traceback.print_exc()
            rows = []
            for key, label in _expected_keys(spec):
                old = lg.get(f"{chart['slug']}/{key}")
                if old:
                    meta = {k: v for k, v in old.items() if k not in ("obs", "stored")}
                    rows.append((key, label, [tuple(o) for o in old["obs"]], meta, "last-good"))
        for key, label, obs, meta, source in rows:
            obs = _transform(obs, chart)
            columns[key] = dict(obs)
            series.append({"key": key, "label": label, "_source": source,
                           "_date": obs[-1][0] if obs else None,
                           "source_url": meta.get("source_url")})
            if meta.get("next_release"):
                releases.append(meta["next_release"])

    dates = sorted({d for col in columns.values() for d in col})
    data = [{"date": d, **{k: col.get(d) for k, col in columns.items()}} for d in dates]
    upcoming = sorted(r for r in releases if r >= date.today().isoformat())
    return {
        "slug": chart["slug"],
        "category": category,
        "title": chart["title"],
        "type": chart.get("type", "line"),
        "freq": chart["freq"],
        "units": chart["units"],
        "source": chart["source"],
        "note": chart.get("note"),
        "series": series,
        "data_through": max((s["_date"] for s in series if s["_date"]), default=None),
        "next_release": upcoming[0] if upcoming else None,
        "status": "ok" if all(s["_source"] == "live" for s in series) and series else "stale",
        "data": data,
    }


def run(config_path: Path) -> int:
    """Build every chart in a category's config.yaml. Returns the exit code (1 if any
    fetch failed, after writing everything that could be written)."""
    cfg = yaml.safe_load(Path(config_path).read_text())
    category = cfg["category"]
    out_dir = REPO / "data" / category
    out_dir.mkdir(parents=True, exist_ok=True)
    lg = LastGood(out_dir / "last-good.json")
    failures: list[str] = []
    index = []

    for chart in cfg["charts"]:
        result = build_chart(chart, category, lg, failures)
        (out_dir / f"{chart['slug']}.json").write_text(json.dumps(result, indent=1) + "\n")
        index.append({k: result[k] for k in ("slug", "title", "data_through", "next_release", "status")})
        print(f"[{category}] {chart['slug']}: {result['status']}, through {result['data_through']}")

    lg.save()
    (out_dir / "index.json").write_text(
        json.dumps({"category": category, "title": cfg["title"], "charts": index}, indent=1) + "\n")

    if failures:
        print(f"\n{len(failures)} fetch failure(s):", *failures, sep="\n  ", file=sys.stderr)
        return 1
    return 0
