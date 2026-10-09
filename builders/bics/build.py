#!/usr/bin/env python3
"""BICS builder: harvest new waves, then build the curated series in series.yaml.

Step 1 (harvest): download only the files needed: the newest wave (its question log
records where every question last appeared), and for each question series.yaml uses,
the newest wave that asked it, unless already harvested (see ukmacro/bics.py).

Step 2 (curate): for every entry in series.yaml, find its question in the catalogue,
compute the measure for every wave x breakdown (total, each industry, each size band),
and write
    data/bics/bics_series.csv      the complete curated dataset, long format
    data/bics/series/<id>.json     one chart file per series
    data/bics/index.json           list of series with freshness
    data/bics/charts/<slug>.json   charts listed under `charts:` in series.yaml,
    img/bics/<slug>.png            with their PNGs in the house style

Measures (set per series in series.yaml):
    share       sum of the listed answers                          (% of businesses)
    complement  100 minus the sum of the listed answers            (e.g. "uses AI" = 100 - "does not use AI")
    net         sum of `up` answers minus sum of `down` answers   (balance, % points)
  + exclude:    optional answers to drop from the base first (e.g. Not sure, Not applicable)

Answers match exactly (ignoring case/quotes/spaces); end one with '*' to match every
answer that starts with it, which catches options ONS has reworded over time.

A series can join several `versions` of a reworded question (see series.yaml). The
CSV's `version` column records which version each value came from, and each chart
file lists `version_breaks`: where levels either side may not be comparable.

Run by hand:  .venv/bin/python builders/bics/build.py              (harvest + curate)
              .venv/bin/python builders/bics/build.py --no-fetch     (curate only)
              .venv/bin/python builders/bics/build.py --local DIR    (use wave files already in DIR)
"""

from __future__ import annotations

import csv
import json
import re
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from ukmacro import bics, charts  # noqa: E402

OUT = REPO / "data" / "bics"
SOURCE = "ONS Business Insights and Conditions Survey (BICS), weighted estimates"
SOURCE_URL = "https://www.ons.gov.uk" + bics.DATASET
GROUP_ORDER = {"total": 0, "size": 1, "industry": 2}


def breakdown_sort_key(b: str):
    """Total first, then size bands smallest to largest, then industries A-Z."""
    g = bics.breakdown_group(b)
    m = re.match(r"(\d+)", b)
    return (GROUP_ORDER[g], int(m.group(1)) if g == "size" and m else 10**6, b)


def slug(text: str) -> str:
    """'Wholesale and retail trade; ...' -> 'wholesale-and-retail-trade-...' (chart column keys)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------- resolving a series spec

def find_question(spec: dict, catalogue: dict) -> dict:
    """The single catalogue row matching the spec's question text (+ population/weighting)."""
    q = bics.norm(spec["question"])
    weighting = spec.get("weighting", "count")
    hits = [r for r in catalogue.values()
            if q in bics.norm(r["question"]) and r["weighting"] == weighting
            and bics.norm(spec.get("population", "")) in bics.norm(r["population"])]
    if len(hits) > 1:  # prefer an exact match on the question, then one starting with the text,
        exact = [r for r in hits if bics.norm(r["question"]) == q]  # then on the population
        starts = [r for r in hits if bics.norm(r["question"]).startswith(q)]
        hits = exact or starts or hits
    if len(hits) > 1 and spec.get("population"):
        exact = [r for r in hits if bics.norm(r["population"]) == bics.norm(spec["population"])]
        hits = exact or hits
    if len(hits) > 1:  # a reworded copy whose waves the newest version already covers adds nothing
        top = max(hits, key=lambda r: (int(r["last_wave"]), int(r["n_waves"])))
        if all(int(top["first_wave"]) <= int(r["first_wave"]) and int(top["n_waves"]) >= int(r["n_waves"])
               and bics.norm(top["population"]) == bics.norm(r["population"]) for r in hits):
            hits = [top]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        words = set(q.split())
        near = sorted(catalogue.values(), key=lambda r: -len(words & set(bics.norm(r["question"]).split())))[:5]
        raise LookupError(f"no {weighting}-weighted question contains {spec['question']!r}. Closest:\n"
                          + "\n".join(f"      - {r['question']}  [{r['weighting']}]" for r in near))
    raise LookupError(f"{spec['question']!r} matches {len(hits)} questions; add more of the text or a "
                      "`population:` line to pick one:\n"
                      + "\n".join(f"      - {r['question']}  |  {r['population']}" for r in hits))


