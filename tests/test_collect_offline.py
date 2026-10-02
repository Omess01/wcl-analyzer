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


def test_fixture_buff_cast_by_dying_actor_is_not_an_external():
    """Fixture casts entry for dying actor 4 contains Earth Shield (974) applied BY 4 ON 13; it must not count."""
    import json
    import os
    import collect_data
    from conftest import FIXTURE_CACHE
    path = os.path.join(FIXTURE_CACHE, "67b181e8d315886c4bd45dd825c0250c70b71385.json")
    if not os.path.exists(path):
        import pytest
        pytest.skip("fixture casts entry missing")
    with open(path, encoding="utf-8") as f:
        entry = json.load(f)
    buffs = entry["buffs"]
    assert any(e["type"] == "applybuff" and e["sourceID"] == 4 and e["targetID"] == 13 for e in buffs)
    actors = {i: {"name": f"P{i}", "class": "Priest", "server": "TM"}
              for i in {e.get("sourceID") for e in buffs} | {e.get("targetID") for e in buffs}}
    lab = collect_data.Labeller()
    lab.learn(actors)
    t0 = min(e["timestamp"] for e in buffs)
    death = {"actor_id": 4, "seconds_into_fight": 60.0}
    collect_data.attach_casts(death, entry["data"], buffs, {"startTime": t0 - 30_000}, actors, lab,
                              {974: "Earth Shield"}, [""])   # "" matches every ability name
    assert all(caster != "P4" for _, _, caster in death["externals"])
    assert not any(name == "Earth Shield" for _, name, _ in death["externals"])


def test_every_pull_has_spec_ids_and_full_spec_coverage(bosses):
    from dash.common import pull_specs
    pulls = [p for ps in bosses.values() for p in ps]
    assert pulls
    for p in pulls:
        assert "spec_ids" in p
        if p.get("has_extras"):
            assert set(p["spec_ids"]) == set(p["participants"]), p["fight_id"]
        missing = set(p["participants"]) - set(pull_specs(p))
        assert not missing, (p["fight_id"], missing)


def test_every_pull_has_wipe_called_s(bosses):
    pulls = [p for ps in bosses.values() for p in ps]
    for p in pulls:
        assert "wipe_called_s" in p
        w = p["wipe_called_s"]
        assert w is None or (isinstance(w, float) and w >= 0), w


# ---------------------------------------------------------------- Phase 1 T1: analysis core hooks (pull-dict only)

def test_every_pull_has_wipe_cutoff_player_events_and_gear(bosses):
    pulls = [p for ps in bosses.values() for p in ps]
    for p in pulls:
        for key in ("wipe_cutoff_s", "player_events", "gear"):
            assert key in p, (p["fight_id"], key)
        assert set(p["player_events"]) == set(p["participants"]), p["fight_id"]
        for label, d in p["player_events"].items():
            assert {"dtk", "hits", "hits_buffs", "dodge_parry_miss"} <= set(d)
            assert all(isinstance(v, int) and v >= 0 for v in d.values()), (label, d)
            assert d["hits_buffs"] <= d["hits"]
        assert isinstance(p["gear"], dict) and set(p["gear"]) <= set(p["participants"])


def test_fixture_wipe_cutoff_only_on_the_cascade_wipe(bosses):
    by_fid = {p["fight_id"]: p for ps in bosses.values() for p in ps}
    assert by_fid[8]["wipe_cutoff_s"] == 92.5 and not by_fid[8]["kill"]
    for fid in (2, 7, 9):
        assert by_fid[fid]["wipe_cutoff_s"] is None, fid
    # the cutoff is reflected in the digest: the dying tank's damage after 92.5 s is not counted
    assert all(p["wipe_called_s"] is None for p in by_fid.values())


def test_fixture_tanks_have_am_between_50_and_90_with_complete_aura_data(bosses):
    from dash.common import pull_specs, load_avoidable, avoidable_set, ignore_set
    from analysis.player_metrics import player_metrics, COL
    from analysis.mitigation import TANK_BUFFS_SEEN
    cfg = load_avoidable()
    seen_tanks = set()
    for (name, _diff), pulls in bosses.items():
        for p in pulls:
            specs_ = pull_specs(p)
            tanks = [lab for lab, tok in specs_.items() if tok == "Vengeance"]
            assert len(tanks) == 2, (p["fight_id"], tanks)
            pm = player_metrics(p, avoidable_set(cfg, name), ignore_set(cfg), None)
            for lab in tanks:
                d = p["player_events"][lab]
                assert {"am_up", "amw_num", "amw_den", "mit_num", "mit_den"} <= set(d), (lab, d)
                assert d["hits"] > 0 and d["hits_buffs"] / d["hits"] >= 0.95, (p["fight_id"], lab, d)
                v = pm[lab]
                assert 50 <= v[COL["am"]] <= 90, (p["fight_id"], lab, v[COL["am"]])
                assert 40 <= v[COL["amw"]] <= 95 and 50 <= v[COL["mit"]] <= 90, (p["fight_id"], lab)
                seen_tanks.add(lab)
            # non-tanks never get the tank keys
            for lab, d in p["player_events"].items():
                if lab not in tanks:
                    assert "am_up" not in d and "mit_num" not in d, (lab, d)
    assert seen_tanks == {"Airohdh", "Ixavior"}
    assert TANK_BUFFS_SEEN["Vengeance"][203819] > 1000 and set(TANK_BUFFS_SEEN) == {"Vengeance"}


