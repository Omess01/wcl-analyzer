"""Synthetic tests for analysis/wipe.py (post-wipe cutoff) and analysis/mitigation.py (event digest, AM ids)."""

import pytest

from analysis import mitigation
from analysis.mitigation import digest_events, am_ids_for, parse_buffs, spec_label, TANK_BUFFS_SEEN
from analysis.wipe import wipe_cutoff_s, WIPE_CASCADE_GAP_S, WIPE_CASCADE_MIN_DEATHS, WIPE_TAIL_S

FIXTURE_FIGHT8_DEATHS = [57.1, 66.1, 70.1, 92.5, 93.6, 94.0, 94.6, 94.7, 94.8, 95.0, 95.6, 96.2, 99.0, 99.6, 101.0, 104.0, 104.8]


# ---------------------------------------------------------------- wipe cutoff

def test_constants_as_pinned():
    assert (WIPE_CASCADE_GAP_S, WIPE_CASCADE_MIN_DEATHS, WIPE_TAIL_S) == (10.0, 3, 20.0)


def test_cutoff_on_fixture_death_list_is_first_death_of_cascade():
    assert wipe_cutoff_s(False, 105.0, FIXTURE_FIGHT8_DEATHS, None) == 92.5


def test_cutoff_unsorted_input_same_result():
    assert wipe_cutoff_s(False, 105.0, list(reversed(FIXTURE_FIGHT8_DEATHS)), None) == 92.5


def test_cutoff_two_deaths_is_none():
    assert wipe_cutoff_s(False, 250.6, [30.0, 35.0], None) is None


def test_cutoff_cascade_ending_40s_before_end_is_none():
    assert wipe_cutoff_s(False, 200.0, [150.0, 152.0, 155.0], None) is None


def test_cutoff_cascade_at_end_counts_only_the_tail_run():
    # 20 s gap between 70 and 90 breaks the run; the tail run of 3 within 20 s of the end gives the cutoff 90
    assert wipe_cutoff_s(False, 100.0, [10.0, 70.0, 90.0, 95.0, 99.0], None) == 90.0


def test_cutoff_tail_run_too_short_is_none():
    assert wipe_cutoff_s(False, 100.0, [10.0, 20.0, 95.0, 99.0], None) is None


def test_cutoff_kill_is_none_even_with_cascade():
    assert wipe_cutoff_s(True, 100.0, [95.0, 96.0, 97.0], None) is None


def test_cutoff_wipe_called_s_wins():
    assert wipe_cutoff_s(False, 100.0, [95.0, 96.0, 97.0], 42.0) == 42.0
    assert wipe_cutoff_s(True, 100.0, [], 12.5) == 12.5


def test_cutoff_no_deaths_is_none():
    assert wipe_cutoff_s(False, 100.0, [], None) is None
    assert wipe_cutoff_s(False, None, [1.0, 2.0, 3.0], None) is None


# ---------------------------------------------------------------- AM ids / config

def test_am_ids_for_resolves_vengeance_and_protection():
    assert 203819 in am_ids_for("Vengeance", "DemonHunter")
    assert am_ids_for("Vengeance") == am_ids_for("Vengeance", "DemonHunter")
    assert am_ids_for("Protection", "Paladin") == {132403}
    assert 132404 in am_ids_for("Protection", "Warrior") and 132403 not in am_ids_for("Protection", "Warrior")
    # without a class a shared token resolves to the union (the T3 recap flag only needs "is any AM up")
    assert am_ids_for("Protection") == am_ids_for("Protection", "Paladin") | am_ids_for("Protection", "Warrior")


def test_am_ids_for_unknown_spec_is_none():
    assert am_ids_for("Havoc", "DemonHunter") is None
    assert am_ids_for("Havoc") is None
    assert am_ids_for("") is None


