"""
wcl_client rate-limit handling, fully offline: the HTTP session, the OAuth token
and time.sleep are replaced, so no test here reaches the network.
"""

import sys
import threading

import pytest

import wcl_client
from wcl_client import WCLError, WCLRateLimited


class FakeResponse:
    def __init__(self, status_code=200, data=None, rate=None, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        body = dict(data or {})
        if rate is not None:
            body["rateLimitData"] = rate
        self._payload = {"data": body}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns the queued responses in order and records every post()."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def rate(spent, limit=3600, reset_in=1200):
    return {"limitPerHour": limit, "pointsSpentThisHour": spent, "pointsResetIn": reset_in}


@pytest.fixture
def wcl(monkeypatch):
    """Offline wcl_client: fake token, recorded sleeps, fresh rate bookkeeping. Returns a helper to install responses."""
    sleeps = []
    monkeypatch.setattr(wcl_client, "get_access_token", lambda: "test-token")
    monkeypatch.setattr(wcl_client.time, "sleep", lambda s: sleeps.append(s))
    clock = [1000.0]   # deterministic time.monotonic(); tests advance clock[0] by hand
    monkeypatch.setattr(wcl_client.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(wcl_client, "last_rate", {})
    monkeypatch.setattr(wcl_client, "_run_points", {"first_spent": None, "max_spent": 0.0, "last_spent": None,
                                                    "last_reset_in": None, "prev_hours": 0.0, "requests": 0,
                                                    "prev_op": None, "prev_sole": False})
    monkeypatch.setattr(wcl_client, "_flight", {"in": 0, "starts": 0})
    monkeypatch.setattr(wcl_client, "_rate_headers_logged", False)
    monkeypatch.setattr(wcl_client, "_req_budget_warned", False)
    monkeypatch.setattr(wcl_client, "WCL_RATE_WAIT_MAX", 900.0)

    def install(*responses):
        session = FakeSession(responses)
        monkeypatch.setattr(wcl_client, "_session", session)
        return session

    install.sleeps = sleeps
    install.clock = clock
    return install


QUERY = "query ReportFights($code: String!) {\n  reportData { report(code: $code) { title } }\n}\n"


def test_rate_fields_added_at_send_time_only(wcl):
    session = wcl(FakeResponse(data={"reportData": {"report": {"title": "x"}}}, rate=rate(10)))
    before = QUERY
    data = wcl_client.run_query(QUERY, {"code": "abc"})

    sent = session.calls[0]["json"]["query"]
    assert "rateLimitData {" in sent
    assert sent.rstrip().endswith("}")
    assert sent.count("{") == sent.count("}")
    assert QUERY == before                                  # caller's text (the cache key) untouched
    assert "rateLimitData" not in QUERY
    assert data == {"reportData": {"report": {"title": "x"}}}   # popped before returning / caching
    assert wcl_client.last_rate == {"limitPerHour": 3600.0, "pointsSpentThisHour": 10.0, "pointsResetIn": 1200.0,
                                    "req_limit": None, "req_remaining": None, "at": 1000.0}


def test_cache_key_is_callers_query(wcl, monkeypatch, tmp_path):
    """cache.py hashes the text the caller passes, so adding fields at send time cannot change the key."""
    import cache
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path))
    assert cache._cache_path(QUERY, {"code": "abc"}) != cache._cache_path(wcl_client._with_rate_fields(QUERY), {"code": "abc"})
    assert cache._cache_path(QUERY, {"code": "abc"}) == cache._cache_path(QUERY, {"code": "abc"})


def test_per_request_line_attributes_lagged_cost_to_previous_op(wcl, capsys):
    """WCL reports pointsSpentThisHour BEFORE the response's own charge, so the delta belongs to the previous op."""
    wcl(FakeResponse(data={"a": 1}, rate=rate(100)),
        FakeResponse(data={"a": 2}, rate=rate(130, reset_in=1190)),      # +30 = cost of the FightBundle before it
        FakeResponse(data={"a": 3}, rate=rate(131, reset_in=1180)))      # +1  = cost of the ReportPhases before it
    wcl_client.run_query("query FightBundle($code: String!) { reportData { x } }")
    wcl_client.run_query("query ReportPhases($code: String!) { reportData { x } }")
    wcl_client.run_query(QUERY)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("  [wcl]")]
    assert lines == [
        "  [wcl] FightBundle 100/3600 pts this hour, reset in 1200 s",
        "  [wcl] ReportPhases 130/3600 pts this hour, reset in 1190 s; FightBundle cost 30 pts",
        "  [wcl] ReportFights 131/3600 pts this hour, reset in 1180 s; ReportPhases cost 1 pts",
    ]
    summary = wcl_client.rate_summary()
    assert summary.startswith("WCL points this run: 31 of 3600 per hour (+ the last request's cost")
    assert "resets in 1180 s" in summary
    assert "requests:" not in summary                      # no x-ratelimit headers in this test


