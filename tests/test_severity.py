"""Synthetic tests for analysis/severity.py (Phase 1 T4). The fixture has one night, so own history is only testable here."""

import json
import re

import pytest

from analysis import severity
from analysis.severity import compute, aggregate_night, baseline, score, tolerance

# Contract A column order (local copy on purpose: the engine takes `cols` as an argument)
COLS = ["act", "dps", "hps", "dth", "fd", "alv", "avh", "avm", "dtk", "dtps", "prep", "pot", "hs", "ir", "ds",
        "ilvl", "rp", "bp", "oh", "mit", "am", "amw", "gap"]

DAY_MS = 86_400_000
T0 = 1_757_400_000_000   # arbitrary epoch ms


def vec(**kw) -> list:
    v = [None] * len(COLS)
    for k, val in kw.items():
        v[COLS.index(k)] = val
    while v and v[-1] is None:
        v.pop()
    return v


def pull(night, start_ms, duration=200.0, kill=False, deaths=None, night_type="main", participants=None):
    return {"night": night, "night_type": night_type, "absolute_start_ms": start_ms, "duration_seconds": duration,
            "kill": kill, "deaths": deaths or [], "participants": participants or {}}


def night_pulls(night, day, n, pm_rows, spec_row, duration=200.0, night_type="main", deaths_rows=None):
    """n pulls on one night; pm_rows[i] = {label: vec}, spec_row = {label: token}. Returns (pulls, pms, specs)."""
    pulls, pms, sps = [], [], []
    for i in range(n):
        row = pm_rows[i] if i < len(pm_rows) else pm_rows[-1]
        d = (deaths_rows[i] if deaths_rows and i < len(deaths_rows) else None) or []
        pulls.append(pull(night, T0 + day * DAY_MS + i * 600_000, duration=duration, deaths=d, night_type=night_type,
                          participants={lab: "X" for lab in row}))
        pms.append(row)
        sps.append(spec_row)
    return pulls, pms, sps


def build(*nights):
    """nights: (pulls, pms, specs) tuples -> (bosses, pm_by_key, specs_by_key) under one boss key."""
    key = ("Boss", "Mythic")
    bosses, pm, sp = {key: []}, {key: []}, {key: []}
    for pulls, pms, sps in nights:
        bosses[key] += pulls
        pm[key] += pms
        sp[key] += sps
    return bosses, pm, sp


def items_of(res, label, night):
    return {it[0]: it for it in res["sev"][label][night]}


# three dps peers who die 0 times, act 95, dps 100k, plus the subject
def dps_row(subject_vec, n_peers=3, peer_dps=100, peer_act=95):
    row = {f"peer{i}": vec(act=peer_act, dps=peer_dps, dth=0, fd=0, alv=200, avh=0, prep=15) for i in range(n_peers)}
    row["Me"] = subject_vec
    return row


def dps_specs(row):
    return {lab: "Havoc" for lab in row}


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------

def test_output_shape_and_nights_chronological():
    rowA = dps_row(vec(act=90, dps=90, dth=1, fd=1, alv=100, avh=2, prep=15))
    n2 = night_pulls("Thu 2026-09-10", 1, 4, [rowA], dps_specs(rowA))
    n1 = night_pulls("Wed 2026-09-09 open", 0, 4, [rowA], dps_specs(rowA), night_type="open")
    res = compute(*build(n2, n1), COLS)
    assert set(res) == {"sev", "advice", "nights"}
    assert res["nights"] == [["Wed 2026-09-09 open", "open", T0], ["Thu 2026-09-10", "main", T0 + DAY_MS]]
    assert res["advice"] is not severity.ADVICE and res["advice"] == severity.ADVICE
    for it in res["sev"]["Me"]["Thu 2026-09-10"]:
        assert len(it) == 9
        metric, value, base, bkind, level, sc, tpl, affected, pulls = it
        assert tpl == metric and tpl in severity.ADVICE
        assert level in ("good", "watch", "note")
        assert bkind in ("own", "role", "cotank", "band", None)
        assert isinstance(affected, int) and isinstance(pulls, int)


