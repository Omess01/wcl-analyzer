"""analysis/gear.py: roster-majority rules, gap strings, ilvl, latest_gear, config loader."""
import json

from analysis import gear

# Per-slot (enchanted, gemmed, non-empty) counts measured on tests/fixtures (16 players).
FIXTURE_COUNTS = {0: (15, 4, 16), 1: (0, 16, 16), 2: (16, 0, 16), 3: (0, 0, 10), 4: (16, 0, 16),
                  5: (0, 2, 16), 6: (16, 0, 16), 7: (15, 0, 16), 8: (0, 1, 16), 9: (0, 0, 16),
                  10: (16, 16, 16), 11: (16, 16, 16), 12: (0, 0, 16), 13: (0, 0, 16), 14: (0, 0, 16),
                  15: (15, 0, 16), 16: (4, 0, 8), 17: (0, 0, 11)}


def fixture_roster():
    """16 players whose gear reproduces FIXTURE_COUNTS; empty slots are item_id 0 rows."""
    roster = {}
    for i in range(16):
        rows = []
        for slot, (ne, ng, nt) in FIXTURE_COUNTS.items():
            if i >= nt:
                rows.append([slot, 0, 0, 0, 0])
                continue
            rows.append([slot, 300, 7000 + slot if i < ne else 0, 1 if i < ng else 0, 200000 + slot])
        roster[f"P{i}"] = rows
    return roster


def full_rows(ilvl=300, enchant=1, gems=1):
    return [[s, ilvl, enchant, gems, 1000 + s] for s in range(18)]


def test_majority_rule_on_fixture_distribution():
    rules = gear.roster_rules(fixture_roster(), gear.DEFAULTS)
    assert rules["enchant_slots"] == {0, 2, 4, 6, 7, 10, 11, 15}
    assert 14 not in rules["enchant_slots"] and 16 not in rules["enchant_slots"]
    assert rules["gem_slots"] == {1, 10, 11}


def test_explicit_lists_override_auto():
    cfg = {**gear.DEFAULTS, "enchantable": [14, 8], "socket_slots": [0]}
    rules = gear.roster_rules(fixture_roster(), cfg)
    assert rules == {"enchant_slots": {8, 14}, "gem_slots": {0}}
    # an explicit list for one check leaves the other on auto
    rules = gear.roster_rules(fixture_roster(), {**gear.DEFAULTS, "enchantable": [14]})
    assert rules["gem_slots"] == {1, 10, 11}


def test_empty_roster_requires_nothing():
    assert gear.roster_rules({}, gear.DEFAULTS) == {"enchant_slots": set(), "gem_slots": set()}
    assert gear.roster_rules(None) == {"enchant_slots": set(), "gem_slots": set()}


def test_gap_strings_and_order():
    rules = {"enchant_slots": {0, 2}, "gem_slots": {1, 11}}
    rows = full_rows()
    rows[0][2] = 0       # head without enchant
    rows[11][3] = 0      # ring 2 without gem
    rows[8][1] = 280     # wrist far below average
    rep = gear.gear_report(rows, rules, gear.DEFAULTS)
    # 16 counted slots (shirt/tabard skipped): mean = (15*300 + 280)/16 = 298.75
    assert rep["ilvl"] == 299
    assert rep["gaps"] == ["head: no enchant", "wrist 19 ilvl below your average", "ring 2: empty socket"]
    assert rep["n_gaps"] == 3


def test_low_slot_wording_exact():
    rows = [[0, 320, 0, 0, 1], [2, 320, 0, 0, 2], [4, 320, 0, 0, 3], [8, 300, 0, 0, 4],
            [15, 335, 0, 0, 5]]
    # mean = 319; wrist 300 <= 319 - 15 -> "wrist 19 ilvl below your average"
    rep = gear.gear_report(rows, {"enchant_slots": set(), "gem_slots": set()}, gear.DEFAULTS)
    assert rep == {"ilvl": 319, "gaps": ["wrist 19 ilvl below your average"], "n_gaps": 1}
    # exactly low_slot_gap below counts ("<=")
    rows = [[0, 315, 0, 0, 1], [1, 315, 0, 0, 2], [2, 315, 0, 0, 3], [8, 300, 0, 0, 4]]
    rep = gear.gear_report(rows, {}, {**gear.DEFAULTS, "low_slot_gap": 11.25})
    assert rep["gaps"] == ["wrist 11 ilvl below your average"]