def match_answers(wanted: list[str], available: set[str]) -> set[str]:
    """Answer labels in the harvest matching the spec's list (exact, or prefix with '*')."""
    out = set()
    for w in wanted:
        # YAML reads a bare Yes/No as true/false; turn them back into answer text
        w = {True: "Yes", False: "No"}.get(w, w) if isinstance(w, bool) else str(w)
        if w.endswith("*"):
            got = {a for a in available if bics.norm(a).startswith(bics.norm(w[:-1]))}
        else:
            got = {a for a in available if bics.norm(a) == bics.norm(w)}
        if not got:
            raise LookupError(f"answer {w!r} not found; this question's answers are: "
                              + " | ".join(sorted(available)))
        out |= got
    return out


# ---------------------------------------------------------------- computing a series

def compute(spec: dict, rows: list[tuple[int, str, str, float]]) -> dict[tuple[int, str], float]:
    """{(wave, breakdown): value} for one series."""
    available = {r[2] for r in rows}
    measure = spec.get("measure", "share")
    if measure == "net":
        up = match_answers(spec["answers"]["up"], available)
        down = match_answers(spec["answers"]["down"], available)
        needed = up | down
    else:
        up, down = match_answers(spec["answers"], available), set()
        needed = up
    excl = match_answers(spec.get("exclude", []), available)

    cells: dict[tuple[int, str], dict[str, float]] = {}
    in_wave: dict[int, set[str]] = {}
    for w, b, a, v in rows:
        cells.setdefault((w, b), {})[a] = v
        in_wave.setdefault(w, set()).add(a)

    out = {}
    for (w, b), vals in cells.items():
        # an answer published for this wave in other breakdowns but missing here was
        # suppressed ([c]); summing without it would understate, so skip the cell
        req = (needed | excl) & in_wave[w]
        if not req & needed or any(a not in vals for a in req):
            continue
        def s(labels):  # sum of these answers in this cell
            return sum(vals[a] for a in labels if a in vals)

        if measure == "net":
            v = s(up) - s(down)
        elif measure == "complement":
            v = 100 - s(up)
        elif measure == "share":
            v = s(up)
        else:
            raise ValueError(f"unknown measure {measure!r}")
        base = 100 - s(excl)
        if excl:
            if base <= 0:
                continue
            v = v * 100 / base
        out[(w, b)] = round(v, 2)
    return out


def versions_of(spec: dict) -> list[dict]:
    """A series is one question, or several `versions` (newest/preferred first) that
    each inherit the series' fields unless they set their own."""
    base = {k: v for k, v in spec.items() if k != "versions"}
    return [{**base, **v} for v in spec["versions"]] if spec.get("versions") else [base]


def build_series(spec: dict, store: bics.Store) -> tuple[dict, dict, list[dict]]:
    """-> (values {(wave, breakdown): v}, version used per cell, version metadata)."""
    values, used, meta = {}, {}, []
    for i, ver in enumerate(versions_of(spec), start=1):
        q = find_question(ver, store.catalogue)
        vals = compute(ver, store.load(q["id"]))
        if ver.get("waves"):  # [from, to] inclusive; to may be left out for open-ended
            lo, hi = (list(ver["waves"]) + [None])[:2]
            vals = {k: v for k, v in vals.items() if k[0] >= lo and (hi is None or k[0] <= hi)}
        for k, v in vals.items():
            if k not in values:  # earlier versions take priority where they overlap
                values[k], used[k] = v, i
        ws = sorted({w for (w, _), j in used.items() if j == i})
        meta.append({"version": i, "question": q["question"], "population": q["population"],
                     "weighting": q["weighting"],
                     "waves_used": f"{ws[0]}-{ws[-1]} ({len(ws)})" if ws else "none"})
    keep = spec.get("breakdowns", "all")
    if keep != "all":
        keep_n = {bics.norm(k) for k in keep}
        values = {k: v for k, v in values.items() if bics.norm(k[1]) in keep_n}
    if not values:
        raise ValueError("no data points after matching answers")
    return values, used, meta


