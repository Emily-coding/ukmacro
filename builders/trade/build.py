#!/usr/bin/env python3
"""Trade builder.

1. Headline charts from config.yaml (exports, imports, trade balance).
2. ai_trade.py: AI-relevant trade in goods and services (tiers, EU / non-EU, values,
   volumes and prices) and a product layer from HMRC; see definitions/ai_trade.yaml.

If the AI trade analysis fails the headline charts still publish, but the run exits 1.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # repo root, so `ukmacro` imports

from ukmacro.builder import run  # noqa: E402

import ai_trade  # noqa: E402

if __name__ == "__main__":
    status = run(HERE / "config.yaml")
    try:
        ai_trade.build()
    except Exception as e:  # noqa: BLE001
        print(f"ai_trade failed: {e}", file=sys.stderr)
        status = 1
    sys.exit(status)
