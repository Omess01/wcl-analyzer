"""Pure-function tests: no fixtures, no network."""

import collect_data
from collect_data import aggregate_damage, attach_recaps, Labeller, is_defensive, DEFAULT_DEFENSIVES


def ev(player, ability, seconds, amount=100, tick=False, self_=False, source="Boss"):
    return {"player": player, "class": "Mage", "ability": ability, "seconds": seconds, "amount": amount,
            "is_tick": tick, "self": self_, "source": source, "absorbed": 0, "overkill": 0, "unmitigated": amount, "avoided": False}


def test_hits_count_instances_not_events():
    # a direct hit + 8 DoT ticks = 1 instance; a pulsing puddle every second for 6 s = 1 instance;
    # then a second puddle 20 s later = another instance
    events = [ev("A", "Goo", 10.0)] + [ev("A", "Goo", 10.0 + i, tick=True) for i in range(1, 9)]
    events += [ev("A", "Puddle", 30.0 + i) for i in range(6)] + [ev("A", "Puddle", 50.0 + i) for i in range(3)]
    rows = {r["ability"]: r for r in aggregate_damage(events)}
    assert rows["Goo"]["hits"] == 1 and rows["Goo"]["ticks"] == 8 and rows["Goo"]["events"] == 9
    assert rows["Puddle"]["hits"] == 2 and rows["Puddle"]["events"] == 9
    assert rows["Puddle"]["times"] == [30.0, 50.0]
    assert rows["Puddle"]["uptime_seconds"] == 5.0 + 2.0


def test_self_damage_excluded_from_stats_but_kept_for_recaps():
    events = [ev("A", "Burning Rush", 5.0, amount=50, self_=True), ev("A", "Boss Slam", 6.0, amount=900)]
    rows = aggregate_damage(events)
    assert [r["ability"] for r in rows] == ["Boss Slam"]
    deaths = [{"player": "A", "class": "Mage", "seconds_into_fight": 6.2, "ability": "Melee"}]
    attach_recaps(deaths, events, window=6)
    d = deaths[0]
    assert d["hits_in_window"] == 2 and d["window_damage"] == 950
    assert d["top_contributor"] == "Boss Slam" and d["one_shot"] is True


def test_labeller_disambiguates_same_name_on_two_realms():
    lab = Labeller()
    lab.learn({1: {"name": "Omess", "class": "DemonHunter", "server": "TarrenMill"},
               2: {"name": "Omess", "class": "Mage", "server": "Silvermoon"},
               3: {"name": "Morse", "class": "Priest", "server": "Hellfire"}})
    assert lab.actor_label({"name": "Omess", "server": "TarrenMill"}) == "Omess-TarrenMill"
    assert lab.label("Omess", "Tarren Mill") == "Omess-TarrenMill"     # rankings spell the realm with a space
    assert lab.actor_label({"name": "Morse", "server": "Hellfire"}) == "Morse"


def test_defensive_patterns():
    pats = [p.lower() for p in DEFAULT_DEFENSIVES]
    assert is_defensive("Blur", pats) and is_defensive("Algari Healing Potion", pats)
    assert not is_defensive("Chaos Strike", pats)


def test_default_difficulties_from_env(monkeypatch):
    monkeypatch.setenv("DIFFICULTIES", "normal, heroic,mythic bogus")
    assert collect_data.default_difficulties() == ["normal", "heroic", "mythic"]
    monkeypatch.setenv("DIFFICULTIES", "")
    assert collect_data.default_difficulties() == ["heroic", "mythic"]


def test_classify_night_rules(monkeypatch, tmp_path):
    from datetime import datetime
    from collect_data import classify_night
    monkeypatch.setattr(collect_data, "NIGHTS_FILE", str(tmp_path / "nights.json"))
    monkeypatch.setenv("MAIN_RAID_DAYS", "Thu,Sun")
    monkeypatch.delenv("OPEN_RAID_DAYS", raising=False)
    thu, mon, wed = datetime(2026, 9, 17), datetime(2026, 9, 21), datetime(2026, 9, 23)
    # no open days configured: every non-main night is open
    assert classify_night(thu, "") == "main" and classify_night(mon, "") == "open" and classify_night(wed, "") == "open"
    # open days configured: other weekdays are not raid nights
    monkeypatch.setenv("OPEN_RAID_DAYS", "Mon")
    assert classify_night(mon, "") == "open" and classify_night(wed, "") is None and classify_night(thu, "") == "main"
    # title keyword marks a non-main night open (whole word: "reopening" does not count); a main day stays main
    assert classify_night(wed, "open raid for alts") == "open"
    assert classify_night(wed, "reopening the vault") is None
    assert classify_night(thu, "open raid for alts") == "main"
    (tmp_path / "nights.json").write_text('{"2026-09-23": "main", "abc": "skip", "_open_days": ["Wed"]}', encoding="utf-8")
    assert classify_night(wed, "") == "main"
    assert classify_night(mon, "", "abc") is None
    monkeypatch.delenv("OPEN_RAID_DAYS")
    (tmp_path / "nights.json").write_text('{"_open_days": ["Wed"]}', encoding="utf-8")
    assert classify_night(wed, "") == "open" and classify_night(mon, "") is None


