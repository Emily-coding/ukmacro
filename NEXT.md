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
- **NEETs**: the same decomposition on the ONS quarterly NEET release
  (16-17, 18-24, by sex), then split by reason (unemployed / long-term sick /
  caring).
- HMRC RTI payrolled employees as a cross-check on the LFS.

### GDP
- OBR forecast vs outturn: parse the Historical official forecasts database
  (`obr.find("historical-official-forecasts")`, already reachable) and plot each
  EFO vintage's GDP path against the ONS outturn.

### Investment
- Business investment by asset (ONS business investment release).
- OBR business investment forecast vintages (same database as above).
- BoE Decision Maker Panel investment expectations.
- Business investment as a share of GDP, G7 comparison (OECD).

### Trade
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