def test_spec_label_disambiguates_shared_tokens_only():
    assert spec_label("Paladin", "Protection") == "Protection Paladin"
    assert spec_label("Warrior", "Protection") == "Protection Warrior"
    assert spec_label("DemonHunter", "Vengeance") == "Vengeance"


def test_parse_buffs():
    assert parse_buffs("203819.187827.") == {203819, 187827}
    assert parse_buffs("") == set() and parse_buffs(None) == set()


def test_config_file_shape_and_known_keys():
    import json
    import os
    with open(mitigation.TANK_MITIGATION_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    with open(os.path.join(os.path.dirname(mitigation.TANK_MITIGATION_FILE), "tank_mitigation.example.json"), encoding="utf-8") as f:
        example = json.load(f)
    specs_keys = {k for k in raw if not k.startswith("_")}
    assert specs_keys == {"Vengeance", "Protection Paladin", "Protection Warrior", "Blood", "Guardian", "Brewmaster"}
    assert {k for k in example if not k.startswith("_")} == specs_keys
    for key in specs_keys:
        for kind in ("am", "major"):
            assert raw[key][kind], (key, kind)
            assert all(isinstance(i["id"], int) and i["name"] for i in raw[key][kind])
    assert "203819" in raw["_comment"] or "Demon Spikes" in raw["_comment"]


# ---------------------------------------------------------------- digest

PARTS = {"Tank": "DemonHunter", "Dps": "Mage"}
SPECS = {"Tank": 581, "Dps": 62}   # Vengeance, Arcane


def ev(player, seconds, amount, *, buffs="x", hit_type=1, tick=False, source="Boss", mitigated=100, absorbed=0,
       unmitigated=None, self_=False):
    e = {"player": player, "self": self_, "is_tick": tick, "source": source, "amount": amount + absorbed,
         "absorbed": absorbed, "overkill": 0, "seconds": seconds, "hit_type": hit_type, "mitigated": mitigated,
         "blocked": None, "avoided": amount == 0 and absorbed == 0,
         "unmitigated": unmitigated if unmitigated is not None else amount + absorbed + (mitigated or 0)}
    e["buffs"] = None if buffs is None else ("203819.1." if buffs == "x" else buffs)
    return e


@pytest.fixture(autouse=True)
def _clear_seen():
    TANK_BUFFS_SEEN.clear()
    yield
    TANK_BUFFS_SEEN.clear()


def test_digest_has_entry_for_every_participant_and_tank_keys_only_for_tanks():
    d = digest_events([], PARTS, SPECS, None)
    assert set(d) == {"Tank", "Dps"}
    assert set(d["Dps"]) == {"dtk", "hits", "hits_buffs", "dodge_parry_miss"}
    assert set(d["Tank"]) == {"dtk", "hits", "hits_buffs", "dodge_parry_miss", "am_up", "amw_num", "amw_den", "mit_num", "mit_den"}


def test_digest_counts_hits_and_am_with_and_without_buffs():
    events = [
        ev("Tank", 1, 1000, buffs="203819.5."),        # AM up
        ev("Tank", 2, 1000, buffs="5."),               # AM down
        ev("Tank", 3, 1000, buffs=None),               # no aura data: counted as a hit, not in hits_buffs
        ev("Tank", 4, 1000, buffs="", hit_type=2),     # crit, empty buffs string = aura data present, AM down
    ]
    d = digest_events(events, PARTS, SPECS, None)["Tank"]
    assert d["hits"] == 4 and d["hits_buffs"] == 3 and d["am_up"] == 1
    assert d["amw_den"] == 3 * 1100 and d["amw_num"] == 1100
    assert d["dtk"] == 4000
    assert TANK_BUFFS_SEEN["Vengeance"][203819] == 1 and TANK_BUFFS_SEEN["Vengeance"][5] == 2


def test_digest_connected_filter_excludes_dodge_parry_miss_immune_and_ticks():
    events = [
        ev("Tank", 1, 1000),
        ev("Tank", 2, 0, hit_type=7, mitigated=None, unmitigated=0),    # dodge
        ev("Tank", 3, 0, hit_type=8, mitigated=None, unmitigated=0),    # parry
        ev("Tank", 4, 0, hit_type=0, mitigated=None, unmitigated=0),    # miss
        ev("Tank", 5, 0, hit_type=10, mitigated=None, unmitigated=0),   # immune
        ev("Tank", 6, 500, tick=True),                                   # DoT tick: damage yes, hit no
    ]
    d = digest_events(events, PARTS, SPECS, None)["Tank"]
    assert d["hits"] == 1 and d["hits_buffs"] == 1 and d["am_up"] == 1
    assert d["dodge_parry_miss"] == 3
    assert d["dtk"] == 1500
    # mitigation includes the tick (unmitigated > 0) but not the avoided swings (unmitigated 0)
    assert d["mit_den"] == 1100 + 600 and d["mit_num"] == 200


def test_digest_weighted_share_uses_unmitigated_and_missing_mitigated_counts_as_zero():
    events = [
        ev("Tank", 1, 100, buffs="203819.", mitigated=None, unmitigated=900, absorbed=0),   # AM up, big hit
        ev("Tank", 2, 100, buffs="7.", mitigated=50, absorbed=20, unmitigated=170),         # AM down, small hit
    ]
    d = digest_events(events, PARTS, SPECS, None)["Tank"]
    assert d["am_up"] == 1 and d["hits_buffs"] == 2
    assert d["amw_num"] == 900 and d["amw_den"] == 1070
    assert d["mit_num"] == 0 + 50 + 20 and d["mit_den"] == 900 + 170


def test_digest_applies_cutoff_and_skips_self_and_friendly_sources():
    events = [
        ev("Tank", 10, 1000),
        ev("Tank", 20, 1000, self_=True, source="Tank"),       # self-inflicted
        ev("Tank", 30, 1000, source="Dps"),                     # friendly source (a participant)
        ev("Tank", 95, 1000),                                   # after the cutoff
        ev("Dps", 50, 700, buffs=None),
    ]
    d = digest_events(events, PARTS, SPECS, 92.5)
    assert d["Tank"]["dtk"] == 1000 and d["Tank"]["hits"] == 1
    assert d["Dps"] == {"dtk": 700, "hits": 1, "hits_buffs": 0, "dodge_parry_miss": 0}


def test_digest_spec_token_strings_and_unknown_tank_spec(capsys):
    # spec tokens (Contract D fallback) work like specIDs; a tank spec without config gets mit_* but no am_*
    mitigation._noted_missing.clear()
    d = digest_events([ev("Tank", 1, 1000)], PARTS, {"Tank": "Vengeance"}, None)["Tank"]
    assert d["am_up"] == 1 and d["mit_den"] == 1100
    cfg = mitigation.load_tank_mitigation()
    saved = cfg.pop("Vengeance")
    try:
        d = digest_events([ev("Tank", 1, 1000)], PARTS, SPECS, None)["Tank"]
        assert "am_up" not in d and d["mit_den"] == 1100 and d["hits"] == 1
        assert "no entry for 'Vengeance'" in capsys.readouterr().out
        digest_events([ev("Tank", 1, 1000)], PARTS, SPECS, None)
        assert capsys.readouterr().out == ""   # noted once
    finally:
        cfg["Vengeance"] = saved
        mitigation._noted_missing.clear()


def test_digest_thirty_percent_rule_is_left_to_player_metrics():
    # the digest only counts; the 30 % "aura data incomplete" rule is applied in player_metrics (tested there)
    events = [ev("Tank", i, 1000, buffs=None) for i in range(4)] + [ev("Tank", 9, 1000)]
    d = digest_events(events, PARTS, SPECS, None)["Tank"]
    assert d["hits"] == 5 and d["hits_buffs"] == 1 and d["am_up"] == 1
