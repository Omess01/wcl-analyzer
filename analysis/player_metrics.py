"""
The per-player-per-pull metric vector (Contract A of the Phase 1 plan; design doc 2026-09-25 section 6.10).

`PM_COLS` is defined here and only here: dash/payload.py imports it for the boss-level `pmcols`, the roundtrip test
asserts equality with the plan's list, and analysis/severity.py receives it as `cols`. Adding a column appends.

Imported only from dash/ (never from collect_data), so importing collect_data / dash.common here is cycle-free.
"""

import specs
from collect_data import normalize
from dash.common import pull_specs
from analysis.mitigation import AM_BUFFS_MISSING_MAX

PM_COLS = ["act", "dps", "hps", "dth", "fd", "alv", "avh", "avm", "dtk", "dtps", "prep", "pot", "hs", "ir", "ds",
           "ilvl", "rp", "bp", "oh", "mit", "am", "amw", "gap"]
COL = {name: i for i, name in enumerate(PM_COLS)}

PREP_BITS = (("flask", 1), ("food", 2), ("rune", 4), ("prepot", 8), ("vantus", 16))
GEAR_SKIP_SLOTS = frozenset({3, 17})   # shirt, tabard


def trim(vec: list) -> list:
    """Copy of `vec` with the trailing None values popped (JS tolerates short vectors)."""
    out = list(vec)
    while out and out[-1] is None:
        out.pop()
    return out


def role_of(pull: dict, label: str, specs_by_label: dict | None = None) -> str:
    """'tank' | 'healer' | 'dps' per Contract D: specID (via pull_specs) first, table spec token second, dps default."""
    tokens = specs_by_label if specs_by_label is not None else pull_specs(pull)
    return specs.role_of_token(tokens.get(label, ""))


def _pct(num: float, den: float) -> int | None:
    return round(100 * num / den) if den else None


