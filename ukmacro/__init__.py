"""ukmacro: shared code for the builders.

Source clients (one per publisher; each returns plain Python data):
    ons         ONS time series by CDID
    oecd        OECD SDMX API
    boe         Bank of England statistics database
    nomis       Nomis (APS / LFS breakdowns, population estimates)
    hmrc_trade  HMRC uktradeinfo (trade by commodity code and country)
    obr         OBR spreadsheet downloads
    bics        ONS Business Insights and Conditions Survey wave files

Shared machinery:
    http        GET with a browser User-Agent, retries and rate-limit handling
    builder     config.yaml -> chart JSON, with last-good fallback
    lastgood    the last-good store
    charts      chart JSON -> PNG in the house style
"""