def test_json_serialisable_no_nan():
    row = dps_row(vec(act=90, dps=90, dth=1, fd=1, alv=100, avh=2, prep=15, ilvl=300, rp=50, bp=40, gap=2, ir=1, ds=1))
    n = night_pulls("N", 0, 4, [row], dps_specs(row))
    res = compute(*build(n), COLS, named=True)
    text = json.dumps(res, allow_nan=False)
    back = json.loads(text)
    assert back["sev"]["Me"]["N"]


def test_all_null_vector_yields_no_watch():
    row = dps_row(vec())
    n = night_pulls("N", 0, 5, [row], dps_specs(row))
    res = compute(*build(n), COLS)
    its = res["sev"]["Me"]["N"]
    assert all(it[4] != "watch" for it in its)
    # only fd (0 % with null fd counted as 0) can be computed from an empty vector
    assert [it[0] for it in its] == ["fd"]


def test_advice_templates_cover_every_emitted_metric():
    assert set(severity.RULES) | set(severity.NOTE_ONLY) <= set(severity.ADVICE)


def test_night_key_derived_when_missing():
    row = dps_row(vec(dth=0))
    pulls, pms, sps = night_pulls("N", 0, 3, [row], dps_specs(row))
    for p in pulls:
        del p["night"]
        del p["night_type"]
    res = compute(*build((pulls, pms, sps)), COLS)
    assert len(res["nights"]) == 1
    night, ntype, start = res["nights"][0]
    assert ntype == "main" and start == T0
    assert re.fullmatch(r"[A-Z][a-z]{2} \d{4}-\d{2}-\d{2}", night), night


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------

def test_own_history_needs_two_earlier_nights_of_same_type():
    good = dps_row(vec(act=95, dps=100, dth=0, fd=0, alv=200, avh=0, prep=15), n_peers=0)
    bad = dps_row(vec(act=95, dps=100, dth=1, fd=1, alv=100, avh=0, prep=15), n_peers=0)
    sp = dps_specs(bad)
    n1 = night_pulls("N1", 0, 4, [good], sp)
    n2 = night_pulls("N2", 1, 4, [good], sp)
    n3 = night_pulls("N3", 2, 4, [bad], sp)
    res = compute(*build(n1, n2, n3), COLS)
    # night 2 has only one earlier night -> no own history, no peers -> dth has no band -> null baseline Note
    d2 = items_of(res, "Me", "N2")["dth"]
    assert d2[2] is None and d2[3] is None and d2[4] == "note"
    # night 3 has two earlier main nights -> own baseline 0 deaths/pull; 1 death per pull on 4 pulls -> Watch
    d3 = items_of(res, "Me", "N3")["dth"]
    assert d3[1] == 1 and d3[2] == 0 and d3[3] == "own" and d3[4] == "watch" and d3[7] == 4 and d3[8] == 4
    assert d3[5] == pytest.approx(1 / 0.15 * 4 / 4, abs=0.01)


def test_open_nights_do_not_feed_main_night_history():
    good = dps_row(vec(dth=0), n_peers=0)
    bad = dps_row(vec(dth=1), n_peers=0)
    sp = dps_specs(bad)
    o1 = night_pulls("O1", 0, 4, [good], sp, night_type="open")
    o2 = night_pulls("O2", 1, 4, [good], sp, night_type="open")
    m1 = night_pulls("M1", 2, 4, [bad], sp)
    res = compute(*build(o1, o2, m1), COLS)
    assert items_of(res, "Me", "M1")["dth"][3] is None
    # but a third open night does see the two earlier open nights
    o3 = night_pulls("O3", 3, 4, [bad], sp, night_type="open")
    res = compute(*build(o1, o2, m1, o3), COLS)
    assert items_of(res, "Me", "O3")["dth"][3] == "own"


def test_own_history_uses_only_earlier_nights():
    good = dps_row(vec(dth=0), n_peers=0)
    bad = dps_row(vec(dth=1), n_peers=0)
    sp = dps_specs(bad)
    n1 = night_pulls("N1", 0, 4, [bad], sp)
    n2 = night_pulls("N2", 1, 4, [good], sp)
    n3 = night_pulls("N3", 2, 4, [good], sp)
    res = compute(*build(n1, n2, n3), COLS)
    assert items_of(res, "Me", "N1")["dth"][3] is None      # later nights never feed an earlier night


