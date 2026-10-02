"""Synthetic tests for analysis/player_metrics.py (Contract A of the Phase 1 plan)."""

import copy

from analysis.player_metrics import PM_COLS, COL, player_metrics, trim

CONTRACT_A = "act dps hps dth fd alv avh avm dtk dtps prep pot hs ir ds ilvl rp bp oh mit am amw gap".split()


def vec(pm, label):
    return dict(zip(PM_COLS, pm[label]))


def make_pull(**over):
    """A 180 s wipe with a tank, a healer, a dps with a table row and a dps with no table row at all."""
    pull = {
        "kill": False,
        "duration_seconds": 180.0,
        "wipe_called_s": None,
        "wipe_cutoff_s": None,
        "participants": {"Tank": "DemonHunter", "Heal": "Monk", "Dps": "Mage", "Ghost": "Rogue"},
        "spec_ids": {"Tank": 581, "Heal": 270, "Dps": 62, "Ghost": 259},
        "deaths": [],
        "damage_taken": [
            {"player": "Dps", "ability": "Caustic Waves", "hits": 3, "amount": 300, "times": [10.0, 50.0, 150.0]},
            {"player": "Dps", "ability": "Melee", "hits": 2, "amount": 300, "times": [20.0, 30.0]},
            {"player": "Dps", "ability": "Fel Armor", "hits": 1, "amount": 10, "times": [5.0]},
            {"player": "Tank", "ability": "Caustic Waves", "hits": 1, "amount": 100, "times": [12.0]},
        ],
        "damage_done": [
            {"name": "Tank", "class": "DemonHunter", "spec": "Vengeance", "total": 9_000_000, "active_seconds": 180.0, "ilvl": 312, "overheal": 0},
            {"name": "Heal", "class": "Monk", "spec": "Mistweaver", "total": 1_800_000, "active_seconds": 170.0, "ilvl": 315, "overheal": 0},
            {"name": "Dps", "class": "Mage", "spec": "Arcane", "total": 18_000_000, "active_seconds": 171.0, "ilvl": 0, "overheal": 0},
        ],
        "healing_done": [
            {"name": "Heal", "class": "Monk", "spec": "Mistweaver", "total": 30_000_000, "active_seconds": 175.0, "ilvl": 315, "overheal": 10_000_000},
            {"name": "Tank", "class": "DemonHunter", "spec": "Vengeance", "total": 2_000_000, "active_seconds": 180.0, "ilvl": 312, "overheal": 500_000},
        ],
        "player_events": {
            "Tank": {"dtk": 12_000_000, "hits": 100, "hits_buffs": 100, "dodge_parry_miss": 5,
                     "am_up": 70, "amw_num": 60_000, "amw_den": 100_000, "mit_num": 7_500_000, "mit_den": 10_000_000},
            "Heal": {"dtk": 3_000_000, "hits": 30, "hits_buffs": 29, "dodge_parry_miss": 0},
            "Dps": {"dtk": 4_000_000, "hits": 40, "hits_buffs": 40, "dodge_parry_miss": 0},
            "Ghost": {"dtk": 0, "hits": 0, "hits_buffs": 0, "dodge_parry_miss": 0},
        },
        "gear": {"Dps": [[0, 310, 1, 0, 1], [1, 320, 0, 1, 2], [3, 1, 0, 0, 3], [17, 1, 0, 0, 4], [15, 330, 7, 0, 5]]},
        "parses": {},
        "interrupts": {"Dps": 2},
        "dispels": {"Heal": 4},
        "consumables": {"Tank": {"flask": True, "food": True, "rune": False, "prepot": True, "vantus": False},
                        "Heal": {"flask": True, "food": False, "rune": True, "prepot": False, "vantus": True},
                        "Dps": {"flask": False, "food": False, "rune": False, "prepot": False, "vantus": False}},
        "consumable_use": {"Dps": {"combat_potion": 2, "healing_potion": 1, "healthstone": 1, "mana_potion": 0}},
        "has_extras": True,
    }
    pull.update(over)
    return pull


AVOIDABLE = {"causticwaves", "felarmor"}
IGNORED = {"felarmor"}


def test_pm_cols_matches_contract_a_exactly():
    assert PM_COLS == CONTRACT_A
    assert len(PM_COLS) == 23 and "ish" not in PM_COLS
    assert COL == {name: i for i, name in enumerate(CONTRACT_A)}


def test_trim_pops_trailing_nulls_only():
    assert trim([1, None, 2, None, None]) == [1, None, 2]
    assert trim([None, None]) == []
    assert trim([]) == []
    v = [1, None]
    assert trim(v) == [1] and v == [1, None]   # does not mutate


def test_vectors_have_full_length_and_only_ints_or_none():
    pm = player_metrics(make_pull(), AVOIDABLE, IGNORED, None)
    assert set(pm) == {"Tank", "Heal", "Dps", "Ghost"}
    for v in pm.values():
        assert len(v) == len(PM_COLS)
        assert all(x is None or (isinstance(x, int) and not isinstance(x, bool)) for x in v)


