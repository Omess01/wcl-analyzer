"""
Small wrapper around the Warcraft Logs v2 GraphQL API.

Handles:
- Getting an OAuth access token via the client_credentials flow
- Sending GraphQL queries with that token attached
- Timeouts, retries with backoff (429 / 5xx / network errors) and
  thread-safety, so a network blip does not abort a long build
- Rate-limit visibility: every request also asks for `rateLimitData`
  (points spent / limit / reset), prints one line per request and stops
  the build cleanly (WCLRateLimited) when the hourly points are exhausted
  and the reset is further away than WCL_RATE_WAIT_MAX seconds.
"""

import os
import re
import threading
import time

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"

REQUEST_TIMEOUT = float(os.getenv("WCL_TIMEOUT_SECONDS", "60"))
MAX_ATTEMPTS = int(os.getenv("WCL_MAX_ATTEMPTS", "4"))
# Longest we are willing to sleep for the hourly points to reset before giving up
# (new optional .env key; the default applies when it is absent).
WCL_RATE_WAIT_MAX = float(os.environ.get("WCL_RATE_WAIT_MAX", "900"))
# Fraction of limitPerHour at which a 429 means "the hour is spent" rather than a burst.
RATE_EXHAUSTED_FRACTION = 0.95
RATE_WAIT_MARGIN = 5.0   # extra seconds slept past pointsResetIn in case WCL rounds it down
# --refresh is refused when more than this fraction of the hour is already spent.
RATE_REFRESH_MAX_FRACTION = 0.8

_cached_token = None
_cached_token_expiry = 0
_token_lock = threading.Lock()
_session = requests.Session()

# Rate-limit bookkeeping. `last_rate` mirrors WCL's rateLimitData of the most
# recent successful response: {"limitPerHour", "pointsSpentThisHour", "pointsResetIn"}.
# Guarded by _rate_lock because fights are fetched from a small thread pool.
RATE_FIELDS = "rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }"
RATE_QUERY = "query RateLimit { " + RATE_FIELDS + " }"
_rate_lock = threading.Lock()
last_rate: dict = {}
_run_points = {"first_spent": None, "max_spent": 0.0, "last_spent": None,
               "last_reset_in": None, "prev_hours": 0.0, "requests": 0,
               "prev_op": None, "prev_sole": False}
# In-flight bookkeeping: a response's cost is only attributable when no other request overlapped it.
_flight = {"in": 0, "starts": 0}
_rate_headers_logged = False
_req_budget_warned = False
REQ_BUDGET_WARN_FRACTION = 0.10
_OPNAME_RE = re.compile(r"\bquery\s+([A-Za-z_][A-Za-z0-9_]*)")


class WCLError(RuntimeError):
    """GraphQL / HTTP failure of one request. Callers that can degrade gracefully catch this."""
    pass


class WCLRateLimited(RuntimeError):
    """
    The hourly point budget is exhausted and the reset is too far away to wait.
    Deliberately NOT a WCLError: the per-fight fetchers swallow WCLError and
    carry on with blank data, but a rate-limit stop must abort the whole build.
    """

    def __init__(self, message: str, reset_in: float | None = None,
                 spent: float | None = None, limit: float | None = None):
        super().__init__(message)
        self.reset_in = reset_in
        self.spent = spent
        self.limit = limit


def get_access_token():
    """
    Returns a valid access token, fetching a new one only if we don't
    have a cached one or it's expired. Tokens are typically valid for
    a long time, but we refresh defensively.
    """
    global _cached_token, _cached_token_expiry

    with _token_lock:
        if _cached_token and time.time() < _cached_token_expiry:
            return _cached_token

        client_id = os.getenv("WCL_CLIENT_ID")
        client_secret = os.getenv("WCL_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError(
                "WCL_CLIENT_ID / WCL_CLIENT_SECRET not set. "
                "Copy .env.example to .env and fill them in."
            )

        response = _session.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()

        _cached_token = payload["access_token"]
        # Refresh a little early (60s buffer) rather than exactly at expiry
        _cached_token_expiry = time.time() + payload.get("expires_in", 3600) - 60
        return _cached_token


def _retry_delay(attempt: int, response) -> float:
    """Seconds to wait before the next attempt: Retry-After if WCL sent one, else backoff."""
    if response is not None:
        ra = response.headers.get("Retry-After")
        if ra:
            try:
                return min(float(ra), 120.0)
            except ValueError:
                pass
    return min(2.0 * (2 ** attempt), 30.0)


# --- rate-limit helpers -----------------------------------------------------

def _with_rate_fields(query: str) -> str:
    """
    The text actually sent: the caller's query plus rateLimitData inside the
    outermost braces. The caller's string is never changed (cache keys hash it).
    """
    if "rateLimitData" in query:
        return query
    end = query.rstrip().rfind("}")
    if end < 0:
        return query
    return query[:end] + " " + RATE_FIELDS + " " + query[end:]


def _opname(query: str) -> str:
    m = _OPNAME_RE.search(query)
    return m.group(1) if m else "query"


def _fmt(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:.1f}"