def test_empty_socket_only_in_gem_slots():
    rows = full_rows(gems=0)
    rep = gear.gear_report(rows, {"enchant_slots": set(), "gem_slots": {1}}, gear.DEFAULTS)
    assert rep["gaps"] == ["neck: empty socket"]


def test_shirt_and_tabard_skipped():
    rows = full_rows(enchant=0, gems=0)
    rows[3][1] = 1       # shirt ilvl 1 must not drag the mean or be flagged low
    rows[17][1] = 1
    rules = {"enchant_slots": {3, 17}, "gem_slots": {3, 17}}
    rep = gear.gear_report(rows, rules, gear.DEFAULTS)
    assert rep == {"ilvl": 300, "gaps": [], "n_gaps": 0}


def test_three_rows_still_give_ilvl():
    rows = [[0, 310, 1, 0, 11], [1, 312, 0, 1, 12], [2, 305, 1, 0, 13]]
    rep = gear.gear_report(rows, gear.roster_rules({"A": rows}), gear.DEFAULTS)
    assert rep["ilvl"] == 309
    assert rep["gaps"] == []


def test_item_id_zero_and_ilvl_zero_ignored():
    rows = [[0, 300, 1, 0, 11], [2, 300, 1, 0, 12], [16, 0, 0, 0, 0], [15, 250, 0, 0, 0],
            [14, 0, 0, 0, 99]]
    rules = {"enchant_slots": {0, 2, 14, 15, 16}, "gem_slots": set()}
    assert gear.gear_report(rows, rules, gear.DEFAULTS) == {"ilvl": 300, "gaps": [], "n_gaps": 0}
    # and they do not count towards the roster majority
    roster = {"A": rows, "B": [[16, 0, 0, 0, 0]]}
    assert 16 not in gear.roster_rules(roster)["enchant_slots"]
    assert gear.gear_report([], rules) == {"ilvl": None, "gaps": [], "n_gaps": 0}


def test_slot_name():
    assert gear.slot_name(0) == "head"
    assert gear.slot_name(11) == "ring 2"
    assert gear.slot_name(99) == "slot 99"
    assert gear.slot_name(0, {"slot_names": {"0": "helm"}}) == "helm"


def test_latest_gear_picks_most_recent_pull_with_gear():
    a_old, a_new = [[0, 300, 0, 0, 1]], [[0, 310, 0, 0, 1]]
    pulls = [
        {"absolute_start_ms": 1000, "gear": {"A": a_old, "B": [[0, 290, 0, 0, 2]]}},
        {"absolute_start_ms": 3000, "gear": {"B": []}},
        {"absolute_start_ms": 2000, "gear": {"A": a_new}},
        {"absolute_start_ms": 4000},
    ]
    by_label = {"A": pulls, "B": pulls, "C": pulls[3:]}
    assert gear.latest_gear(by_label) == {"A": a_new, "B": [[0, 290, 0, 0, 2]]}
    assert gear.latest_gear(pulls) == {"A": a_new, "B": [[0, 290, 0, 0, 2]]}
    assert gear.latest_gear({}) == {}


def test_load_gear_checks_defaults_and_override(tmp_path):
    missing = gear.load_gear_checks(str(tmp_path / "nope.json"))
    assert missing["enchantable"] == "auto" and missing["majority"] == 0.5
    assert missing["skip_slots"] == [3, 17] and missing["low_slot_gap"] == 15
    assert missing["slot_names"]["11"] == "ring 2"
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"_comment": "x", "enchantable": [0, 2], "slot_names": {"0": "helm"}}))
    cfg = gear.load_gear_checks(str(f))
    assert cfg["enchantable"] == [0, 2] and "_comment" not in cfg
    assert cfg["slot_names"]["0"] == "helm" and cfg["slot_names"]["1"] == "neck"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert gear.load_gear_checks(str(bad))["socket_slots"] == "auto"


def test_shipped_config_files_match_defaults():
    for name in ("gear_checks.json", "gear_checks.example.json"):
        cfg = gear.load_gear_checks(f"{gear.CONFIG_DIR}/{name}")
        assert {k: cfg[k] for k in gear.DEFAULTS} == gear.DEFAULTS