def test_player_without_table_row_gets_nulls_but_counts_and_alive():
    g = vec(player_metrics(make_pull(), AVOIDABLE, IGNORED, None), "Ghost")
    assert g["act"] is None and g["dps"] is None and g["hps"] is None and g["ilvl"] is None
    assert g["dth"] == 0 and g["fd"] is None and g["alv"] == 180
    assert g["avh"] == 0 and g["avm"] == 0 and g["dtk"] == 0 and g["dtps"] == 0
    assert g["prep"] is None            # not in consumables
    assert g["pot"] == 0 and g["hs"] == 0 and g["ir"] == 0 and g["ds"] == 0
    assert g["rp"] is None and g["bp"] is None and g["oh"] is None
    assert g["mit"] is None and g["am"] is None and g["amw"] is None and g["gap"] is None


def test_healer_gets_hps_oh_and_healing_row_activity():
    h = vec(player_metrics(make_pull(), AVOIDABLE, IGNORED, None), "Heal")
    assert h["act"] == round(100 * 175 / 180)          # healing row wins for healers
    assert h["hps"] == round(30_000_000 / 175 / 1000)  # 171
    assert h["dps"] == round(1_800_000 / 170 / 1000)   # dps still reported from the damage row
    assert h["oh"] == 25
    assert h["mit"] is None and h["am"] is None
    assert h["prep"] == 1 + 4 + 16 and h["ds"] == 4 and h["ir"] == 0


def test_non_healer_has_no_hps_or_oh_even_with_healing_row():
    pm = player_metrics(make_pull(), AVOIDABLE, IGNORED, None)
    assert vec(pm, "Tank")["hps"] is None and vec(pm, "Tank")["oh"] is None
    assert vec(pm, "Dps")["act"] == 95 and vec(pm, "Dps")["dps"] == round(18_000_000 / 171 / 1000)


def test_tank_gets_mit_am_amw_from_digest():
    t = vec(player_metrics(make_pull(), AVOIDABLE, IGNORED, None), "Tank")
    assert t["mit"] == 75 and t["am"] == 70 and t["amw"] == 60
    assert t["dtk"] == 12_000 and t["dtps"] == round(12_000_000 / 180 / 100)
    assert t["prep"] == 1 + 2 + 8 and t["ilvl"] == 312


def test_tank_am_null_when_too_many_hits_lack_buffs_but_mit_stays():
    pull = make_pull()
    pull["player_events"]["Tank"].update({"hits": 100, "hits_buffs": 69, "am_up": 60})   # 31 % missing
    t = vec(player_metrics(pull, AVOIDABLE, IGNORED, None), "Tank")
    assert t["am"] is None and t["amw"] is None and t["mit"] == 75
    pull["player_events"]["Tank"].update({"hits": 100, "hits_buffs": 70, "am_up": 35})   # exactly 30 %: allowed
    assert vec(player_metrics(pull, AVOIDABLE, IGNORED, None), "Tank")["am"] == 50


def test_tank_am_null_when_spec_not_configured_or_no_hits():
    pull = make_pull()
    del pull["player_events"]["Tank"]["am_up"]   # digest omits am_* when the spec has no config entry
    t = vec(player_metrics(pull, AVOIDABLE, IGNORED, None), "Tank")
    assert t["am"] is None and t["amw"] is None and t["mit"] == 75
    pull = make_pull()
    pull["player_events"]["Tank"].update({"hits": 0, "hits_buffs": 0, "am_up": 0, "amw_num": 0, "amw_den": 0})
    assert vec(player_metrics(pull, AVOIDABLE, IGNORED, None), "Tank")["am"] is None


def test_no_digest_gives_null_dtk_dtps_mit_am():
    pull = make_pull()
    del pull["player_events"]
    t = vec(player_metrics(pull, AVOIDABLE, IGNORED, None), "Tank")
    assert t["dtk"] is None and t["dtps"] is None and t["mit"] is None and t["am"] is None


def test_avoidable_counts_minus_ignore_and_null_without_list():
    d = vec(player_metrics(make_pull(), AVOIDABLE, IGNORED, None), "Dps")
    assert d["avh"] == 3                       # Caustic Waves x3; Fel Armor ignored; Melee not avoidable
    assert d["avm"] == round(3 / (180 / 60) * 10)
    d0 = vec(player_metrics(make_pull(), set(), set(), None), "Dps")
    assert d0["avh"] is None and d0["avm"] is None
    # an avoidable list that is entirely ignored behaves like no list
    d1 = vec(player_metrics(make_pull(), {"felarmor"}, {"felarmor"}, None), "Dps")
    assert d1["avh"] is None