def version_breaks(used: dict) -> list[dict]:
    """Waves where the 'All businesses' series switches to a different question version.
    Levels either side are not necessarily comparable; charts should show a break."""
    seq = sorted((w, v) for (w, b), v in used.items() if b == "All businesses")
    return [{"wave": w, "from_version": a, "to_version": v}
            for (_, a), (w, v) in zip(seq, seq[1:]) if a != v]


def chart_json(spec: dict, meta: list[dict], values: dict, waves: dict, used: dict) -> dict:
    """One series as a chart file: one column per breakdown, one row per wave, dated
    by the end of the wave's reference period."""
    breakdowns = sorted({b for _, b in values}, key=breakdown_sort_key)
    by_wave: dict[int, dict] = {}
    for (w, b), v in values.items():
        by_wave.setdefault(w, {})[slug(b)] = v
    data = [{"date": waves.get(w, {}).get("ref_end"), "wave": w, **by_wave[w]} for w in sorted(by_wave)]
    net = spec.get("measure") == "net"
    return {
        "slug": spec["id"], "category": "bics", "topic": spec["topic"], "title": spec["label"],
        "type": "line", "freq": "irregular (BICS waves)",
        "units": "Net balance, % points" if net else "% of businesses",
        "source": SOURCE, "source_url": SOURCE_URL, "note": spec.get("note"),
        "measure": spec.get("measure", "share"), "answers": spec.get("answers"),
        "exclude": spec.get("exclude"), "breaks": spec.get("breaks"),
        "versions": meta,
        "version_breaks": version_breaks(used),
        "series": [{"key": slug(b), "label": b, "group": bics.breakdown_group(b)} for b in breakdowns],
        "data_through": data[-1]["date"] if data else None,
        "status": "ok",
        "data": data,
    }


# ---------------------------------------------------------------- charts

def build_charts(cfg: dict, built: dict[str, dict]) -> list[str]:
    """Draw each chart in series.yaml's `charts:` section from the series just built:
    one line per {id, breakdown}, dated by the end of each wave's reference period.
    Writes data/bics/charts/<slug>.json and img/bics/<slug>.png. Returns problems."""
    problems = []
    for spec in cfg.get("charts", []):
        lines, columns = [], {}
        for line in spec["series"]:
            sid, breakdown = line["id"], line.get("breakdown", "All businesses")
            if sid not in built:
                problems.append(f"chart {spec['slug']}: series {sid!r} was not built")
                continue
            key = f"{sid}__{slug(breakdown)}"
            columns[key] = {d["date"]: d.get(slug(breakdown)) for d in built[sid]["data"]}
            lines.append({"key": key, "label": line.get("label", built[sid]["title"])})
        dates = sorted({d for col in columns.values() for d in col if d})
        data = [{"date": d, **{k: col.get(d) for k, col in columns.items()}} for d in dates]
        if not data:
            problems.append(f"chart {spec['slug']}: no data")
            continue
        chart = {"slug": spec["slug"], "category": "bics", "title": spec["title"], "type": "line",
                 "freq": "irregular (BICS waves)", "units": spec["units"], "source": SOURCE,
                 "note": spec.get("note"), "series": lines, "data_through": dates[-1],
                 "status": "ok", "data": data}
        charts.publish(chart, OUT / "charts" / f"{spec['slug']}.json",
                       REPO / "img" / "bics" / f"{spec['slug']}.png")
        print(f"[bics] chart {spec['slug']}: {len(lines)} lines, {len(data)} waves")
    return problems


# ---------------------------------------------------------------- harvesting

def wanted_waves(cfg: dict, store: bics.Store) -> tuple[set[int], list[str]]:
    """For each question the series use: the version's pinned `wave:`, else the last
    wave the question log says it was asked (that file holds its full history)."""
    wanted, problems = set(), []
    for raw in cfg["series"]:
        for ver in versions_of({**cfg.get("defaults", {}), **raw}):
            w = ver.get("wave") or bics.last_asked(store.log, ver["question"])
            if w:
                wanted.add(int(w))
            else:
                problems.append(f"{raw['id']}: {ver['question']!r} not in the question log; "
                                "add `wave: <N>` (the last wave that asked it) to this version")
    return wanted, problems


