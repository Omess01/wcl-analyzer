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


# --- fetcher hygiene: buffs targetID, nextPageTimestamp pagination, filter variable ---------------

def _buff(src, tgt, ability=1, ts=10_500, kind="applybuff"):
    return {"timestamp": ts, "type": kind, "sourceID": src, "targetID": tgt, "abilityGameID": ability}


def test_attach_casts_keeps_only_buffs_targeting_the_dying_actor():
    lab = Labeller()
    actors = {4: {"name": "Healer", "class": "Priest", "server": "TM"},
              13: {"name": "Tank", "class": "Warrior", "server": "TM"},
              7: {"name": "Helper", "class": "Paladin", "server": "TM"}}
    lab.learn(actors)
    names = {1: "Pain Suppression", 2: "Blessing of Sacrifice", 3: "Power Word: Shield"}
    death = {"actor_id": 4, "seconds_into_fight": 1.0}
    buffs = [_buff(4, 13, 1),    # dying healer casts on the tank: NOT an external they received
             _buff(7, 4, 2),     # someone else on the dying healer: external
             _buff(4, 4, 3)]     # self-buff: not an external
    collect_data.attach_casts(death, [], buffs, {"startTime": 10_000}, actors, lab, names, ["pain sup", "sacrifice", "shield"])
    assert death["externals"] == [[0.5, "Blessing of Sacrifice", "Helper"]]


class _Pool:
    def map(self, fn, items):
        return map(fn, items)


def _page_stub(alias, pages, calls):
    """run_query stub: returns `pages` in order for `alias`, recording (query, variables)."""
    def stub(query, variables):
        calls.append((query, dict(variables)))
        return {"reportData": {"report": {alias: pages[len(calls) - 1]}}}
    return stub


def test_consumable_casts_follow_next_page(monkeypatch, tmp_path):
    import cache
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path))
    calls = []
    pages = [{"data": [{"timestamp": 1}], "nextPageTimestamp": 5000},
             {"data": [{"timestamp": 5000}], "nextPageTimestamp": None}]
    monkeypatch.setattr(collect_data, "run_query", _page_stub("cons_3", pages, calls))
    before = cache.stats["api_calls"]
    fight = {"id": 3, "startTime": 10_000, "endTime": 20_000}
    out = collect_data.get_consumable_casts("ABC", [fight], [111], lambda f: False, _Pool())
    assert out[3] == [{"timestamp": 1}, {"timestamp": 5000}]
    assert len(calls) == 2 and cache.stats["api_calls"] - before == 2
    assert "startTime: 5000," in calls[1][0] and calls[1][1] == calls[0][1]
    assert cache.get_entry(collect_data._cons_key("ABC", 3, [111])) == {"data": out[3]}


def test_first_death_casts_follow_next_page(monkeypatch, tmp_path):
    import cache
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path))
    calls = []

    def stub(query, variables):
        calls.append(query)
        if len(calls) == 1:
            return {"reportData": {"report": {"casts_2": {"data": [{"a": 1}], "nextPageTimestamp": None},
                                              "buffs_2": {"data": [{"b": 1}], "nextPageTimestamp": 12_000}}}}
        return {"reportData": {"report": {"buffs_2": {"data": [{"b": 2}], "nextPageTimestamp": None}}}}
    monkeypatch.setattr(collect_data, "run_query", stub)
    before = cache.stats["api_calls"]
    fight = {"id": 2, "startTime": 10_000, "endTime": 30_000}
    death = {"actor_id": 4, "seconds_into_fight": 5.0}
    out = collect_data.get_first_death_casts("ABC", [(fight, death, False)], 6.0, _Pool())
    assert out[2] == {"casts": [{"a": 1}], "buffs": [{"b": 1}, {"b": 2}]}
    assert len(calls) == 2 and cache.stats["api_calls"] - before == 2
    assert "buffs_2:" in calls[1] and "casts_2:" not in calls[1] and "targetID: 4" in calls[1]


def test_bundle_cinfo_follows_next_page(monkeypatch, tmp_path):
    import cache
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(collect_data, "_bundle_extras_ok", True)
    calls = []

    def stub(query, variables):
        calls.append(query)
        if len(calls) == 1:
            return {"reportData": {"report": {"cinfo_5": {"data": [{"c": 1}], "nextPageTimestamp": 15_000}}}}
        return {"reportData": {"report": {"cinfo_5": {"data": [{"c": 2}], "nextPageTimestamp": None}}}}
    monkeypatch.setattr(collect_data, "run_query", stub)
    before = cache.stats["api_calls"]
    out = collect_data._fetch_bundle_batch("ABC", [{"id": 5, "startTime": 10_000, "endTime": 20_000}], 0)
    assert out[5]["cinfo"] == [{"c": 1}, {"c": 2}]
    assert len(calls) == 2 and cache.stats["api_calls"] - before == 2
    assert "nextPageTimestamp" in calls[0] and "startTime: 15000," in calls[1]


