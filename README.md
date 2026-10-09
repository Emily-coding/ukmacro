# ukmacro

Automatically refreshed chart data for the UK economy in four areas: **GDP**,
**labour markets**, **investment** and **trade**, plus a cleaned, continuously
updated dataset built from the ONS **Business Insights and Conditions Survey (BICS)**. Data comes from the ONS, the OECD
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
  obr.py                 OBR spreadsheet downloads (no API: scrapes /download/ links),
                         incl. the historical forecasts database
  dmp.py                 Decision Maker Panel spreadsheets
  lastgood.py            last-good store (see below)
  builder.py             config.yaml -> chart JSON
  bics.py                BICS wave download, parsing and the harvest store
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

## BICS dataset

BICS is published as one spreadsheet per fortnightly wave, with questions rotating
in and out. The `bics` builder turns it into continuous series:

1. **Harvest (automatic, minimal downloads).** Each wave file carries the full
   history of every question it asks, so only the newest file asking a question is
   needed. The builder reads the newest wave's question log (which records the
   waves every question was asked in) and downloads just those files. After that,
   it takes each new wave as it is published, one file a fortnight. Sheets are
   merged into `data/bics/harvest/`, one CSV per question, and newer files win
   where they overlap, which picks up ONS revisions.
2. **Menus.** `data/bics/question_log.csv` lists every question BICS has ever
   asked and in which waves. `data/bics/catalogue.csv` lists the questions
   harvested so far, with population, weighting (by count or employment) and
   answer options.
3. **Curate (you edit this).** `builders/bics/series.yaml` lists the series you
   want: a few words of the question, the answers to add up, and a measure
   (share, net balance, or 100 minus). Instructions are at the top of the file.
   Every series is built for all businesses, each industry and each size band.
   Reworded questions can be joined as `versions`. Where a series switches version,
   the chart file lists a `version_breaks` entry and the CSV's `version` column
   changes: check the levels either side before reading a trend across it.

Outputs:
- `data/bics/bics_series.csv`: the complete curated dataset, long format
  (`series_id, topic, label, measure, weighting, wave, ref_start, ref_end, group, breakdown, value, version`)
- `data/bics/series/<id>.json`: one chart file per series, one column per breakdown
- `data/bics/index.json`: series list with coverage and the latest total
- `data/bics/charts/` and `img/bics/`: charts defined in the `charts:` section of
  `series.yaml` (e.g. AI adoption, kinds of AI, AI and headcount), as PNGs

```r
bics <- read.csv("https://raw.githubusercontent.com/Emily-coding/ukmacro/main/data/bics/bics_series.csv")
```

Caveats: values are percentages of *businesses* (a sole trader counts the same as
a large employer) unless `weighting: employment`. Points are irregular because
questions rotate, and are dated by the survey's reference period (two weeks early
on, a calendar month later). Suppressed cells (`[c]`) are dropped, and a
combined measure is left blank where any of its parts was suppressed.

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

## Charts as PNGs

`ukmacro/charts.py` renders any chart JSON to a PNG in one house style. Every chart
gets a PNG in `img/<category>/`, re-rendered only when its data changes.

- 25 x 15 cm at 200 dpi (1969 x 1181 px), 256-colour PNG, about 60 KB each
- Font: Source Sans 3 (open licence, bundled in `assets/fonts/`, so output matches on any machine)
- Colours: the "blue-amber" theme, built from the Blue, Yellow Vivid and Blue Grey
  scales of svengraziani/ui-design's professional UI palettes. Series in fixed order:
  blue `#186FAF`, amber `#DE911D`, teal `#27AB83`, red `#BA2525`. Totals in `#102A43`.
  White background, text `#102A43` / `#486581`, axes and source `#627D98`, gridlines
  `#D9E2EC`. Every series pair passes a colour-blind check. Other themes are in
  `THEMES` in `charts.py`; change `DEFAULT_THEME` to switch. The scheme, with R and
  Python snippets for reuse, is in `assets/colour-scheme.md` (and `.json`).

## Employment composition

`builders/labour-markets/composition.py` splits the change in the employment rate
since 2019 into a **composition** effect (the age x sex population mix shifting) and a
**within-group** effect (employment rates changing inside each group). It uses 12 LFS
groups (men and women x 16-17, 18-24, 25-34, 35-49, 50-64, 65+) and midpoint weights,
so the two parts add up to the total exactly. The rebuilt aggregate rates match the
published ones (16+ to 0.01pp). Women 65+ is derived as the 16+ total minus the other
bands, because ONS publishes no age-band series for that group.

`composition_rti.py` repeats this with HMRC PAYE RTI payrolled employees (by age
only: RTI has no split by sex) over ONS mid-year population estimates, and compares
LFS and RTI at the latest common quarter. Per-group workings for both are in
`data/labour-markets/*-composition-workings-*.csv`.

`neet.py` does the same for the NEET rate (16-24): four groups (men and women x
16-17 and 18-24) from ONS NEET table 1, with the within-group part split into
unemployed and economically inactive NEETs. In five quarters ONS suppressed one
part for 16-17s; those quarters show the within-group part unsplit (grey) rather
than deriving the suppressed figure.

## Investment

Headline charts (config.yaml): business vs total investment, business investment by
asset (intellectual property, buildings, ICT and machinery, transport; non-government
investment by asset excluding dwellings, which sums to business investment), and G7
total investment (the OECD has no harmonised business investment series).

`builders/investment/analysis.py`:
- **Asset contributions**: each asset's contribution to the change in business
  investment since 2019 Q4, in % points of the 2019 Q4 level.
- **OBR forecasts vs outturn**: each spring forecast since 2020 (OBR Historical
  official forecasts database). A forecast made in year Y starts from today's ONS
  outturn for Y-1 and chains the OBR's growth rates from Y, so the gap from the
  outturn is the forecast error in growth, separate from data revisions.
- **Firms' expectations vs outturn**: Decision Maker Panel expected growth in firms'
  capital spending over the next year, plotted at the quarter it refers to, against
  actual business investment growth.

## AI-relevant trade

`builders/trade/ai_trade.py`, with tiers and product codes in
`definitions/ai_trade.yaml` (built on the ONS AI thematic account's CPA list in
`definitions/ai_cpa.yaml`). Quarterly from 2016, EU vs non-EU:
- **Goods tiers** (ONS MQ10, exact CPA, seasonally adjusted): core = 26.1-26.3 and
  26.5-26.7; extended = all of C26-C28; full = C26-C30. Values, volumes (CVM) and
  implied prices.
- **Services tiers** (ONS QNA broad service types, seasonally adjusted): core = telecoms,
  computer and information plus IP charges; extended adds other business services;
  full adds personal and cultural. Approximates the CPA tiers.
- **Products** (HMRC, by commodity code): chips, servers, storage, graphics cards,
  phones, network equipment, sensors, cameras, scanners, robots, drones. Values,
  units and value per unit; not seasonally adjusted.
- **By partner** (EU, US, East Asia, rest of world): services
  use partner shares from the ONS by-country file applied to the latest QNA totals
  (suppressed partner values interpolated); products use HMRC country codes. Both
  are charted as rolling four-quarter totals.
All are upper bounds (whole product groups). EU imports have a break in 2022 Q1.
Key AI dates (`definitions/ai_events.yaml`) are drawn as vertical lines on the AI charts.
Outputs: `data/trade/ai/*.csv` and charts in `img/trade/ai/`.

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