def player_metrics(pull: dict, avoidable: set, ignored: set, gear_gaps: dict | None = None) -> dict[str, list]:
    """
    {label: vector in PM_COLS order (not trimmed)} for every participant of one pull.

    `avoidable` / `ignored` are normalised ability-name sets (dash.common.avoidable_set / ignore_set); `gear_gaps`
    is {label: gap count} from analysis/gear.py or None (then `gap` is null). Deaths / hits after the pull's
    `wipe_cutoff_s` do not count for dth/avh/avm/dtk/dtps/mit/am/amw; fd and alv ignore the cutoff.
    """
    duration = float(pull.get("duration_seconds") or 0)
    cutoff = pull.get("wipe_cutoff_s")
    deaths = pull.get("deaths") or []
    drows = {e["name"]: e for e in pull.get("damage_done") or []}
    hrows = {e["name"]: e for e in pull.get("healing_done") or []}
    tokens = pull_specs(pull)
    digest = pull.get("player_events")
    gear = pull.get("gear") or {}
    parses = pull.get("parses") or {}
    cons = pull.get("consumables") or {}
    use = pull.get("consumable_use") or {}
    has_extras = bool(pull.get("has_extras"))
    avoid = set(avoidable or set()) - set(ignored or set())
    first_death_label = deaths[0]["player"] if deaths else None
    own_first_death: dict[str, float] = {}
    for d in deaths:
        s = d.get("seconds_into_fight")
        if s is None:
            continue
        if d["player"] not in own_first_death or s < own_first_death[d["player"]]:
            own_first_death[d["player"]] = s
    avoid_times: dict[str, int] = {}
    if avoid:
        for row in pull.get("damage_taken") or []:
            if normalize(row["ability"]) in avoid:
                n = sum(1 for t in (row.get("times") or []) if cutoff is None or t <= cutoff)
                avoid_times[row["player"]] = avoid_times.get(row["player"], 0) + n

    out: dict[str, list] = {}
    for label in pull.get("participants") or {}:
        role = specs.role_of_token(tokens.get(label, ""))
        drow, hrow = drows.get(label), hrows.get(label)
        v = [None] * len(PM_COLS)

        act_row = (hrow or drow) if role == "healer" else (drow or hrow)
        if act_row and duration > 0:
            v[COL["act"]] = round(100 * (act_row.get("active_seconds") or 0) / duration)
        if drow and (drow.get("active_seconds") or 0) >= 1:
            v[COL["dps"]] = round((drow.get("total") or 0) / drow["active_seconds"] / 1000)
        if role == "healer" and hrow and (hrow.get("active_seconds") or 0) >= 1:
            v[COL["hps"]] = round((hrow.get("total") or 0) / hrow["active_seconds"] / 1000)

        v[COL["dth"]] = sum(1 for d in deaths if d["player"] == label
                            and (cutoff is None or (d.get("seconds_into_fight") or 0) <= cutoff))
        if deaths:
            v[COL["fd"]] = 1 if first_death_label == label else 0
        alive = own_first_death.get(label, duration)
        alv = max(1, int(min(alive, duration) if duration > 0 else alive))
        v[COL["alv"]] = alv

        if avoid:
            avh = avoid_times.get(label, 0)
            v[COL["avh"]] = avh
            v[COL["avm"]] = round(avh / (alv / 60) * 10)

        dg = (digest or {}).get(label) if digest is not None else None
        if dg is not None:
            dtk_raw = dg.get("dtk") or 0
            v[COL["dtk"]] = round(dtk_raw / 1000)
            v[COL["dtps"]] = round(dtk_raw / alv / 100)

        if has_extras and label in cons:
            flags = cons[label] or {}
            v[COL["prep"]] = sum(bit for key, bit in PREP_BITS if flags.get(key))
        if use:
            u = use.get(label) or {}
            v[COL["pot"]] = int(u.get("combat_potion") or 0)
            v[COL["hs"]] = int(u.get("healing_potion") or 0) + int(u.get("healthstone") or 0)
        if has_extras:
            v[COL["ir"]] = int((pull.get("interrupts") or {}).get(label, 0) or 0)
            v[COL["ds"]] = int((pull.get("dispels") or {}).get(label, 0) or 0)

        ilvl = (drow or {}).get("ilvl") or (hrow or {}).get("ilvl") or 0
        if ilvl > 0:
            v[COL["ilvl"]] = int(round(ilvl))
        else:
            rows = [r for r in gear.get(label) or [] if r and r[0] not in GEAR_SKIP_SLOTS and (r[1] or 0) > 0]
            if rows:
                v[COL["ilvl"]] = int(round(sum(r[1] for r in rows) / len(rows)))

        pr = parses.get(label)
        if pr:
            metric = "hps" if role == "healer" else "dps"
            if pr.get(metric) is not None:
                v[COL["rp"]] = int(round(pr[metric]))
            if pr.get("b" + metric) is not None:
                v[COL["bp"]] = int(round(pr["b" + metric]))

        if role == "healer" and hrow:
            total, overheal = hrow.get("total") or 0, hrow.get("overheal") or 0
            v[COL["oh"]] = _pct(overheal, total + overheal)

        if role == "tank" and dg is not None:
            if dg.get("mit_den"):
                v[COL["mit"]] = _pct(dg.get("mit_num") or 0, dg["mit_den"])
            hits, hits_buffs = dg.get("hits") or 0, dg.get("hits_buffs") or 0
            if "am_up" in dg and hits > 0 and (hits - hits_buffs) / hits <= AM_BUFFS_MISSING_MAX and hits_buffs > 0:
                v[COL["am"]] = _pct(dg.get("am_up") or 0, hits_buffs)
                if dg.get("amw_den"):
                    v[COL["amw"]] = _pct(dg.get("amw_num") or 0, dg["amw_den"])

        if gear_gaps and gear_gaps.get(label) is not None:
            v[COL["gap"]] = int(gear_gaps[label])
        out[label] = v
    return out