def _header(headers, name: str):
    """Case-insensitive header lookup that also works on a plain dict."""
    if not headers:
        return None
    val = headers.get(name)
    if val is None:
        low = name.lower()
        for k, v in headers.items():
            if k.lower() == low:
                return v
    return val


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _post(sent_query: str, variables: dict | None):
    """
    One POST. Returns (response, sole): `sole` is True when no other request was in
    flight at any point while this one ran, i.e. the lagged points counter in its
    response is unambiguous.
    """
    with _rate_lock:
        _flight["in"] += 1
        _flight["starts"] += 1
        my_start = _flight["starts"]
        sole = _flight["in"] == 1
    try:
        token = get_access_token()
        response = _session.post(
            GRAPHQL_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"query": sent_query, "variables": variables or {}},
            timeout=REQUEST_TIMEOUT,
        )
    finally:
        with _rate_lock:
            _flight["in"] -= 1
            sole = sole and _flight["starts"] == my_start
    return response, sole


def _record_rate(rate: dict, opname: str, sole: bool = False, headers=None) -> None:
    """
    Store WCL's rateLimitData (+ the x-ratelimit-* request-count headers), print the
    per-request line and keep the run total.

    WCL's pointsSpentThisHour LAGS ONE REQUEST: a response reports the total before
    its own charge (measured 2026-10-01, docs/research/.../06-live-probe.md). So the
    difference to the previous response is the cost of the PREVIOUS operation, and
    only when neither request overlapped another one (WCL_PARALLEL > 1 makes the
    ordering ambiguous). Every line shows the running total; the previous op's cost is
    appended only when it is unambiguous.
    """
    try:
        spent = float(rate.get("pointsSpentThisHour") or 0)
        limit = float(rate.get("limitPerHour") or 0)
        reset_in = float(rate.get("pointsResetIn") or 0)
    except (TypeError, ValueError):
        return
    req_limit = _to_float(_header(headers, "x-ratelimit-limit"))
    req_remaining = _to_float(_header(headers, "x-ratelimit-remaining"))
    warn_budget = False
    with _rate_lock:
        global _req_budget_warned
        rp = _run_points
        prev_spent, prev_reset = rp["last_spent"], rp["last_reset_in"]
        cost_txt = ""
        if prev_spent is None:
            rp["first_spent"] = spent
        else:
            # pointsResetIn only ever counts down within an hour; a jump up while the
            # spent counter dropped means WCL started a new hour.
            rolled = spent < prev_spent and prev_reset is not None and reset_in > prev_reset + 60
            if rolled:
                rp["prev_hours"] += max(rp["max_spent"] - (rp["first_spent"] or 0.0), 0.0)
                rp["first_spent"], rp["max_spent"] = 0.0, 0.0
            elif sole and rp["prev_sole"] and rp["prev_op"]:
                cost_txt = f"; {rp['prev_op']} cost {_fmt(spent - prev_spent)} pts"
        rp["last_spent"], rp["last_reset_in"] = spent, reset_in
        rp["max_spent"] = max(rp["max_spent"], spent)
        rp["requests"] += 1
        rp["prev_op"], rp["prev_sole"] = opname, sole
        last_rate.clear()
        last_rate.update({"limitPerHour": limit, "pointsSpentThisHour": spent, "pointsResetIn": reset_in,
                          "req_limit": req_limit, "req_remaining": req_remaining,
                          "at": time.monotonic()})   # when pointsResetIn was read
        if (req_limit and req_remaining is not None and not _req_budget_warned
                and req_remaining < REQ_BUDGET_WARN_FRACTION * req_limit):
            _req_budget_warned = warn_budget = True
    print(f"  [wcl] {opname} {_fmt(spent)}/{_fmt(limit)} pts this hour, reset in {_fmt(reset_in)} s{cost_txt}")
    if warn_budget:
        print(f"  [wcl] warning: only {_fmt(req_remaining)} of {_fmt(req_limit)} requests left in WCL's "
              f"request-count window (x-ratelimit-remaining); the build may start seeing 429s")


def _exhausted() -> tuple[bool, float, float, float]:
    """
    (spent >= 95% of limit, spent, limit, seconds until the reset) from the last
    successful response. pointsResetIn is reduced by the time elapsed since that
    response was recorded (never below 0).
    """
    with _rate_lock:
        spent = float(last_rate.get("pointsSpentThisHour") or 0)
        limit = float(last_rate.get("limitPerHour") or 0)
        reset_in = float(last_rate.get("pointsResetIn") or 0)
        at = last_rate.get("at")
    if at is not None:
        reset_in = max(0.0, reset_in - (time.monotonic() - at))
    return (limit > 0 and spent >= RATE_EXHAUSTED_FRACTION * limit), spent, limit, reset_in


def _log_rate_headers(response) -> None:
    """Print Retry-After / X-RateLimit-* headers of a 429 once per process (WCL may send none)."""
    global _rate_headers_logged
    if _rate_headers_logged or response is None:
        return
    _rate_headers_logged = True
    try:
        items = [(k, v) for k, v in response.headers.items()
                 if k.lower() == "retry-after" or k.lower().startswith("x-ratelimit")]
    except Exception:
        items = []
    if items:
        print("  [wcl] 429 headers: " + ", ".join(f"{k}={v}" for k, v in items))
    else:
        print("  [wcl] 429 without Retry-After / X-RateLimit-* headers")