def harvest(cfg: dict, store: bics.Store, local_dir: Path | None) -> list[str]:
    """Download (or read from `local_dir`) every wave file not yet harvested that is
    needed. Returns problems to report (questions that couldn't be located)."""
    index = bics.list_waves()
    # newest wave first: its question log says where every other question last appeared
    bics.fetch_waves(store, {max(index)}, index, local_dir)
    # from then on, every new wave is harvested as it is published (one file a fortnight),
    # so series pinned to an old file keep updating once ONS asks the question again
    follow = store.state.setdefault("follow_from", max(index))
    wanted, problems = wanted_waves(cfg, store)
    wanted |= {w for w in index if w > follow}
    bics.fetch_waves(store, wanted, index, local_dir)
    store.state["latest_published"] = max(index)
    return problems


# ---------------------------------------------------------------- main

def main(fetch: bool = True, local_dir: Path | None = None) -> int:
    """Harvest, then build every series in series.yaml. Returns the exit code: 1 if
    anything failed (the other series are still written)."""
    failures = []
    cfg = yaml.safe_load((HERE / "series.yaml").read_text())
    defaults = cfg.get("defaults", {})
    store = bics.Store(OUT)
    if fetch:
        try:
            failures += harvest(cfg, store, local_dir)
        except Exception as e:  # noqa: BLE001 — keep going with what is already harvested
            traceback.print_exc()
            failures.append(f"harvest: {e}")
        store.save()

    series_dir = OUT / "series"
    series_dir.mkdir(parents=True, exist_ok=True)
    long_rows, index, written, built = [], [], set(), {}

    for raw in cfg["series"]:
        spec = {**defaults, **raw}
        try:
            values, used, meta = build_series(spec, store)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{spec['id']}: {e}")
            continue
        chart = chart_json(spec, meta, values, store.waves, used)
        built[spec["id"]] = chart
        (series_dir / f"{spec['id']}.json").write_text(json.dumps(chart, indent=1) + "\n")
        written.add(f"{spec['id']}.json")
        weighting = meta[0]["weighting"]
        for (w, b), v in sorted(values.items()):
            p = store.waves.get(w, {})
            long_rows.append([spec["id"], spec["topic"], spec["label"], chart["measure"], weighting,
                              w, p.get("ref_start"), p.get("ref_end"), bics.breakdown_group(b), b, v,
                              used[(w, b)]])
        total = [d for d in chart["data"] if "all-businesses" in d]
        index.append({"id": spec["id"], "topic": spec["topic"], "title": spec["label"],
                      "n_waves": len(chart["data"]), "first": chart["data"][0]["date"],
                      "data_through": chart["data_through"],
                      "latest_total": total[-1]["all-businesses"] if total else None,
                      "versions": len(meta)})
        print(f"[bics] {spec['id']}: {len(chart['data'])} waves, {len(chart['series'])} breakdowns"
              + (f", {len(meta)} versions" if len(meta) > 1 else ""))

    # a series removed from series.yaml should disappear from the outputs too
    for old in series_dir.glob("*.json"):
        if old.name not in written and not any(f.startswith(old.stem + ":") for f in failures):
            old.unlink()

    with (OUT / "bics_series.csv").open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["series_id", "topic", "label", "measure", "weighting", "wave",
                     "ref_start", "ref_end", "group", "breakdown", "value", "version"])
        wr.writerows(long_rows)
    (OUT / "index.json").write_text(json.dumps(
        {"category": "bics", "title": "Business Insights and Conditions Survey",
         "latest_published": store.state.get("latest_published"),
         "series": index}, indent=1) + "\n")

    failures += build_charts(cfg, built)

    if failures:
        print(f"\n{len(failures)} problem(s):", *failures, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    local = Path(args[args.index("--local") + 1]) if "--local" in args else None
    sys.exit(main(fetch="--no-fetch" not in args, local_dir=local))