def test_fixture_healing_rows_carry_overheal_and_events_carry_aura_keys(bosses):
    pulls = [p for ps in bosses.values() for p in ps]
    for p in pulls:
        assert p["healing_done"], p["fight_id"]
        for row in p["healing_done"]:
            assert isinstance(row["overheal"], int) and row["overheal"] >= 0
        assert any(row["overheal"] > 0 for row in p["healing_done"])
        # the death recaps keep the raw event dicts, which now carry the aura / mitigation keys
        for d in p["deaths"]:
            for e in d.get("recap") or []:
                assert {"buffs", "mitigated", "hit_type", "blocked"} <= set(e)


def test_fixture_parses_on_kills_carry_bracket_and_spec(bosses):
    pulls = [p for ps in bosses.values() for p in ps]
    kills = [p for p in pulls if p["kill"]]
    assert len(kills) == 3
    for p in kills:
        assert p["parses"], p["fight_id"]
        for label, pr in p["parses"].items():
            assert label in p["participants"]
            assert pr.get("spec"), (label, pr)
            for metric in ("dps", "hps"):
                if metric in pr:
                    assert isinstance(pr["b" + metric], int) and 0 <= pr["b" + metric] <= 100, (label, pr)
                    assert 0 <= pr[metric] <= 100
    assert all(p["parses"] == {} for p in pulls if not p["kill"])


def test_fixture_gear_has_18_rows_for_every_damage_table_player(bosses):
    pulls = [p for ps in bosses.values() for p in ps]
    for p in pulls:
        for row in p["damage_done"]:
            rows = p["gear"].get(row["name"])
            assert rows is not None and len(rows) == 18, (p["fight_id"], row["name"])
            assert [r[0] for r in rows] == list(range(18))
            for slot, ilvl, enchant, gems, item in rows:
                assert all(isinstance(x, int) for x in (slot, ilvl, enchant, gems, item))
            assert sum(1 for r in rows if r[2]) >= 4 and sum(r[3] for r in rows) >= 1   # enchants and gems are read
        # cinfo gear (no slot) is only the fallback: the full-cinfo players already have table gear
        assert len(p["gear"]) == len(p["damage_done"])


def test_fixture_player_metrics_vectors_for_every_participant(bosses):
    from dash.common import load_avoidable, avoidable_set, ignore_set, pull_specs
    from analysis.player_metrics import player_metrics, PM_COLS, COL, trim
    cfg = load_avoidable()
    for (name, _diff), pulls in bosses.items():
        for p in pulls:
            pm = player_metrics(p, avoidable_set(cfg, name), ignore_set(cfg), None)
            assert set(pm) == set(p["participants"])
            healers = {lab for lab, tok in pull_specs(p).items() if tok in ("Mistweaver", "Holy")}
            assert len(healers) == 2
            for lab, v in pm.items():
                assert len(v) == len(PM_COLS) and len(trim(v)) <= len(PM_COLS)
                assert v[COL["act"]] is not None and v[COL["ilvl"]] and v[COL["alv"]] >= 1
                assert v[COL["dtk"]] is not None and v[COL["prep"]] is not None
                assert (v[COL["hps"]] is not None) == (lab in healers)
                assert (v[COL["oh"]] is not None) == (lab in healers)
                assert (v[COL["rp"]] is not None) == bool(p["kill"]), (lab, p["fight_id"])
                assert v[COL["gap"]] is None   # no gear module wired in yet
            if p["fight_id"] == 8:   # the cascade wipe: deaths after 92.5 s do not count, fd / alv still do
                assert sum(v[COL["dth"]] for v in pm.values()) == 4
                assert sum(v[COL["fd"]] for v in pm.values()) == 1
                assert any(v[COL["alv"]] > 93 for v in pm.values())


def test_build_dashboard_tank_buffs_seen_and_mitigation_warnings(bosses, tmp_path, monkeypatch, capsys):
    import json
    import build_dashboard
    monkeypatch.setattr(build_dashboard, "DATA_DIR", str(tmp_path))
    path = build_dashboard.write_tank_buffs_seen()
    assert path and path.endswith("tank_buffs_seen.json")
    with open(path, encoding="utf-8") as f:
        seen = json.load(f)
    assert set(seen) == {"Vengeance"} and len(seen["Vengeance"]) <= 25
    assert "203819" in seen["Vengeance"] and "187827" in seen["Vengeance"] and "207771" in seen["Vengeance"]
    # every configured Vengeance id (Demon Spikes, Metamorphosis, Fiery Brand, Soul Barrier) was up on a fixture tank at
    # least once, and the other specs had no tank in the build -> no warning
    assert build_dashboard.tank_mitigation_warnings() == []
    # an id never seen on a Vengeance tank and an unknown spec key are reported
    from analysis.mitigation import load_tank_mitigation
    cfg = load_tank_mitigation()
    cfg["Vengeance"]["major"].add(999999)
    cfg["Vengeance"]["names"][999999] = "Made Up"
    cfg["Prot Pally"] = {"am": {1}, "major": set(), "names": {}}
    try:
        warnings = build_dashboard.tank_mitigation_warnings()
        assert len(warnings) == 2, warnings
        assert any("Made Up (999999)" in w and "never seen in any Vengeance tank" in w for w in warnings), warnings
        assert any("unknown spec key 'Prot Pally'" in w for w in warnings), warnings
        build_dashboard.validate_config(bosses)
        out = capsys.readouterr().out
        assert "Made Up (999999)" in out and "Prot Pally" in out
    finally:
        cfg["Vengeance"]["major"].discard(999999)
        cfg["Vengeance"]["names"].pop(999999, None)
        cfg.pop("Prot Pally", None)
    # an empty counter writes nothing (keeps a real build's file intact when tests run)
    from analysis.mitigation import TANK_BUFFS_SEEN
    saved = dict(TANK_BUFFS_SEEN)
    TANK_BUFFS_SEEN.clear()
    try:
        assert build_dashboard.write_tank_buffs_seen() is None
    finally:
        TANK_BUFFS_SEEN.update(saved)
