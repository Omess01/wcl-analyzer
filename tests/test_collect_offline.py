"""Replays one real report from tests/fixtures with the network switched off."""


def test_collect_replays_report_from_fixtures(bosses):
    assert bosses, "no pulls collected from fixtures"
    pulls = [p for ps in bosses.values() for p in ps]
    assert len(pulls) >= 3
    for p in pulls:
        for key in ("boss_percentage", "fight_percentage", "phase_timeline", "participants", "deaths", "damage_taken",
                    "damage_done", "healing_done", "interrupts", "dispels", "consumables", "night_type"):
            assert key in p, key
        assert p["participants"], "every pull has participants"
        assert set(p["damage_done"][0].keys()) >= {"name", "class", "spec", "total", "active_seconds", "ilvl"}
        # kills are 0% on both scales
        if p["kill"]:
            assert p["boss_percentage"] == 0.0 and p["fight_percentage"] == 0.0
        # every damage-done row is a participant (no summoned guardians)
        assert all(e["name"] in p["participants"] for e in p["damage_done"])
        # phase timeline is chronological and starts at 0
        pt = p["phase_timeline"]
        if pt:
            assert pt[0][1] == 0.0 and [t for _, t in pt] == sorted(t for _, t in pt)


def test_first_death_has_cast_data_and_recap(bosses):
    firsts = [p["deaths"][0] for ps in bosses.values() for p in ps if p["deaths"]]
    assert firsts, "fixture report should contain deaths"
    d = firsts[0]
    assert "recap" in d and "top_contributor" in d and "one_shot" in d
    assert d.get("has_cast_data") is True and isinstance(d.get("casts"), list) and isinstance(d.get("defensives"), list)
    assert isinstance(d.get("externals"), list)


def test_interrupts_dispels_consumables_present(bosses):
    pulls = [p for ps in bosses.values() for p in ps]
    assert all(isinstance(p["interrupts"], dict) and isinstance(p["dispels"], dict) and isinstance(p["consumable_use"], dict) for p in pulls)
    # the fixture night has dispels (Detox / Cleanse) - the nested WCL table must be read
    assert sum(sum(p["dispels"].values()) for p in pulls) > 0
    # potions / healthstones come from filtered cast events, not from the Casts table (which omits item uses)
    used = sum(sum(u.values()) for p in pulls for u in p["consumable_use"].values())
    assert used > 0


def test_consumables_snapshot_present(bosses):
    pulls = [p for ps in bosses.values() for p in ps]
    with_cons = [p for p in pulls if p["consumables"]]
    assert with_cons, "combatant info should give consumables per player"
    p = with_cons[0]
    assert set(p["consumables"]) <= set(p["participants"])
    flags = next(iter(p["consumables"].values()))
    assert {"flask", "food", "vantus", "rune", "prepot"} <= set(flags)


def test_night_classification_and_labels(bosses, offline):
    pulls = [p for ps in bosses.values() for p in ps]
    nights = {p["night"] for p in pulls}
    assert len(nights) == 1
    night = next(iter(nights))
    # the fixture report is a Wednesday -> open night under MAIN_RAID_DAYS=Thu,Sun
    assert night.endswith(" open") and pulls[0]["night_type"] == "open"


def test_every_pull_has_a_puller(bosses):
    from collect_data import PULL_TOLERANCE_MS, PULL_WINDOW_MS
    pulls = [p for ps in bosses.values() for p in ps]
    assert all("pulled_by" in p for p in pulls)
    known = [p for p in pulls if p["pulled_by"]]
    # the fixture night: every pull opens with a participant's own damage within the first half second
    assert len(known) == len(pulls) >= 3
    for p in known:
        pb = p["pulled_by"]
        assert set(pb) == {"player", "class", "ability", "offset_ms", "kind", "via_pet"}
        assert pb["player"] in p["participants"] and pb["class"] == p["participants"][pb["player"]]
        assert -PULL_TOLERANCE_MS <= pb["offset_ms"] <= PULL_WINDOW_MS
        assert pb["kind"] in ("damage", "cast") and isinstance(pb["via_pet"], bool)
        assert pb["ability"] and not pb["ability"].startswith("Ability ")