def test_bundle_cinfo_follow_up_failure_degrades_and_is_not_cached(monkeypatch, tmp_path, capsys):
    import cache
    from wcl_client import WCLError
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(collect_data, "_bundle_extras_ok", True)
    monkeypatch.setattr(collect_data, "_cinfo_page_warning_shown", False)
    calls = []

    def stub(query, variables):
        calls.append(query)
        if len(calls) == 1:
            return {"reportData": {"report": {"cinfo_5": {"data": [{"c": 1}], "nextPageTimestamp": 15_000}}}}
        raise WCLError("page 2 failed")
    monkeypatch.setattr(collect_data, "run_query", stub)
    out = collect_data._fetch_bundle_batch("ABC", [{"id": 5, "startTime": 10_000, "endTime": 20_000}], 0)
    assert out[5]["cinfo"] == [{"c": 1}]                      # page 1 kept
    assert out[5]["extras"] is True
    assert len(calls) == 2
    assert cache.get_entry(collect_data._bundle_key("ABC", 5, True)) is None   # re-fetched next run
    assert "combatant info page 2+ unavailable" in capsys.readouterr().out


def test_follow_pages_stops_on_non_advancing_cursor(monkeypatch):
    calls = []
    pages = [{"data": [{"t": 2}], "nextPageTimestamp": 5000}]   # follow-up returns the same cursor again
    monkeypatch.setattr(collect_data, "run_query", _page_stub("x_1", pages, calls))
    fight = {"id": 1, "startTime": 0, "endTime": 10_000}
    out = collect_data._follow_pages("ABC", fight, "test", "x_1", lambda s: f"x_1: events(startTime: {s})",
                                     {"data": [{"t": 1}], "nextPageTimestamp": 5000}, "Q")
    assert out == [{"t": 1}, {"t": 2}]
    assert len(calls) == 1                                    # stopped after one follow-up


def test_follow_pages_stops_on_backwards_cursor(monkeypatch):
    calls = []
    pages = [{"data": [{"t": 2}], "nextPageTimestamp": 4000}]
    monkeypatch.setattr(collect_data, "run_query", _page_stub("x_1", pages, calls))
    fight = {"id": 1, "startTime": 0, "endTime": 10_000}
    out = collect_data._follow_pages("ABC", fight, "test", "x_1", lambda s: f"x_1: events(startTime: {s})",
                                     {"data": [{"t": 1}], "nextPageTimestamp": 5000}, "Q")
    assert out == [{"t": 1}, {"t": 2}] and len(calls) == 1


def test_follow_pages_page_cap(monkeypatch, capsys):
    monkeypatch.setattr(collect_data, "MAX_PAGES", 3)
    monkeypatch.setattr(collect_data, "_pages_cap_warning_shown", False)
    calls = []
    pages = [{"data": [{"t": i}], "nextPageTimestamp": 1000 * (i + 2)} for i in range(10)]   # never ends
    monkeypatch.setattr(collect_data, "run_query", _page_stub("x_1", pages, calls))
    fight = {"id": 1, "startTime": 0, "endTime": 100_000}
    out = collect_data._follow_pages("ABC", fight, "test", "x_1", lambda s: f"x_1: events(startTime: {s})",
                                     {"data": [], "nextPageTimestamp": 1000}, "Q")
    assert len(calls) == 3 and out == [{"t": 0}, {"t": 1}, {"t": 2}]
    assert "after 3 follow-ups" in capsys.readouterr().out


def test_consumable_filter_is_a_graphql_variable(monkeypatch, tmp_path):
    import cache
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(collect_data, "run_query",
                        _page_stub("cons_9", [{"data": [{"x": 1}], "nextPageTimestamp": None}], calls))
    fight = {"id": 9, "startTime": 10_000, "endTime": 20_000}
    collect_data.get_consumable_casts("ABC", [fight], [222, 111], lambda f: False, _Pool())
    (query, variables), = calls
    assert "$filter: String" in query and "filterExpression: $filter" in query
    assert "ability.id in (" not in query and "nextPageTimestamp" in query
    assert variables == {"code": "ABC", "filter": "ability.id in (111,222)"}
    key = collect_data._cons_key("ABC", 9, [111, 222])
    assert key == f"cons:{collect_data.CONSUMABLES_VERSION}:ABC:9:" + __import__("hashlib").sha1(b"111,222").hexdigest()[:12]
    assert cache.get_entry(key) == {"data": [{"x": 1}]}