def test_no_cost_attribution_when_requests_overlap(wcl, capsys):
    """With WCL_PARALLEL > 1 the lagged counter cannot be assigned to one op: only the running total is printed."""
    barrier = threading.Barrier(2, timeout=5)
    responses = [FakeResponse(data={"a": 1}, rate=rate(100)), FakeResponse(data={"a": 2}, rate=rate(130))]
    lock = threading.Lock()

    class OverlappingSession:
        def post(self, url, **kwargs):
            barrier.wait()                                 # both requests are in flight at the same time
            with lock:
                return responses.pop(0)

    wcl()
    wcl_client._session = OverlappingSession()
    threads = [threading.Thread(target=wcl_client.run_query, args=(QUERY,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    out = capsys.readouterr().out
    assert out.count("[wcl] ReportFights") == 2
    assert "cost" not in out
    # a later sequential request is still not attributable: its predecessor overlapped something
    wcl_client._session = FakeSession([FakeResponse(data={"a": 3}, rate=rate(131))])
    wcl_client.run_query(QUERY)
    assert "cost" not in capsys.readouterr().out


def test_request_count_headers_captured_and_warned_once(wcl, capsys):
    wcl(FakeResponse(data={"a": 1}, rate=rate(100), headers={"x-ratelimit-limit": "300", "x-ratelimit-remaining": "299"}),
        FakeResponse(data={"a": 2}, rate=rate(101), headers={"X-RateLimit-Limit": "300", "X-RateLimit-Remaining": "29"}),
        FakeResponse(data={"a": 3}, rate=rate(102), headers={"x-ratelimit-limit": "300", "x-ratelimit-remaining": "28"}))
    wcl_client.run_query(QUERY)
    assert wcl_client.last_rate["req_limit"] == 300.0
    assert wcl_client.last_rate["req_remaining"] == 299.0
    assert "warning" not in capsys.readouterr().out
    wcl_client.run_query(QUERY)                            # 29 < 10 % of 300 -> warn
    wcl_client.run_query(QUERY)                            # still low -> no second warning
    out = capsys.readouterr().out
    assert out.count("[wcl] warning: only 29 of 300 requests left") == 1
    assert wcl_client.last_rate["req_remaining"] == 28.0
    assert "requests: 28 of 300 remaining" in wcl_client.rate_summary()


def test_429_below_threshold_short_backoff_then_success(wcl):
    wcl(FakeResponse(data={"a": 1}, rate=rate(1000)),
        FakeResponse(status_code=429, headers={"Retry-After": "7"}, text="slow down"),
        FakeResponse(data={"a": 2}, rate=rate(1001)))
    wcl_client.run_query(QUERY)
    data = wcl_client.run_query(QUERY)
    assert data == {"a": 2}
    assert wcl.sleeps == [7.0]                             # only the short backoff, no long wait


def test_429_exhausted_waits_for_reset_then_retries(wcl):
    wcl(FakeResponse(data={"a": 1}, rate=rate(3500, reset_in=600)),   # 97 % spent, reset within WCL_RATE_WAIT_MAX
        FakeResponse(status_code=429, text="limited"),
        FakeResponse(data={"a": 2}, rate=rate(3, reset_in=3600)))
    wcl_client.run_query(QUERY)
    wcl.clock[0] += 100.0                                  # 100 s pass before the 429
    data = wcl_client.run_query(QUERY)
    assert data == {"a": 2}
    assert wcl.sleeps[0] == 2.0                            # existing short backoff first (attempt 0, no Retry-After)
    # one long sleep: pointsResetIn minus elapsed time plus the safety margin
    assert wcl.sleeps[1:] == [600.0 - 100.0 + wcl_client.RATE_WAIT_MARGIN]


def test_429_exhausted_elapsed_time_brings_reset_within_wait_max(wcl):
    """A reset that was too far when recorded is waited for once enough time has passed."""
    wcl(FakeResponse(data={"a": 1}, rate=rate(3500, reset_in=1000)),
        FakeResponse(status_code=429, text="limited"),
        FakeResponse(data={"a": 2}, rate=rate(3, reset_in=3600)))
    wcl_client.run_query(QUERY)
    wcl.clock[0] += 200.0                                  # 1000 - 200 = 800 s left <= WCL_RATE_WAIT_MAX
    assert wcl_client.run_query(QUERY) == {"a": 2}
    assert wcl.sleeps[1:] == [800.0 + wcl_client.RATE_WAIT_MARGIN]


def test_429_exhausted_reset_too_far_raises(wcl):
    session = wcl(FakeResponse(data={"a": 1}, rate=rate(3500, reset_in=901)),
                  FakeResponse(status_code=429, text="limited"))
    wcl_client.run_query(QUERY)
    with pytest.raises(WCLRateLimited) as info:
        wcl_client.run_query(QUERY)
    assert info.value.reset_in == 901.0
    assert "901" in str(info.value)
    assert len(session.calls) == 2                         # no further retry after the stop decision
    assert 901.0 not in wcl.sleeps


def test_graphql_rate_limit_error_exhausted_raises(wcl):
    first = FakeResponse(data={"a": 1}, rate=rate(3500, reset_in=5000))
    limited = FakeResponse(data={}, rate=rate(3500, reset_in=4999))
    limited._payload["errors"] = [{"message": "You are being rate limited."}]
    wcl(first, limited)
    wcl_client.run_query(QUERY)
    with pytest.raises(WCLRateLimited):
        wcl_client.run_query(QUERY)
    assert wcl.sleeps == [60]                              # existing 60 s backoff first


def test_rate_limited_is_not_a_wclerror():
    assert not issubclass(WCLRateLimited, WCLError)
    assert issubclass(WCLRateLimited, RuntimeError)
    with pytest.raises(WCLRateLimited):
        try:
            raise WCLRateLimited("stop")
        except WCLError:                                   # the degrade-silently handlers must not catch it
            pytest.fail("WCLRateLimited was swallowed by except WCLError")


def test_429_headers_logged_once(wcl, capsys):
    wcl(FakeResponse(status_code=429, headers={"Retry-After": "1", "X-RateLimit-Remaining": "0"}),
        FakeResponse(status_code=429, headers={"Retry-After": "1"}),
        FakeResponse(data={"a": 1}, rate=rate(5)))
    wcl_client.run_query(QUERY)
    out = capsys.readouterr().out
    assert out.count("429 headers") == 1
    assert "X-RateLimit-Remaining=0" in out


def test_build_dashboard_exits_3_when_rate_limited(monkeypatch):
    import build_dashboard

    def boom(*_a, **_k):
        raise WCLRateLimited("exhausted", reset_in=2400)

    monkeypatch.setattr(build_dashboard, "collect", boom)
    monkeypatch.setattr(build_dashboard, "update_mplus_if_stale", lambda force=False: None)
    monkeypatch.setattr(sys, "argv", ["build_dashboard.py", "2026-01-01", "2026-01-02", "--no-mplus"])
    with pytest.raises(SystemExit) as info:
        build_dashboard.main()
    assert info.value.code == 3


def test_build_dashboard_exits_3_when_build_html_rate_limited(monkeypatch, tmp_path, capsys):
    """build_html -> zone_encounter_order -> cached_query can run out of points too."""
    import build_dashboard

    def boom(*_a, **_k):
        raise WCLRateLimited("exhausted", reset_in=1800)

    monkeypatch.setattr(build_dashboard, "collect", lambda *a, **k: {("Boss", "Mythic"): [{}]})
    monkeypatch.setattr(build_dashboard, "write_abilities_seen", lambda bosses: str(tmp_path / "seen.json"))
    monkeypatch.setattr(build_dashboard, "validate_config", lambda bosses: None)
    monkeypatch.setattr(build_dashboard, "build_html", boom)
    monkeypatch.setattr(build_dashboard, "update_mplus_if_stale", lambda force=False: None)
    out = tmp_path / "out.html"
    monkeypatch.setattr(sys, "argv", ["build_dashboard.py", "2026-01-01", "2026-01-02", "--no-mplus", "-o", str(out)])
    with pytest.raises(SystemExit) as info:
        build_dashboard.main()
    assert info.value.code == 3
    assert "resets in 1800 s" in capsys.readouterr().out
    assert not out.exists()


def test_build_dashboard_refresh_refused_when_hour_mostly_spent(wcl, monkeypatch, capsys):
    import build_dashboard
    session = wcl(FakeResponse(data={}, rate=rate(3000)))   # 83 % > 80 %
    monkeypatch.setattr(build_dashboard, "collect", lambda *a, **k: pytest.fail("collect must not run"))
    monkeypatch.setattr(sys, "argv", ["build_dashboard.py", "2026-01-01", "2026-01-02", "--no-mplus", "--refresh"])
    with pytest.raises(SystemExit) as info:
        build_dashboard.main()
    assert info.value.code == 3
    assert len(session.calls) == 1
    assert session.calls[0]["json"]["query"].count("rateLimitData") == 1   # not injected twice
    assert "--refresh refused" in capsys.readouterr().out