def test_death_at_zero_seconds_gives_alv_1_and_first_death():
    pull = make_pull(deaths=[{"player": "Dps", "class": "Mage", "seconds_into_fight": 0.0, "ability": "Falling"},
                             {"player": "Tank", "class": "DemonHunter", "seconds_into_fight": 100.0, "ability": "Melee"}])
    pm = player_metrics(pull, AVOIDABLE, IGNORED, None)
    d, t, h = vec(pm, "Dps"), vec(pm, "Tank"), vec(pm, "Heal")
    assert d["alv"] == 1 and d["fd"] == 1 and d["dth"] == 1
    assert d["avm"] == round(3 / (1 / 60) * 10)   # per minute alive uses the floor of 1 s
    assert t["alv"] == 100 and t["fd"] == 0 and t["dth"] == 1
    assert h["fd"] == 0 and h["dth"] == 0 and h["alv"] == 180


def test_wipe_cutoff_excludes_later_deaths_and_hits_but_not_fd_alv():
    deaths = [{"player": "Tank", "class": "DemonHunter", "seconds_into_fight": 40.0, "ability": "A"},
              {"player": "Dps", "class": "Mage", "seconds_into_fight": 120.0, "ability": "B"},
              {"player": "Heal", "class": "Monk", "seconds_into_fight": 125.0, "ability": "B"},
              {"player": "Dps", "class": "Mage", "seconds_into_fight": 170.0, "ability": "B"},
              {"player": "Ghost", "class": "Rogue", "seconds_into_fight": 178.0, "ability": "B"}]
    pull = make_pull(deaths=deaths, wipe_cutoff_s=120.0)
    pm = player_metrics(pull, AVOIDABLE, IGNORED, None)
    d, g, t = vec(pm, "Dps"), vec(pm, "Ghost"), vec(pm, "Tank")
    assert d["dth"] == 1 and g["dth"] == 0 and t["dth"] == 1        # 120.0 counts (<=), 170 / 178 do not
    assert d["fd"] == 0 and t["fd"] == 1 and g["alv"] == 178 and d["alv"] == 120
    assert d["avh"] == 2 and d["avm"] == round(2 / (120 / 60) * 10)   # the 150 s hit is excluded
    # the same pull without a cutoff counts everything
    pm2 = player_metrics(make_pull(deaths=deaths), AVOIDABLE, IGNORED, None)
    assert vec(pm2, "Dps")["dth"] == 2 and vec(pm2, "Dps")["avh"] == 3 and vec(pm2, "Ghost")["dth"] == 1


def test_kill_has_parses_and_no_cutoff():
    pull = make_pull(kill=True, parses={
        "Dps": {"dps": 77, "bdps": 60, "spec": "Arcane", "hps": 5, "bhps": 3},
        "Heal": {"dps": 10, "bdps": 8, "hps": 91, "bhps": 88, "spec": "Mistweaver"},
        "Tank": {"dps": 50},
    })
    pm = player_metrics(pull, AVOIDABLE, IGNORED, None)
    assert vec(pm, "Dps")["rp"] == 77 and vec(pm, "Dps")["bp"] == 60
    assert vec(pm, "Heal")["rp"] == 91 and vec(pm, "Heal")["bp"] == 88    # healers use the hps ranking
    assert vec(pm, "Tank")["rp"] == 50 and vec(pm, "Tank")["bp"] is None
    assert vec(pm, "Ghost")["rp"] is None


def test_ilvl_falls_back_to_gear_mean_skipping_shirt_and_tabard():
    d = vec(player_metrics(make_pull(), AVOIDABLE, IGNORED, None), "Dps")
    assert d["ilvl"] == round((310 + 320 + 330) / 3)


def test_prep_pot_hs_ir_ds_null_rules():
    pm = player_metrics(make_pull(), AVOIDABLE, IGNORED, None)
    d = vec(pm, "Dps")
    assert d["prep"] == 0 and d["pot"] == 2 and d["hs"] == 2 and d["ir"] == 2 and d["ds"] == 0
    pull = make_pull(has_extras=False, consumable_use={})
    d2 = vec(player_metrics(pull, AVOIDABLE, IGNORED, None), "Dps")
    assert d2["prep"] is None and d2["ir"] is None and d2["ds"] is None
    assert d2["pot"] is None and d2["hs"] is None


def test_gear_gaps_fill_gap_column_and_none_is_allowed():
    pm = player_metrics(make_pull(), AVOIDABLE, IGNORED, {"Dps": 3, "Tank": 0})
    assert vec(pm, "Dps")["gap"] == 3 and vec(pm, "Tank")["gap"] == 0 and vec(pm, "Heal")["gap"] is None
    assert all(vec(player_metrics(make_pull(), AVOIDABLE, IGNORED, None), n)["gap"] is None for n in ("Dps", "Tank"))


def test_role_falls_back_to_table_spec_when_spec_ids_missing():
    pull = make_pull(spec_ids={})
    pm = player_metrics(pull, AVOIDABLE, IGNORED, None)
    assert vec(pm, "Heal")["hps"] is not None and vec(pm, "Tank")["mit"] == 75
    # and healers are detected from the healing table only when the token is a healer spec
    assert vec(pm, "Dps")["hps"] is None


def test_input_pull_is_not_mutated():
    pull = make_pull()
    before = copy.deepcopy(pull)
    player_metrics(pull, AVOIDABLE, IGNORED, {"Dps": 1})
    assert pull == before