def test_role_median_excludes_self_support_and_low_presence():
    me = vec(act=80, dps=50, dth=0, fd=0, alv=200, avh=0, prep=15)
    row = dps_row(me, n_peers=3, peer_act=95)
    row["Augy"] = vec(act=60, dps=30, dth=0, fd=0, alv=200, avh=0, prep=15)      # support: must not count
    row["Rare"] = vec(act=10, dps=5, dth=0, fd=0, alv=200, avh=0, prep=15)       # present on 1 of 8 pulls
    sp = dps_specs(row)
    sp["Augy"] = "Augmentation"
    row_wo_rare = {k: v for k, v in row.items() if k != "Rare"}
    pulls, pms, sps = night_pulls("N", 0, 8, [row] + [row_wo_rare] * 7, sp)
    res = compute(*build((pulls, pms, sps)), COLS)
    act = items_of(res, "Me", "N")["act"]
    assert act[3] == "role" and act[2] == 95       # median of the 3 regular peers only
    assert act[4] == "watch" and act[7] == 8
    # with only 2 non-support regular peers the role median is unavailable -> band 90 -> Note
    row2 = dps_row(me, n_peers=2, peer_act=95)
    res2 = compute(*build(night_pulls("N", 0, 8, [row2], dps_specs(row2))), COLS)
    act2 = items_of(res2, "Me", "N")["act"]
    assert act2[3] == "band" and act2[2] == 90 and act2[4] == "note"


def test_support_player_gets_no_dps_ratio_and_is_not_a_peer():
    row = dps_row(vec(act=90, dps=100, dth=0, fd=0, alv=200, avh=0, prep=15), n_peers=3)
    row["Augy"] = vec(act=90, dps=30, dth=0, fd=0, alv=200, avh=0, prep=15)
    sp = dps_specs(row)
    sp["Augy"] = "Augmentation"
    res = compute(*build(night_pulls("N", 0, 4, [row], sp)), COLS)
    assert "dps_ratio" not in items_of(res, "Augy", "N")
    assert "dps_ratio" in items_of(res, "Me", "N")


def test_tank_uses_cotank_baseline_else_band():
    row = {"TankA": vec(act=90, dps=40, dth=0, fd=0, alv=200, avh=0, prep=15, mit=50, am=70),
           "TankB": vec(act=90, dps=40, dth=0, fd=0, alv=200, avh=0, prep=15, mit=50, am=85)}
    row.update({f"peer{i}": vec(act=95, dps=100, dth=0, fd=0, alv=200, avh=0, prep=15) for i in range(3)})
    sp = {lab: "Havoc" for lab in row}
    sp["TankA"] = sp["TankB"] = "Vengeance"
    res = compute(*build(night_pulls("N", 0, 5, [row], sp)), COLS)
    am = items_of(res, "TankA", "N")["am"]
    assert am[3] == "cotank" and am[2] == 85 and am[1] == 70 and am[4] == "watch" and am[7] == 5
    assert items_of(res, "TankB", "N")["am"][4] == "good"
    assert items_of(res, "TankA", "N")["dth"][3] == "cotank"
    assert "dps_ratio" not in items_of(res, "TankA", "N")
    # alone -> band 80 -> Note
    row1 = {k: v for k, v in row.items() if k != "TankB"}
    res1 = compute(*build(night_pulls("N", 0, 5, [row1], sp)), COLS)
    am1 = items_of(res1, "TankA", "N")["am"]
    assert am1[3] == "band" and am1[2] == 80 and am1[4] == "note"


def test_healer_gets_oh_and_hps_but_no_am_or_dps_ratio():
    row = dps_row(vec(act=90, dps=100, dth=0, fd=0, alv=200, avh=0, prep=15), n_peers=3)
    row["Heal"] = vec(act=88, hps=120, dth=0, fd=0, alv=200, avh=0, prep=15, oh=45)
    sp = dps_specs(row)
    sp["Heal"] = "Mistweaver"
    res = compute(*build(night_pulls("N", 0, 4, [row], sp)), COLS)
    its = items_of(res, "Heal", "N")
    assert "oh" in its and "hps" in its and "am" not in its and "dps_ratio" not in its
    assert its["oh"][3] == "band" and its["oh"][2] == 30 and its["oh"][4] == "note"
    assert its["hps"][3] is None and its["hps"][4] == "note"
    # healers do not get the dps peers' act as a baseline (different role) -> band
    assert its["act"][3] == "band"


