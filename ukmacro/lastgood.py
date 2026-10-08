"""Last-good store: the dated value each series last returned live.

If a fetch fails, the builder serves the series from here, tags it
`_source: last-good`, and the run exits nonzero so the failure is visible
(see README, "A failed fetch is a failed run").

An entry is rewritten only when the data itself changes, so a successful daily run
with no new release leaves the file — and the git history — untouched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class LastGood:
    """The last-good store for one category: {chart_slug/series_key: {stored, obs, ...meta}}."""

    def __init__(self, path: Path):
        self.path = path
        self.store: dict = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str) -> dict | None:
        """The stored entry for a series, or None if it has never been fetched."""
        return self.store.get(key)

    def put(self, key: str, obs: list[tuple[str, float]], meta: dict) -> None:
        """Record a successful fetch (only if the data changed)."""
        obs = [list(o) for o in obs]  # JSON round-trips tuples as lists; compare like with like
        old = self.store.get(key)
        if old and old["obs"] == obs:
            return
        self.store[key] = {"stored": date.today().isoformat(), "obs": obs, **meta}

    def save(self) -> None:
        """Write the store back to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.store, indent=0, sort_keys=True) + "\n")
