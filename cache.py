"""
Simple on-disk cache for WCL GraphQL responses.

Reports never change after they're uploaded, so any query that is tied
to a specific report code can be cached forever. This makes re-running
the dashboard nearly free after the first run, and keeps you well clear
of WCL's rate limits.

Two kinds of entry:
  cached_query(query, vars)   - keyed by sha1(query text + variables)
  get_entry(key) / put_entry  - keyed by an explicit string, used when one
                                HTTP request fetches data for several fights
                                (batched aliases) but each fight must stay
                                individually cacheable / refreshable.

Cached responses live in a `.cache/` folder next to this file. Delete
that folder if you ever want to force a full refetch.

Thread-safe: stats and file writes are guarded by a lock so fights can be
fetched from a small thread pool.
"""

import hashlib
import json
import os
import threading

from path import DATA_DIR
from wcl_client import run_query

CACHE_DIR = os.path.join(DATA_DIR, "cache")

# Run statistics, so you can see what actually hit the API
stats = {"api_calls": 0, "cache_hits": 0, "refreshed": 0}
FORCE_REFRESH = False   # set True (via --refresh) to ignore the cache entirely this run

_lock = threading.Lock()


def _bump(key: str, n: int = 1) -> None:
    with _lock:
        stats[key] += n


def _path_for(raw: str) -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{digest}.json")


def _cache_path(query: str, variables: dict) -> str:
    return _path_for(query + json.dumps(variables, sort_keys=True))


def _read(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, data) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = f"{path}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def cached_query(query: str, variables: dict, refresh: bool = False) -> dict:
    """
    Same as wcl_client.run_query, but reads from / writes to the local
    cache. Only use this for report-specific queries (fights, deaths,
    tables...) - NOT for the guild report list or report metadata, since
    those keep changing.

    refresh=True re-downloads even if cached (used for reports that may
    still be live-logging).
    """
    path = _cache_path(query, variables)
    exists = os.path.exists(path)

    if exists and not refresh and not FORCE_REFRESH:
        _bump("cache_hits")
        return _read(path)

    if exists:
        _bump("refreshed")
    data = run_query(query, variables)
    _bump("api_calls")
    _write(path, data)
    return data


def get_entry(key: str, refresh: bool = False):
    """Explicitly keyed entry, or None if missing (or refresh requested)."""
    path = _path_for("entry:" + key)
    if os.path.exists(path) and not refresh and not FORCE_REFRESH:
        _bump("cache_hits")
        return _read(path)
    return None


def put_entry(key: str, data) -> None:
    _write(_path_for("entry:" + key), data)


def count_api_call(n: int = 1, refreshed: int = 0) -> None:
    """For callers that run_query() themselves (batched requests) but should still show up in the summary."""
    _bump("api_calls", n)
    if refreshed:
        _bump("refreshed", refreshed)


def summary() -> str:
    return (f"WCL API calls this run: {stats['api_calls']} "
            f"(of which {stats['refreshed']} re-downloaded recent reports) - cache hits: {stats['cache_hits']}")