def test_baseline_helper_order():
    assert baseline("prep", [1, 2, 3], [1, 2, 3], "dps") == (0.0, "band")
    assert baseline("dth", [0.5, 1.0, 0.0], [9, 9, 9], "dps") == (0.5, "own")
    assert baseline("dth", [0.5], [1, 2, 3], "dps") == (2.0, "role")
    assert baseline("dth", [0.5], [1, 2], "dps") == (None, None)
    assert baseline("dth", [], [1], "tank") == (1.0, "cotank")
    assert baseline("act", [], [1, 2], "dps") == (90.0, "band")
    assert baseline("ilvl", [], [], "dps") == (None, None)


# --------------------------------------------------------------------------
# Score, level, affected
# --------------------------------------------------------------------------

def test_score_and_tolerance_helpers():
    assert score(1.0, 0.0, 0.15, 4, 4) == pytest.approx(1 / 0.15)
    assert score(1.0, 0.0, 0.15, 2, 4) == pytest.approx(1 / 0.15 / 2)
    assert score(1.0, None, 0.15, 2, 4) == 0.0
    assert tolerance("avm", 4.0) == pytest.approx(1.0)
    assert tolerance("avm", 0.0) == pytest.approx(0.25)
    assert tolerance("dps_ratio", 100.0) == pytest.approx(8.0)
    assert tolerance("dth", 3.0) == 0.15


def test_watch_needs_affected_at_least_max_3_or_25pct():
    # 12 pulls, baseline from 2 earlier nights with 0 deaths; die on 2 pulls -> mean 0.17 > 0.15 but affected 2 < 3 -> Note
    sp = {"Me": "Havoc"}
    good = {"Me": vec(dth=0)}
    n1 = night_pulls("N1", 0, 4, [good], sp)
    n2 = night_pulls("N2", 1, 4, [good], sp)
    rows = [{"Me": vec(dth=1)}] * 2 + [{"Me": vec(dth=0)}] * 10
    n3 = night_pulls("N3", 2, 12, rows, sp)
    res = compute(*build(n1, n2, n3), COLS)
    d = items_of(res, "Me", "N3")["dth"]
    assert d[4] == "note" and d[7] == 2 and d[8] == 12
    # 3 deaths -> Watch
    rows = [{"Me": vec(dth=1)}] * 3 + [{"Me": vec(dth=0)}] * 9
    res = compute(*build(n1, n2, night_pulls("N3", 2, 12, rows, sp)), COLS)
    d = items_of(res, "Me", "N3")["dth"]
    assert d[4] == "watch" and d[7] == 3
    assert d[5] == pytest.approx((3 / 12) / 0.15 * 3 / 12, abs=0.01)
    # 16 pulls: 3 deaths is below ceil(25 %) = 4 -> Note; 4 -> Watch
    rows = [{"Me": vec(dth=1)}] * 3 + [{"Me": vec(dth=0)}] * 13
    res = compute(*build(n1, n2, night_pulls("N3", 2, 16, rows, sp)), COLS)
    assert items_of(res, "Me", "N3")["dth"][4] == "note"
    rows = [{"Me": vec(dth=1)}] * 4 + [{"Me": vec(dth=0)}] * 12
    res = compute(*build(n1, n2, night_pulls("N3", 2, 16, rows, sp)), COLS)
    assert items_of(res, "Me", "N3")["dth"][4] == "watch"


def test_good_within_tolerance_and_good_affected_counts_better_pulls():
    sp = {"Me": "Havoc"}
    hist = {"Me": vec(act=90)}
    n1 = night_pulls("N1", 0, 4, [hist], sp)
    n2 = night_pulls("N2", 1, 4, [hist], sp)
    # act 88 vs own 90: within +-3 -> Good; two pulls at 95 are better beyond tolerance
    rows = [{"Me": vec(act=88)}] * 2 + [{"Me": vec(act=95)}] * 2
    res = compute(*build(n1, n2, night_pulls("N3", 2, 4, rows, sp)), COLS)
    a = items_of(res, "Me", "N3")["act"]
    assert a[4] == "good" and a[3] == "own" and a[2] == 90
    assert a[7] == 2 and a[8] == 4


