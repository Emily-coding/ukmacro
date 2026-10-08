#!/usr/bin/env python3
"""Smoke-test every source client with one small, known-good request.

Run this when a builder goes red to see whether a source itself is down or has
changed shape:  .venv/bin/python scripts/check_sources.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ukmacro import boe, hmrc_trade, nomis, obr, oecd, ons  # noqa: E402

CHECKS = {
    "ONS (ABMI real GDP)": lambda: ons.fetch("ABMI", "QNA", "Q")["obs"][-1],
    "OECD (UK unemployment)": lambda: oecd.fetch(
        "OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0", "GBR..._Z.Y._T.Y_GE15..M", "2025-01")["GBR"][-1],
    "BoE (Bank Rate)": lambda: boe.fetch(["IUDBEDR"], "01/Jan/2026")["IUDBEDR"][-1],
    "Nomis (APS employment rate 16-64)": lambda: nomis.fetch(
        "NM_17_5", geography="2092957697", date="latest", variable="45", measures="20599",
        select="date_name,obs_value")[0],
    "HMRC uktradeinfo (one CN8 code)": lambda: len(hmrc_trade.ots(28259060, 202501, 202501)),
    "OBR (download links)": lambda: sorted(obr.find("historical-official-forecasts")),
}

failed = 0
for name, check in CHECKS.items():
    try:
        print(f"ok    {name}: {check()}")
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"FAIL  {name}: {type(e).__name__}: {e}")
sys.exit(1 if failed else 0)
