#!/usr/bin/env python3
"""Investment builder.

1. Headline charts from config.yaml: business vs total investment, business investment
   by asset, G7 total investment.
2. analysis.py: which assets drove the change since 2019, OBR forecasts vs outturn,
   and firms' expectations (Decision Maker Panel) vs outturn.

If the analyses fail the headline charts still publish, but the run exits 1.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # repo root, so `ukmacro` imports

from ukmacro.builder import run  # noqa: E402

import analysis  # noqa: E402

if __name__ == "__main__":
    status = run(HERE / "config.yaml")
    try:
        analysis.build()
    except Exception as e:  # noqa: BLE001
        print(f"analysis failed: {e}", file=sys.stderr)
        status = 1
    sys.exit(status)