def test_prep_watch_eligible_prepot_note_only():
    sp = {"Me": "Havoc"}
    # 6 pulls: flask missing on 4 (bits food+rune = 6), pre-pot missing on all (bit 8 never set)
    rows = [{"Me": vec(prep=6)}] * 4 + [{"Me": vec(prep=7)}] * 2
    res = compute(*build(night_pulls("N", 0, 6, rows, sp)), COLS)
    its = items_of(res, "Me", "N")
    prep, prepot = its["prep"], its["prepot"]
    assert prep[4] == "watch" and prep[1] == 4 and prep[2] == 0 and prep[3] == "band" and prep[7] == 4 and prep[8] == 6
    assert prep[5] == pytest.approx(4 / 1 * 4 / 6, abs=0.01)
    assert prepot[4] == "note" and prepot[1] == 6 and prepot[7] == 6 and prepot[8] == 6 and prepot[5] == 0
    # one miss is within tolerance -> Good; two misses -> Note (below the 3-pull floor)
    res = compute(*build(night_pulls("N", 0, 6, [{"Me": vec(prep=14)}] + [{"Me": vec(prep=15)}] * 5, sp)), COLS)
    its = items_of(res, "Me", "N")
    assert its["prep"][4] == "good" and "prepot" not in its
    res = compute(*build(night_pulls("N", 0, 6, [{"Me": vec(prep=9)}] * 2 + [{"Me": vec(prep=15)}] * 4, sp)), COLS)
    assert items_of(res, "Me", "N")["prep"][4] == "note"


def test_prepot_never_watch_even_when_always_missing_with_history():
    sp = {"Me": "Havoc"}
    nights = [night_pulls(f"N{i}", i, 8, [{"Me": vec(prep=7)}], sp) for i in range(4)]
    res = compute(*build(*nights), COLS)
    for n in range(4):
        assert items_of(res, "Me", f"N{n}")["prepot"][4] == "note"


def test_short_pulls_excluded_from_act_dps_ratio_oh_am_but_not_dth_prep_avm():
    # dps subject with 3 peers; 2 long pulls act 95, 3 short pulls act 10 dth 1 prep 6 avh 5
    long_row = dps_row(vec(act=95, dps=100, dth=0, fd=0, alv=200, avh=0, prep=15))
    short_row = dps_row(vec(act=10, dps=10, dth=1, fd=1, alv=30, avh=5, prep=6))
    sp = dps_specs(long_row)
    key = ("Boss", "Mythic")
    bosses = {key: []}
    pm = {key: []}
    spk = {key: []}
    for i in range(2):
        bosses[key].append(pull("N", T0 + i * 600_000, duration=200.0, participants={l: "X" for l in long_row}))
        pm[key].append(long_row)
        spk[key].append(sp)
    for i in range(3):
        bosses[key].append(pull("N", T0 + (i + 2) * 600_000, duration=30.0, participants={l: "X" for l in short_row}))
        pm[key].append(short_row)
        spk[key].append(sp)
    res = compute(bosses, pm, spk, COLS)
    its = items_of(res, "Me", "N")
    assert its["act"][1] == 95 and its["act"][8] == 2
    assert its["dps_ratio"][1] == 100 and its["dps_ratio"][8] == 2
    assert its["dth"][1] == pytest.approx(3 / 5) and its["dth"][8] == 5
    assert its["prep"][1] == 3 and its["prep"][8] == 5
    assert its["avm"][8] == 5 and its["avm"][1] == pytest.approx(15 / ((400 + 90) / 60), abs=0.01)
    assert its["fd"][1] == 60 and its["fd"][8] == 5
    # healer oh / tank am over short pulls only -> metric absent
    row = {"Heal": vec(hps=100, oh=40), "Tank": vec(am=70)}
    sp2 = {"Heal": "Mistweaver", "Tank": "Vengeance"}
    res2 = compute(*build(night_pulls("N", 0, 3, [row], sp2, duration=30.0)), COLS)
    assert "oh" not in items_of(res2, "Heal", "N") and "hps" not in items_of(res2, "Heal", "N")
    assert "am" not in items_of(res2, "Tank", "N")


