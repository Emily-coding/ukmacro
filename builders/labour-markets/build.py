#!/usr/bin/env python3
"""Builder for this category: headline charts come from config.yaml.

Bespoke analyses (e.g. a decomposition that needs more than plotting a series)
go below `run(...)` as their own functions writing into the same data/ folder.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # repo root, so `ukmacro` imports

from ukmacro.builder import run  # noqa: E402

import composition  # noqa: E402  (age/sex composition of the employment rate, + PNGs)

if __name__ == "__main__":
    status = run(HERE / "config.yaml")
    try:
        composition.build()
    except Exception as e:  # noqa: BLE001 — keep the headline charts; still fail the run
        print(f"composition failed: {e}", file=sys.stderr)
        status = 1
    sys.exit(status)