# ---- specs.py: the one spec / role table -------------------------------------

def _fixture_bundles():
    import glob
    import json
    import os
    out = []
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "fixtures", "cache", "*.json"))):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and "cinfo" in d and "damage" in d:
            out.append(d)
    return out


def test_every_fixture_spec_id_resolves():
    import specs
    bundles = _fixture_bundles()
    assert bundles, "fixture bundles with cinfo missing"
    ids = {ev["specID"] for b in bundles for ev in b.get("cinfo") or [] if ev.get("specID")}
    assert len(ids) >= 10
    assert [i for i in sorted(ids) if specs.spec_of(i) is None] == []


def test_fixture_icon_tokens_match_spec_table():
    import specs
    checked = 0
    for b in _fixture_bundles():
        sid_by_source = {ev["sourceID"]: ev["specID"] for ev in b.get("cinfo") or [] if ev.get("specID")}
        for key in ("damage", "healing"):
            for e in collect_data._table_entries(b.get(key)):
                icon, typ = e.get("icon") or "", e.get("type")
                if "-" not in icon or icon.split("-", 1)[0] != typ or e.get("id") not in sid_by_source:
                    continue
                cls, token, _role, _sup = specs.spec_of(sid_by_source[e["id"]])
                assert (cls, token) == (typ, icon.split("-", 1)[1]), (e.get("name"), icon, sid_by_source[e["id"]])
                checked += 1
    assert checked > 0


def test_role_sets_match_previous_literals():
    import specs
    rs = specs.role_sets()
    assert set(rs["tanks"]) == {"Protection", "Blood", "Vengeance", "Guardian", "Brewmaster"}
    assert set(rs["healers"]) == {"Holy", "Discipline", "Restoration", "Mistweaver", "Preservation"}
    assert rs["support"] == ["Augmentation"]
    assert len(specs.SPECS) == 40   # 39 + Devourer (1480)
    # tokens shared by two classes must share a role, or token-based role lookup would be ambiguous
    roles: dict = {}
    for _cls, tok, role, _simc, _sup in specs.SPECS.values():
        assert roles.setdefault(tok, role) == role, tok
    assert specs.role_of_token("Havoc") == "dps" and specs.role_of_token("Holy") == "healer"


def test_unknown_spec_id_is_none():
    import specs
    assert specs.spec_of(99999) is None and specs.spec_of(None) is None and specs.spec_of("x") is None
    assert specs.spec_of(577) == ("DemonHunter", "Havoc", "dps", False)
    assert specs.spec_of(1473)[3] is True


def test_player_tables_fall_back_to_spec_id_when_icon_has_no_spec():
    lab = Labeller()
    actors = {7: {"name": "Omess", "class": "DemonHunter", "server": "TarrenMill"}}
    lab.learn(actors)
    bundle = {"damage": {"data": {"entries": [{"id": 7, "name": "Omess", "type": "DemonHunter", "icon": "foo.jpg", "total": 5}]}}}
    participants = {"Omess": "DemonHunter"}
    dmg, _ = collect_data.player_tables_from_bundle(bundle, actors, lab, participants)
    assert dmg[0]["spec"] == ""
    dmg, _ = collect_data.player_tables_from_bundle(bundle, actors, lab, participants, {"Omess": 577})
    assert dmg[0]["spec"] == "Havoc"


def test_spec_ids_from_cinfo_warns_once_per_unknown_id(capsys):
    lab = Labeller()
    actors = {1: {"name": "A", "class": "Mage", "server": "S"}, 2: {"name": "B", "class": "Mage", "server": "S"},
              3: {"name": "C", "class": "Mage", "server": "S"}}
    lab.learn(actors)
    collect_data._unknown_spec_ids.discard(4242)
    events = [{"sourceID": 1, "specID": 62}, {"sourceID": 2, "specID": 4242}, {"sourceID": 3, "specID": 4242}, {"sourceID": 9, "specID": 63}]
    got = collect_data.spec_ids_from_cinfo(events, actors, lab, {"A": "Mage", "B": "Mage"})
    collect_data.spec_ids_from_cinfo(events, actors, lab, {"A": "Mage", "B": "Mage"})
    assert got == {"A": 62, "B": 4242}
    assert capsys.readouterr().out.count("unknown specID 4242 for B (Mage)") == 1


def test_fights_query_requests_wipe_called_time():
    assert "wipeCalledTime" in collect_data.FIGHTS_QUERY