def test_dps_ratio_uses_per_pull_others_median():
    # pull 1: peers 100/100/200 -> median 100, me 50 -> 50 %; pull 2: peers 50/50/50 -> me 50 -> 100 %
    row1 = {"Me": vec(dps=50), "p0": vec(dps=100), "p1": vec(dps=100), "p2": vec(dps=200)}
    row2 = {"Me": vec(dps=50), "p0": vec(dps=50), "p1": vec(dps=50), "p2": vec(dps=50)}
    sp = dps_specs(row1)
    res = compute(*build(night_pulls("N", 0, 2, [row1, row2], sp)), COLS)
    r = items_of(res, "Me", "N")["dps_ratio"]
    assert r[1] == 75 and r[8] == 2           # median of [50, 100]
    # fewer than 3 others -> no ratio at all
    row3 = {"Me": vec(dps=50), "p0": vec(dps=100), "p1": vec(dps=100)}
    res = compute(*build(night_pulls("N", 0, 2, [row3], dps_specs(row3))), COLS)
    assert "dps_ratio" not in items_of(res, "Me", "N")


def test_dps_ratio_relative_tolerance_and_watch():
    sp = {"Me": "Havoc", "p0": "Havoc", "p1": "Havoc", "p2": "Havoc"}
    hist = {"Me": vec(dps=100), "p0": vec(dps=100), "p1": vec(dps=100), "p2": vec(dps=100)}
    n1 = night_pulls("N1", 0, 4, [hist], sp)
    n2 = night_pulls("N2", 1, 4, [hist], sp)
    low = {"Me": vec(dps=80), "p0": vec(dps=100), "p1": vec(dps=100), "p2": vec(dps=100)}
    res = compute(*build(n1, n2, night_pulls("N3", 2, 4, [low], sp)), COLS)
    r = items_of(res, "Me", "N3")["dps_ratio"]
    assert r[2] == 100 and r[3] == "own" and r[1] == 80 and r[4] == "watch" and r[7] == 4
    assert r[5] == pytest.approx(20 / 8 * 4 / 4, abs=0.01)


def test_nodef_from_first_deaths_needs_two_with_cast_data():
    sp = {"Me": "Havoc", "Other": "Havoc"}
    row = {"Me": vec(dth=1), "Other": vec(dth=0)}

    def death(player, cast=True, defensives=(), externals=()):
        d = {"player": player, "seconds_into_fight": 50.0}
        if cast:
            d.update({"has_cast_data": True, "defensives": list(defensives), "externals": list(externals)})
        return d

    deaths = [
        [death("Me")],                                     # no defensive, no external -> 1
        [death("Me", defensives=[[3.0, "Blur"]])],         # defensive used -> 0
        [death("Me", externals=[[2.0, "Pain Suppression", "Priest"]])],   # external -> 0
        [death("Me", cast=False)],                         # no cast data -> ignored
        [death("Other"), death("Me")],                     # not the first death -> ignored
    ]
    res = compute(*build(night_pulls("N", 0, 5, [row], sp, deaths_rows=deaths)), COLS)
    nd = items_of(res, "Me", "N")["nodef"]
    assert nd[1] == pytest.approx(100 / 3, abs=0.01) and nd[8] == 3 and nd[7] == 1   # affected = n without defensive
    assert nd[3] == "band" and nd[2] == 50 and nd[4] == "note"
    assert "nodef" not in items_of(res, "Other", "N")
    # a single first death with cast data is not enough
    res = compute(*build(night_pulls("N", 0, 2, [row], sp, deaths_rows=[[death("Me")], []])), COLS)
    assert "nodef" not in items_of(res, "Me", "N")


def test_avm_zero_baseline_uses_relative_floor():
    sp = {"Me": "Havoc"}
    clean = {"Me": vec(avh=0, alv=200)}
    n1 = night_pulls("N1", 0, 4, [clean], sp)
    n2 = night_pulls("N2", 1, 4, [clean], sp)
    hits = {"Me": vec(avh=4, alv=120)}     # 2 hits/min on every pull
    res = compute(*build(n1, n2, night_pulls("N3", 2, 4, [hits], sp)), COLS)
    a = items_of(res, "Me", "N3")["avm"]
    assert a[2] == 0 and a[3] == "own" and a[4] == "watch" and a[1] == 2 and a[7] == 4
    assert a[5] == pytest.approx(2 / 0.25, abs=0.01)


# --------------------------------------------------------------------------
# Note-only metrics, ordering, named rank
# --------------------------------------------------------------------------