def _wait_or_stop(opname: str, long_waited: bool) -> bool:
    """
    Called after the short backoff of a rate-limit signal. Returns True when it
    slept until the hourly reset (retry once more), False when the budget is not
    exhausted (normal retry). Raises WCLRateLimited when waiting is not an option.
    """
    exhausted, spent, limit, reset_in = _exhausted()
    if not exhausted:
        return False
    if long_waited:
        raise WCLRateLimited(f"{opname}: still rate limited after waiting for the hourly reset "
                             f"({_fmt(spent)}/{_fmt(limit)} points)", reset_in=0, spent=spent, limit=limit)
    if reset_in <= WCL_RATE_WAIT_MAX:
        wait = reset_in + RATE_WAIT_MARGIN
        print(f"  [wcl] hourly points exhausted ({_fmt(spent)}/{_fmt(limit)}); waiting {_fmt(wait)} s for the reset")
        time.sleep(wait)
        return True
    raise WCLRateLimited(f"{opname}: hourly points exhausted ({_fmt(spent)}/{_fmt(limit)}), reset in {_fmt(reset_in)} s "
                         f"(> WCL_RATE_WAIT_MAX={_fmt(WCL_RATE_WAIT_MAX)} s)",
                         reset_in=reset_in, spent=spent, limit=limit)


def rate_summary() -> str:
    """One line for the end of a build: points used this run, the hourly limit and the reset countdown."""
    with _rate_lock:
        if not last_rate or _run_points["requests"] == 0:
            return "WCL points this run: none (no WCL requests made)"
        used = _run_points["prev_hours"] + max(_run_points["max_spent"] - (_run_points["first_spent"] or 0.0), 0.0)
        limit, reset_in = last_rate["limitPerHour"], last_rate["pointsResetIn"]
        spent = last_rate["pointsSpentThisHour"]
        req_limit, req_remaining = last_rate.get("req_limit"), last_rate.get("req_remaining")
    req_txt = (f"; requests: {_fmt(req_remaining)} of {_fmt(req_limit)} remaining (x-ratelimit window)"
               if req_limit is not None and req_remaining is not None else "")
    return (f"WCL points this run: {_fmt(used)} of {_fmt(limit)} per hour (+ the last request's cost, which WCL "
            f"reports one response late; {_fmt(spent)} spent this hour); resets in {_fmt(reset_in)} s{req_txt}")


# --- the request ------------------------------------------------------------

def run_query(query: str, variables: dict | None = None) -> dict:
    """
    Sends a GraphQL query to the WCL v2 client API and returns the
    parsed JSON response (the `data` object).

    Retries on 429 (rate limit), 5xx and connection/timeout errors with
    backoff; raises WCLError for GraphQL-level errors and after the last
    failed attempt. When WCL reports the hourly points as exhausted it waits
    for the reset (if <= WCL_RATE_WAIT_MAX seconds) or raises WCLRateLimited.
    """
    opname = _opname(query)
    sent_query = _with_rate_fields(query)
    last_exc: Exception | None = None
    attempt = 0
    long_waited = False
    while attempt < MAX_ATTEMPTS:
        response = None
        try:
            response, sole = _post(sent_query, variables)
            if response.status_code == 401:
                # token expired server-side: drop it and retry immediately
                global _cached_token
                with _token_lock:
                    _cached_token = None
                last_exc = WCLError("401 unauthorized")
                attempt += 1
                continue
            if response.status_code == 429:
                _log_rate_headers(response)
                last_exc = WCLError(f"HTTP 429: {response.text[:200]}")
                time.sleep(_retry_delay(attempt, response))
                if _wait_or_stop(opname, long_waited):
                    long_waited = True
                else:
                    attempt += 1
                continue
            if response.status_code >= 500:
                last_exc = WCLError(f"HTTP {response.status_code}: {response.text[:200]}")
                time.sleep(_retry_delay(attempt, response))
                attempt += 1
                continue
            response.raise_for_status()
            payload = response.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            time.sleep(_retry_delay(attempt, None))
            attempt += 1
            continue

        data = payload.get("data")
        if isinstance(data, dict):
            rate = data.pop("rateLimitData", None)   # never written to the cache
            if isinstance(rate, dict):
                _record_rate(rate, opname, sole, getattr(response, "headers", None))

        errors = payload.get("errors")
        if errors:
            msg = "; ".join(str(e.get("message", e)) for e in errors)
            if "rate limit" in msg.lower() and attempt < MAX_ATTEMPTS - 1:
                last_exc = WCLError(f"GraphQL rate limit: {msg}")
                time.sleep(60)
                if _wait_or_stop(opname, long_waited):
                    long_waited = True
                else:
                    attempt += 1
                continue
            raise WCLError(f"GraphQL error(s): {msg}")
        return payload["data"]

    raise WCLError(f"WCL request failed after {MAX_ATTEMPTS} attempts: {last_exc}")