def _lab():
    lab = Labeller()
    lab.learn({3: {"name": "Giga", "class": "Monk", "server": "Silvermoon"}, 10: {"name": "Maxi", "class": "Paladin", "server": "TarrenMill"}})
    return lab


def test_counts_from_table_walks_wcl_details_level():
    from collect_data import counts_from_table
    actors = {3: {"name": "Giga", "class": "Monk", "server": "Silvermoon"}, 10: {"name": "Maxi", "class": "Paladin", "server": "TarrenMill"}}
    # the real WCL shape: entries[] = dispelled ability, details[] = the players who dispelled it
    table = {"data": {"entries": [{"name": "Essence Rend", "guid": 1, "type": 32, "details": [
        {"name": "Giga", "id": 3, "type": "Monk", "total": 3, "actors": [{"name": "Totemdave", "total": 1}]},
        {"name": "Maxi", "id": 10, "type": "Paladin", "total": 2},
        {"name": "Stranger", "id": 99, "type": "Mage", "total": 5}]}]}}
    out = counts_from_table(table, actors, _lab(), {"Giga": "Monk", "Maxi": "Paladin"})
    assert out == {"Giga": 3, "Maxi": 2}


def test_consumable_categories_and_use():
    from collect_data import consumable_ability_ids, consumable_use, name_matches, DEFAULT_CONSUMABLES
    pats = {k: [p.lower() for p in v] for k, v in DEFAULT_CONSUMABLES.items()}
    assert name_matches("Potion of Recklessness", pats["combat_potion"])
    assert not name_matches("Concentrated Silvermoon Health Potion", pats["combat_potion"])
    assert name_matches("Concentrated Silvermoon Health Potion", pats["healing_potion"])
    names = {1: "Potion of Recklessness", 2: "Silvermoon Health Potion", 3: "Demonic Healthstone", 4: "Lightfused Mana Potion", 5: "Holy Shock"}
    ids = consumable_ability_ids(names, pats)
    assert ids == {1: "combat_potion", 2: "healing_potion", 3: "healthstone", 4: "mana_potion"}
    actors = {3: {"name": "Giga", "class": "Monk", "server": "Silvermoon"}, 10: {"name": "Maxi", "class": "Paladin", "server": "TarrenMill"}}
    parts = {"Giga": "Monk", "Maxi": "Paladin"}
    events = [{"type": "cast", "sourceID": 3, "abilityGameID": 1, "timestamp": 9_000},      # pre-pot, 1 s before the pull
              {"type": "cast", "sourceID": 3, "abilityGameID": 1, "timestamp": 130_000},    # second combat potion, in fight
              {"type": "cast", "sourceID": 10, "abilityGameID": 2, "timestamp": 9_500},     # health potion before the pull: not a pre-pot, not counted
              {"type": "cast", "sourceID": 10, "abilityGameID": 3, "timestamp": 50_000},    # healthstone
              {"type": "cast", "sourceID": 10, "abilityGameID": 2, "timestamp": 60_000},    # health potion
              {"type": "cast", "sourceID": 99, "abilityGameID": 3, "timestamp": 61_000}]    # stranger
    prepot, use = consumable_use(events, actors, _lab(), parts, ids, fight_start=10_000)
    assert prepot == {"Giga"}
    assert use == {"Giga": {"combat_potion": 1}, "Maxi": {"healthstone": 1, "healing_potion": 1}}


