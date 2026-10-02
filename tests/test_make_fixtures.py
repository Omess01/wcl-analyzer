"""Unit tests for tests/make_fixtures.py slim() / clean() on synthetic cache files (no network)."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_fixtures as mf   # noqa: E402  (main() is behind __main__, so importing is side-effect free)


def _write(d, name, data):
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _entry(pid, icon, typ, n_abilities=12):
    return {"name": f"P{pid}", "id": pid, "type": typ, "icon": icon, "total": 1000 * pid, "itemLevel": 700,
            "activeTime": 100, "overheal": 5,
            "abilities": [{"name": f"a{i}", "total": i} for i in range(n_abilities)],
            "gear": [{"id": 1}], "targets": [{"name": "Boss", "total": 1}],
            "talents": [{"id": 9}], "damageAbilities": [{"x": 1}], "pets": [{"p": 1}],
            "given": [{"g": 1}], "taken": [{"t": 1}]}


def _cinfo(pid, fight=1):
    return {"timestamp": 1, "type": "combatantinfo", "fight": fight, "sourceID": pid, "specID": 1,
            "auras": [{"ability": 5}], "gear": [{"id": 2}], "talentTree": [{"id": 3}],
            "strength": 1, "agility": 2, "stamina": 3, "intellect": 4, "critSpell": 5, "hasteSpell": 6,
            "mastery": 7, "versatilityDamageDone": 8, "pvpTalents": [{"id": 0}], "expansion": "x"}


@pytest.fixture
def bundle(tmp_path):
    # cinfo order puts four dps first; the role pick must still reach the tank (6) and healer (7)
    entries = [_entry(i, "Mage-Frost", "Mage") for i in range(1, 6)]
    entries.append(_entry(6, "Warrior-Protection", "Warrior"))
    entries.append(_entry(7, "Priest-Holy", "Priest"))
    data = {"damage": {"data": {"entries": entries}},
            "healing": {"data": {"entries": [_entry(7, "Priest-Holy", "Priest")]}},
            "deaths": [], "cinfo": [_cinfo(i) for i in range(1, 8)]}
    return _write(str(tmp_path), "bundle.json", data)


def test_tables_drop_keys_and_truncate_abilities(bundle):
    mf.slim(os.path.dirname(bundle))
    data = _read(bundle)
    for key in ("damage", "healing"):
        for e in data[key]["data"]["entries"]:
            for k in mf._TABLE_DROP:
                assert e[k] in ([], None), (k, e[k])
            assert e["gear"] == [{"id": 1}]
            assert e["targets"] == [{"name": "Boss", "total": 1}]
            assert e["overheal"] == 5 and e["itemLevel"] == 700
            assert [a["total"] for a in e["abilities"]] == list(range(11, 3, -1))   # top 8 by total


def test_cinfo_full_detail_for_three_players_one_per_role(bundle):
    mf.slim(os.path.dirname(bundle))
    cinfo = {ev["sourceID"]: ev for ev in _read(bundle)["cinfo"]}
    full = {sid for sid, ev in cinfo.items() if "gear" in ev}
    assert len(full) == 3
    assert {6, 7} <= full                      # tank + healer picked despite cinfo order
    for sid, ev in cinfo.items():
        assert set(mf._CINFO_KEEP) <= set(ev)
        assert "pvpTalents" not in ev and "expansion" not in ev
        if sid in full:
            assert ev["talentTree"] == [{"id": 3}] and ev["mastery"] == 7 and ev["intellect"] == 4
        else:
            assert "talentTree" not in ev and "mastery" not in ev and "strength" not in ev


def test_cinfo_three_per_fight(tmp_path):
    data = {"damage": {"data": {"entries": []}}, "cinfo": [_cinfo(i, f) for f in (1, 2) for i in range(1, 6)]}
    path = _write(str(tmp_path), "b.json", data)
    mf.slim(str(tmp_path))
    out = _read(path)["cinfo"]
    for f in (1, 2):
        assert sum("gear" in ev for ev in out if ev["fight"] == f) == 3


def test_event_pages_keep_buffs_and_mitigation(tmp_path):
    ev = {"timestamp": 1, "type": "damage", "sourceID": 1, "targetID": 2, "abilityGameID": 3, "amount": 4,
          "buffs": "1.2.", "mitigated": 5, "hitType": 1, "blocked": 6, "sourceMarker": 9, "x": 1}
    path = _write(str(tmp_path), "ev.json", {"reportData": {"report": {"events": {"data": [ev]}}}})
    mf.slim(str(tmp_path))
    out = _read(path)["reportData"]["report"]["events"]["data"][0]
    assert out == {k: v for k, v in ev.items() if k not in ("sourceMarker", "x")}


def test_puller_entries_untouched_shape(tmp_path):
    ev = {"timestamp": 1, "type": "cast", "sourceID": 1, "targetID": 2, "abilityGameID": 3, "fight": 1, "junk": 1}
    path = _write(str(tmp_path), "pull.json", {"damage": [dict(ev)], "casts": [dict(ev)]})
    mf.slim(str(tmp_path))
    out = _read(path)
    assert set(out) == {"damage", "casts"}
    for key in ("damage", "casts"):
        assert out[key] == [{k: v for k, v in ev.items() if k != "junk"}]


def test_report_meta_and_non_bundles_skipped(tmp_path):
    meta = _write(str(tmp_path), "report_meta.json", {"cinfo": [{"gear": 1}]})
    other = _write(str(tmp_path), "other.json", {"foo": [1, 2]})
    mf.slim(str(tmp_path))
    assert _read(meta) == {"cinfo": [{"gear": 1}]}
    assert _read(other) == {"foo": [1, 2]}


def test_clean_empties_dir(tmp_path):
    d = tmp_path / "cache"
    (d / "sub").mkdir(parents=True)
    (d / "a.json").write_text("{}")
    (d / "sub" / "b.json").write_text("{}")
    mf.clean(str(d))
    assert d.is_dir() and list(d.iterdir()) == []


def test_check_budget(tmp_path, monkeypatch):
    (tmp_path / "a.json").write_text("x" * 100)
    monkeypatch.setattr(mf, "SIZE_BUDGET", 50)
    with pytest.raises(SystemExit):
        mf.check_budget(str(tmp_path))
    monkeypatch.setattr(mf, "SIZE_BUDGET", 1000)
    mf.check_budget(str(tmp_path))
