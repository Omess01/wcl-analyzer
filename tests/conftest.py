"""
Offline test setup: every WCL response comes from tests/fixtures/cache
(created once with `python tests/make_fixtures.py`), and any attempt to hit
the network fails the test.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(HERE, "fixtures")
FIXTURE_CACHE = os.path.join(FIXTURES, "cache")
REPORT_FILE = os.path.join(FIXTURES, "report.json")


def _no_network(*_args, **_kwargs):
    raise AssertionError("test tried to reach the WCL API - fixtures are missing or a query text changed "
                         "(regenerate with: python tests/make_fixtures.py)")


@pytest.fixture
def fixture_report() -> dict:
    if not os.path.exists(REPORT_FILE):
        pytest.skip("no fixtures - run python tests/make_fixtures.py once (needs network)")
    with open(REPORT_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def offline(monkeypatch, tmp_path, fixture_report):
    """Cache -> fixtures, meta -> temp file, network -> hard failure, report list -> the fixture report."""
    import cache
    import collect_data
    import wcl_client

    monkeypatch.setattr(cache, "CACHE_DIR", FIXTURE_CACHE)
    monkeypatch.setattr(collect_data, "META_FILE", str(tmp_path / "report_meta.json"))
    monkeypatch.setattr(cache, "run_query", _no_network)
    monkeypatch.setattr(collect_data, "run_query", _no_network)
    monkeypatch.setattr(wcl_client, "run_query", _no_network)
    monkeypatch.setattr(collect_data, "fetch_reports_by_code", lambda codes: [fixture_report])
    monkeypatch.setattr(collect_data, "fetch_guild_reports", lambda s, e: [fixture_report])
    monkeypatch.setattr(collect_data, "NIGHTS_FILE", str(tmp_path / "no_nights.json"))   # the real nights.json must not leak in
    monkeypatch.setenv("RAID_TIMEZONE", "Europe/Amsterdam")
    monkeypatch.setenv("MAIN_RAID_DAYS", "Thu,Sun")
    monkeypatch.delenv("OPEN_RAID_DAYS", raising=False)
    monkeypatch.delenv("BOSS_ORDER", raising=False)
    return fixture_report


@pytest.fixture
def bosses(offline):
    import collect_data
    return collect_data.collect("2000-01-01", "2100-01-01", difficulties=["lfr", "normal", "heroic", "mythic"],
                                reports=[offline["code"]])
