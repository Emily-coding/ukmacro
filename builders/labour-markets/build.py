#!/usr/bin/env python3
"""Labour markets builder.

1. Headline charts from config.yaml (employment, unemployment, vacancies, pay, G7).
2. Analyses, each in its own module in this folder:
     composition.py      how much of the change in the employment rate since 2019 is
                         the age/sex mix vs employment rates within groups (LFS)
     composition_rti.py  the same with HMRC PAYE RTI, and LFS vs RTI compared
     neet.py             the same for the NEET rate (16-24)

Each analysis is independent: if one fails the others still publish, but the run
exits 1 so the failure shows in GitHub Actions.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # repo root, so `ukmacro` imports

from ukmacro.builder import run  # noqa: E402

import composition  # noqa: E402
import composition_rti  # noqa: E402
import neet  # noqa: E402


def attempt(name, fn, *args):
    """Run one analysis; on failure print the error and return (None, False)."""
    try:
        return fn(*args), True
    except Exception as e:  # noqa: BLE001
        print(f"{name} failed: {e}", file=sys.stderr)
        return None, False


if __name__ == "__main__":
    ok = run(HERE / "config.yaml") == 0
    # the LFS age/sex data is fetched once and shared with the RTI comparison
    lfs_cells, ok1 = attempt("composition", composition.build)
    _, ok2 = attempt("composition_rti", composition_rti.build, lfs_cells)
    _, ok3 = attempt("neet", neet.build)
    sys.exit(0 if ok and ok1 and ok2 and ok3 else 1)