def test_excluded_bosses_from_nights_json(monkeypatch, tmp_path):
    from collect_data import excluded_bosses
    monkeypatch.setattr(collect_data, "NIGHTS_FILE", str(tmp_path / "nights.json"))
    monkeypatch.delenv("EXCLUDE_BOSSES", raising=False)
    assert excluded_bosses() == set()
    (tmp_path / "nights.json").write_text('{"_exclude_bosses": ["Nymrissa Wavecaller"]}', encoding="utf-8")
    assert excluded_bosses() == {"nymrissawavecaller"}
    monkeypatch.setenv("EXCLUDE_BOSSES", "Some Boss, Other")
    assert excluded_bosses() == {"someboss", "other"}


def test_detect_breaks_ignores_trash_time(monkeypatch):
    from dash.common import detect_breaks
    monkeypatch.setenv("BREAK_MINUTES", "4.5")
    night = "Thu 2026-09-17"
    pulls = [
        {"night": night, "absolute_start_ms": 0, "duration_seconds": 300, "pull_time": "20:00", "boss_percentage": 50, "kill": False},
        # 10 minutes after the first pull ends, but 7 of them were trash -> only 3 min idle -> no break
        {"night": night, "absolute_start_ms": 900_000, "duration_seconds": 300, "pull_time": "20:15", "boss_percentage": 40, "kill": False},
        # 10 idle minutes -> break
        {"night": night, "absolute_start_ms": 1_800_000, "duration_seconds": 300, "pull_time": "20:30", "boss_percentage": 30, "kill": False},
    ]
    collect_data.NIGHT_FIGHTS.clear()
    collect_data.NIGHT_FIGHTS[night] = [[300_000, 720_000, False]]
    brs = detect_breaks(pulls)
    assert len(brs) == 1 and brs[0]["after"] == 2 and round(brs[0]["gap_min"]) == 10


def test_hp_band_thresholds():
    """Python twin of dash.js hpBand (Task 11): kill, < 10 near, < 40 mid, else far."""
    from dash.common import hp_band
    assert hp_band(0.0, kill=True) == "kill" and hp_band(55, kill=True) == "kill"
    assert hp_band(7) == "near" and hp_band(9.9) == "near"
    assert hp_band(10) == "mid" and hp_band(25) == "mid" and hp_band(39.9) == "mid"
    assert hp_band(40) == "far" and hp_band(60) == "far" and hp_band(100) == "far"


# --- who pulled (pull_initiator) -------------------------------------------------------------

def _pull_setup():
    """Three players, one hunter pet, two enemies (42 boss, 54 add); WCL's Environment actor is -1."""
    actors = {1: {"name": "Voltarian", "class": "Hunter", "server": "TarrenMill"},
              2: {"name": "Totemdave", "class": "Shaman", "server": "TarrenMill"},
              3: {"name": "Morse", "class": "Priest", "server": "Hellfire"},
              4: {"name": "Bystander", "class": "Mage", "server": "TarrenMill"}}
    lab = Labeller()
    lab.learn(actors)
    parts = {"Voltarian": "Hunter", "Totemdave": "Shaman", "Morse": "Priest"}   # Bystander is not in the pull
    names = {1: "Melee", 100: "Kill Command", 101: "Flame Shock", 102: "Ascendance", 103: "Barbed Shot",
             104: "Power Word: Shield", 105: "Taunt"}
    fight = {"startTime": 10_000, "endTime": 200_000}
    return actors, lab, parts, names, fight


def _ev(kind, src, ability, ts, tgt=42):
    return {"type": kind, "sourceID": src, "targetID": tgt, "abilityGameID": ability, "timestamp": ts}


def _who(damage, casts, hostile=frozenset({42, 54}), pets=None):
    from collect_data import pull_initiator
    actors, lab, parts, names, fight = _pull_setup()
    return pull_initiator(damage, casts, fight, actors, lab, parts, set(hostile), {50: 1} if pets is None else pets, names)


def test_pull_initiator_pet_damage_is_credited_to_the_owner():
    out = _who([_ev("damage", 50, 100, 10_004), _ev("damage", 2, 101, 10_053)], [])
    assert out == {"player": "Voltarian", "class": "Hunter", "ability": "Kill Command", "offset_ms": 4,
                   "kind": "damage", "via_pet": True}
    # a pet nobody owns (or an unknown source) is skipped, the next action counts
    out = _who([_ev("damage", 50, 100, 10_004), _ev("damage", 99, 1, 10_010), _ev("damage", 2, 101, 10_053)], [], pets={})
    assert out["player"] == "Totemdave" and out["via_pet"] is False and out["offset_ms"] == 53


