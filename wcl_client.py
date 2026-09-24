"""
Small wrapper around the Warcraft Logs v2 GraphQL API.

Handles:
- Getting an OAuth access token via the client_credentials flow
- Sending GraphQL queries with that token attached
- Timeouts, retries with backoff (429 / 5xx / network errors) and
  thread-safety, so a network blip does not abort a long build
"""

import os
import threading
import time

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
GRAPHQL_URL = "https://www.warcraftlogs.com/api/v2/client"

REQUEST_TIMEOUT = float(os.getenv("WCL_TIMEOUT_SECONDS", "60"))
MAX_ATTEMPTS = int(os.getenv("WCL_MAX_ATTEMPTS", "4"))

_cached_token = None
_cached_token_expiry = 0
_token_lock = threading.Lock()
_session = requests.Session()


class WCLError(RuntimeError):
    pass


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


def run_query(query: str, variables: dict | None = None) -> dict:
    """
    Sends a GraphQL query to the WCL v2 client API and returns the
    parsed JSON response (the `data` object).

    Retries on 429 (rate limit), 5xx and connection/timeout errors with
    backoff; raises WCLError for GraphQL-level errors and after the last
    failed attempt.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        response = None
        try:
            token = get_access_token()
            response = _session.post(
                GRAPHQL_URL,
                headers={"Authorization": f"Bearer {token}"},
                json={"query": query, "variables": variables or {}},
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 401:
                # token expired server-side: drop it and retry immediately
                global _cached_token
                with _token_lock:
                    _cached_token = None
                last_exc = WCLError("401 unauthorized")
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_exc = WCLError(f"HTTP {response.status_code}: {response.text[:200]}")
                time.sleep(_retry_delay(attempt, response))
                continue
            response.raise_for_status()
            payload = response.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            time.sleep(_retry_delay(attempt, None))
            continue

        errors = payload.get("errors")
        if errors:
            msg = "; ".join(str(e.get("message", e)) for e in errors)
            if "rate limit" in msg.lower() and attempt < MAX_ATTEMPTS - 1:
                last_exc = WCLError(f"GraphQL rate limit: {msg}")
                time.sleep(60)
                continue
            raise WCLError(f"GraphQL error(s): {msg}")
        return payload["data"]

    raise WCLError(f"WCL request failed after {MAX_ATTEMPTS} attempts: {last_exc}")
