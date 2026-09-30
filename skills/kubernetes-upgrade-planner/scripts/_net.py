"""Small cached HTTP GET used by fetch_eol.py and check_compat.py.

Only these hosts are allowed, so a script can't be pointed anywhere else:
endoflife.date, compatibility.fyi, raw.githubusercontent.com.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOSTS = {"endoflife.date", "compatibility.fyi", "raw.githubusercontent.com"}
DEFAULT_CACHE = pathlib.Path.home() / ".cache" / "kubernetes-upgrade-planner"


def fetch(url: str, cache_dir: pathlib.Path | None = None, offline: bool = False,
          max_age: int = 24 * 3600, timeout: int = 20) -> tuple[str | None, dict]:
    """Return (body, info). info has source=network|cache|none and fetchedAt."""
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host not allowed: {host}")
    cache_dir = cache_dir or DEFAULT_CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_dir / hashlib.sha256(url.encode()).hexdigest()[:24]
    meta = key.with_suffix(".meta.json")
    cached = key.exists() and meta.exists()
    if cached:
        info = json.loads(meta.read_text())
        if offline or time.time() - info.get("ts", 0) < max_age:
            return key.read_text(), {"source": "cache", "fetchedAt": info.get("fetchedAt"), "url": url}
    if offline:
        return None, {"source": "none", "url": url, "error": "offline and not cached"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kubernetes-upgrade-planner/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if cached:
            info = json.loads(meta.read_text())
            return key.read_text(), {"source": "cache", "stale": True, "fetchedAt": info.get("fetchedAt"),
                                     "url": url, "error": str(exc)}
        return None, {"source": "none", "url": url, "error": str(exc)}
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    key.write_text(body)
    meta.write_text(json.dumps({"ts": time.time(), "fetchedAt": fetched_at, "url": url}))
    return body, {"source": "network", "fetchedAt": fetched_at, "url": url}
