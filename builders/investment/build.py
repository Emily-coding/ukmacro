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

if __name__ == "__main__":
    sys.exit(run(HERE / "config.yaml"))