def test_pull_initiator_begincast_and_non_damaging_casts_do_not_count():
    # begincast on the boss is not an action yet; a self-buff logged "on the boss" (Ascendance) does not attack it
    casts = [_ev("begincast", 2, 101, 10_000), _ev("cast", 2, 102, 10_039)]
    damage = [_ev("damage", 3, 1, 10_300)]
    assert _who(damage, casts)["player"] == "Morse"
    # ... but a cast whose ability also damages an enemy in the window is the pull (projectile still in flight)
    casts.append(_ev("cast", 1, 103, 10_054))
    damage.append(_ev("damage", 1, 103, 10_485))
    out = _who(damage, casts)
    assert out == {"player": "Voltarian", "class": "Hunter", "ability": "Barbed Shot", "offset_ms": 54,
                   "kind": "cast", "via_pet": False}


def test_pull_initiator_taunt_pull_counts_without_damage():
    # a tank's taunt (105 = Taunt) engages the boss although it never shows up as damage
    casts = [_ev("cast", 3, 105, 10_010), _ev("cast", 2, 102, 10_005)]     # Ascendance "on the boss" at 5 ms still ignored
    damage = [_ev("damage", 1, 103, 10_300)]
    out = _who(damage, casts)
    assert out == {"player": "Morse", "class": "Priest", "ability": "Taunt", "offset_ms": 10, "kind": "cast", "via_pet": False}
    # ... but only when it targets an enemy
    assert _who(damage, [_ev("cast", 3, 105, 10_010, tgt=-1)])["player"] == "Voltarian"


def test_pull_initiator_ignores_casts_on_friendly_or_environment_targets():
    # Flame Shock is damaging, but Morse's earlier cast targets a player (2) and Totemdave's an Environment (-1) target
    casts = [_ev("cast", 3, 101, 10_000, tgt=2), _ev("cast", 2, 101, 10_010, tgt=-1), _ev("cast", 3, 104, 10_020, tgt=3)]
    damage = [_ev("damage", 2, 101, 10_050)]
    out = _who(damage, casts)
    assert out["player"] == "Totemdave" and out["kind"] == "damage" and out["offset_ms"] == 50
    # damage on a non-enemy (friendly NPC / player) never counts
    assert _who([_ev("damage", 3, 1, 10_001, tgt=77)], []) is None


def test_pull_initiator_window_edges():
    from collect_data import PULL_TOLERANCE_MS, PULL_WINDOW_MS
    start = 10_000
    early = _ev("damage", 3, 1, start - PULL_TOLERANCE_MS - 1)      # too early: not part of this pull
    edge = _ev("damage", 2, 101, start - PULL_TOLERANCE_MS)          # inclusive edge
    late = _ev("damage", 1, 103, start + PULL_WINDOW_MS + 1)         # after the window
    assert _who([early, late], []) is None
    out = _who([early, edge, late], [])
    assert out["player"] == "Totemdave" and out["offset_ms"] == -PULL_TOLERANCE_MS
    out = _who([late, _ev("damage", 1, 103, start + PULL_WINDOW_MS)], [])
    assert out["player"] == "Voltarian" and out["offset_ms"] == PULL_WINDOW_MS


def test_pull_initiator_ordering_and_ties():
    # earliest timestamp wins regardless of input order
    out = _who([_ev("damage", 3, 1, 10_300), _ev("damage", 2, 101, 10_100)], [])
    assert out["player"] == "Totemdave"
    # same millisecond: damage beats a (damaging) cast, then log order
    out = _who([_ev("damage", 3, 1, 10_100)], [_ev("cast", 2, 1, 10_100)])
    assert out["player"] == "Morse" and out["kind"] == "damage"
    out = _who([_ev("damage", 1, 103, 10_100), _ev("damage", 3, 1, 10_100)], [])
    assert out["player"] == "Voltarian"
    # a non-participant (bench / other group) is skipped, unknown ability ids get a placeholder name
    out = _who([_ev("damage", 4, 1, 10_000), _ev("damage", 3, 999, 10_001)], [])
    assert out["player"] == "Morse" and out["ability"] == "Ability 999" and out["class"] == "Priest"


def test_pull_initiator_empty_inputs():
    assert _who([], []) is None
    assert _who(None, None) is None
    assert _who([_ev("damage", 2, 101, 10_050)], [], hostile=frozenset()) is None
