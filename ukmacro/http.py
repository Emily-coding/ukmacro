"""Shared HTTP helper: one place for the User-Agent, timeouts and retries.

Several UK sources (the BoE database in particular) reject requests that do not
look like a browser, so every client goes through `get` rather than calling
urllib directly.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (compatible; uk-macro/0.1; +https://github.com/) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)


def get(url: str, *, timeout: int = 60, retries: int = 3, backoff: float = 3.0) -> bytes:
    """GET a URL and return the body, retrying transient failures (5xx, 429, timeouts)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            # 4xx other than rate-limiting is our mistake (bad code, bad path): fail fast
            if (e.code < 500 and e.code != 429) or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(backoff * attempt)
    raise RuntimeError("unreachable")


def get_json(url: str, **kw):
    return json.loads(get(url, **kw))


def get_text(url: str, encoding: str = "utf-8", **kw) -> str:
    return get(url, **kw).decode(encoding)
