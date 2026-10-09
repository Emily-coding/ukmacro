# NEXT — ukmacro

## Next

### Labour markets
- **How much of the employment fall is compositional?** Shift-share over age x
  sex cells: ΔE = Σ Δsᵢ·eᵢ,₂₀₁₉ (composition) + Σ sᵢ,ₜ·Δeᵢ (within-group).
  Chart: actual rate vs 2019 rates applied to today's population mix. Data: Nomis
  (APS `NM_17_5`, rolling year) or ONS table A05 (quarterly LFS by age, which is a
  spreadsheet). Decide 16+ vs 16-64 first: ageing does most of the compositional
  work in the 16+ rate. LFS population weights moved with the migration revisions,
  and those weights *are* sᵢ, so flag the vintage.
- ~~Employment composition~~ done (builders/labour-markets/composition.py).
- ~~NEETs~~ done (builders/labour-markets/neet.py). Possible extension: split
  inactive NEETs by reason (long-term sick / caring / other); needs the LFS
  inactivity-reason tables for 16-24s.
- ~~HMRC RTI as a cross-check~~ done (builders/labour-markets/composition_rti.py).

### GDP
- OBR forecast vs outturn: `obr.historical_forecasts("UKGDP")` already reads the
  database; reuse the investment chart's method (builders/investment/analysis.py).

### Investment
- ~~By asset, OBR forecasts vs outturn, DMP expectations, G7~~ done
  (builders/investment/).
- Business investment as a share of GDP (needs current-price series).
- DMP: other investment questions (uncertainty, hurdle rates, finance) are in the
  quarterly file; the monthly file has NICs and National Living Wage reactions,
  which would pair with the BICS employment-cost series.

### Trade
- **AI trade (builders/trade/ai_trade.py): still to do**
  - Look over the redrawn by-partner charts (rolling four-quarter totals) and the
    fuller products total; fix any layout problems.
  - Decide whether the EU / non-EU tier charts (quarterly, ONS seasonally adjusted)
    should also move to rolling four-quarter totals, to match the by-partner charts.
  - Possibly add an EU-by-country table (Netherlands, Germany, Ireland, Sweden...),
    since "EU" mixes entrepot trade, real EU assembly and one-off IP flows. Checked
    2026-10-09: Ireland is small in both services and products; the Netherlands
    (goods distribution hub) and a 2024 jump in IP-charge exports to Sweden matter more.
  - Confirm the scheduled workflow can commit new data (first live run around the
    mid-October releases).
- **Critical minerals**: `builders/trade/minerals.yaml` mapping each mineral
  (BGS Critical Minerals Intelligence Centre list) to CN8 codes, pulled monthly
  from uktradeinfo by partner country. Building the code mapping is the real work.
- Comtrade (needs a free key → repo secret) for other countries' minerals trade.
- Headline trade excluding precious metals.

### BICS
- Labour-market health indicators from outside BICS (BICS hasn't asked about
  sickness since the pandemic): ONS inactivity due to long-term sickness, and the
  ONS sickness absence estimates. These go in the labour-markets builder.
- Pandemic-era questions that only exist in per-wave sheets (no time-series sheet)
  aren't harvested. Add a per-wave parser only if one is needed.
- Possible further series: prices paid and price expectations, main concern,
  skills in high demand, variable hours contracts, support for unpaid carers.

### Infrastructure
- A static preview page reading `data/*/index.json`.
- Create the GitHub repo, push, and run each workflow once by hand
  (`workflow_dispatch`) to confirm Actions can push.

## Decided against
- **Scheduling builds from the ONS release calendar.** Checking a source costs
  almost nothing and commits happen only on change, so a fixed weekday cron is
  simpler and can't miss a moved release. The calendar is still used for the
  `next_release` labels.
- **The retired `api.ons.gov.uk` time-series API.** It was switched off. The site's
  own `/timeseries/<cdid>/<dataset>/data` JSON is used instead, with paths looked up
  through `api.beta.ons.gov.uk` search.