def test_note_only_metrics_are_notes_with_zero_score():
    sp = {"Me": "Havoc"}
    rows = [{"Me": vec(ilvl=300, rp=50, bp=40, gap=2, ir=2, ds=0)}, {"Me": vec(ilvl=305, rp=70, bp=60, gap=1, ir=0, ds=0)}]
    pulls, pms, sps = night_pulls("N", 0, 2, rows, sp)
    pulls[0]["kill"] = pulls[1]["kill"] = True
    res = compute(*build((pulls, pms, sps)), COLS)
    its = items_of(res, "Me", "N")
    assert its["ilvl"][1] == 305 and its["gap"][1] == 1          # latest
    assert its["rp"][1] == 60 and its["bp"][1] == 50 and its["rp"][8] == 2   # mean over kills
    assert its["ir"][1] == 1 and "ds" not in its                 # per pull; zero totals are not emitted
    for m in ("ilvl", "rp", "bp", "gap", "ir"):
        assert its[m][4] == "note" and its[m][5] == 0


def test_deterministic_ordering_level_tier_score():
    sp = {"Me": "Havoc"}
    hist = {"Me": vec(act=95, dth=0, fd=0, alv=200, avh=0, prep=15, ilvl=300)}
    n1 = night_pulls("N1", 0, 4, [hist], sp)
    n2 = night_pulls("N2", 1, 4, [hist], sp)
    bad = {"Me": vec(act=50, dth=1, fd=1, alv=100, avh=10, prep=6, ilvl=300)}
    res = compute(*build(n1, n2, night_pulls("N3", 2, 4, [bad], sp)), COLS)
    its = res["sev"]["Me"]["N3"]
    levels = [it[4] for it in its]
    assert levels == sorted(levels, key=lambda l: severity.LEVEL_ORDER[l])
    watch = [it for it in its if it[4] == "watch"]
    tiers = [severity.RULES[it[0]][3] for it in watch]
    assert tiers == sorted(tiers)
    # inside a tier, higher score first (dth and fd share tier 1)
    t1 = [it for it in watch if severity.RULES[it[0]][3] == 1]
    assert len(t1) == 2 and t1[0][5] >= t1[1][5]
    assert its[0][0] in ("dth", "fd")
    assert its[-1][4] == "note"
    # identical inputs -> identical output
    assert compute(*build(n1, n2, night_pulls("N3", 2, 4, [bad], sp)), COLS) == res


def test_named_adds_rank_only():
    row = dps_row(vec(act=80, dps=50, dth=2, fd=1, alv=100, avh=3, prep=15), n_peers=3)
    sp = dps_specs(row)
    plain = compute(*build(night_pulls("N", 0, 4, [row], sp)), COLS)
    named = compute(*build(night_pulls("N", 0, 4, [row], sp)), COLS, named=True)
    for a, b in zip(plain["sev"]["Me"]["N"], named["sev"]["Me"]["N"]):
        assert len(a) == 9 and len(b) == 10
        assert a == b[:9]
        assert isinstance(b[9], str) and " of " in b[9]
    its = items_of(named, "Me", "N")
    assert its["dth"][9] == "4 of 4"        # worst of four
    assert items_of(named, "peer0", "N")["dth"][9] == "1 of 4"
    assert its["act"][9] == "4 of 4"
    assert plain["nights"] == named["nights"] and plain["advice"] == named["advice"]


def test_aggregate_night_direct():
    recs = [
        {"vec": {"dth": 1, "fd": 1, "alv": 60, "avh": 2, "act": 90, "prep": 7}, "dur": 100.0, "kill": False, "role": "dps",
         "spec": "Havoc", "support": False, "nodef": 1, "ratio": 90.0, "start": 0},
        {"vec": {"dth": 0, "alv": 200, "avh": 0, "act": 96, "prep": 15}, "dur": 200.0, "kill": True, "role": "dps",
         "spec": "Havoc", "support": False, "nodef": None, "ratio": 110.0, "start": 1},
    ]
    agg = aggregate_night(recs, "dps")
    assert agg["dth"]["value"] == 0.5 and agg["fd"]["value"] == 50.0
    assert agg["avm"]["value"] == pytest.approx(2 / (260 / 60))
    assert "nodef" not in agg
    assert agg["prep"]["value"] == 0 and agg["prepot"]["value"] == 1
    assert agg["act"]["value"] == 93 and agg["dps_ratio"]["value"] == 100.0
    assert aggregate_night([], "dps") == {}
