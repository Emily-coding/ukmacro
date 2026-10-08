# uk-macro

Automatically refreshed chart data for the UK economy in four areas: **GDP**,
**labour markets**, **investment** and **trade**. Data comes from the ONS, the OECD
(for international comparisons), the Bank of England and the OBR. The layout is
modelled on [econvitals/econvitals-data](https://github.com/econvitals/econvitals-data).

Each area has a *builder* that GitHub Actions runs every weekday morning. It
fetches the latest data, writes chart JSON into `data/<area>/` and commits only
when something has actually changed, so the git history is a log of real data
releases.

## Layout

```
ukmacro/                 shared source clients + the chart builder
  ons.py                 ONS time series by CDID (path lookup cached in ons_uris.json)
  oecd.py                OECD SDMX API
  boe.py                 Bank of England statistics database (CSV)
  nomis.py               Nomis (APS/LFS breakdowns)
  hmrc_trade.py          HMRC uktradeinfo (trade by CN8 code x country)
  obr.py                 OBR spreadsheet downloads (no API: scrapes /download/ links)
  lastgood.py            last-good store (see below)
  builder.py             config.yaml -> chart JSON
builders/<area>/
  config.yaml            which charts, which series: edit this to add a chart
  build.py               runs the config; bespoke analyses go here too
data/<area>/
  <slug>.json            one file per chart
  index.json             chart list with data_through / next_release / status
  last-good.json         last live value of every series
scripts/check_sources.py one known-good request per source: run when something goes red
.github/workflows/       one workflow per area, sharing _refresh.yml
NEXT.md                  to-do list + "Decided against"
```

## Running locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python builders/gdp/build.py
.venv/bin/python scripts/check_sources.py
```

No API keys are needed for anything currently configured. UN Comtrade (planned)
will need one: put it in a repo secret, never in the code.

## Adding a chart

Add an entry to `builders/<area>/config.yaml`. An ONS series needs its CDID and
dataset, which are shown on the series page, e.g. `.../timeseries/npel/qna` →
`cdid: NPEL, dataset: QNA`. The builder finds the URL path itself the first time
and caches it in `ukmacro/ons_uris.json`. Chart options are documented at the top
of `ukmacro/builder.py`.

## Chart JSON

```json
{"slug": "gdp-level", "category": "gdp", "title": "...", "type": "line", "freq": "Q",
 "units": "Index, 2019 Q4 = 100", "source": "...", "note": "...",
 "series": [{"key": "gdp", "label": "GDP", "_source": "live", "_date": "2026-Q2", "source_url": "..."}],
 "data_through": "2026-Q2", "next_release": "2026-11-12", "status": "ok",
 "data": [{"date": "2026-Q2", "gdp": 106.2, "gdp_per_head": 101.7}]}
```

Dates are `YYYY`, `YYYY-Qn` or `YYYY-MM` for every source. `next_release` comes
from the ONS series metadata.

## Rules

**A failed fetch is a failed run.** If a source fails, the chart is still written
using that series' entry in `last-good.json`. The series is tagged
`_source: last-good`, the chart's `status` becomes `stale`, and the build exits 1
so the Action goes red. The commit step runs regardless, so a stale-but-labelled
chart still publishes. Nothing is ever silently passed off as fresh.

**Commit only on change.** Output files contain no build timestamps, and
`last-good.json` entries are rewritten only when the data changes. A run on a day
with no new releases therefore produces no commit.

**Push with retry.** Area jobs can finish at the same moment. The commit step
rebases and retries up to five times. Keep that loop in any new workflow.

## Data caveats

- **LFS** (employment, unemployment, inactivity): falling response rates and
  reweighting mean ONS labels these estimates "official statistics in development".
  Check headline LFS moves against HMRC RTI payrolled employees.
- **Trade**: headline totals include precious metals, which can swing monthly
  figures by billions.
- **OBR** forecasts are only published as spreadsheets. Each vintage is saved
  under its own name and old ones are never overwritten.
