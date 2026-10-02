"""Severity engine: Good / Watch / Note per player x night x metric (design 2026-09-25 §7.3, Phase 1 plan T4).

The single scorer. Python emits every item; the browser only orders, filters and renders (public cap of <= 3 Watch
and >= 1 Good is applied in JS from `level` + `score`). Imports: stdlib + `specs` only - the PM column order arrives
as the `cols` argument so this module never imports `analysis.player_metrics`, `dash` or `collect_data`.

Inputs (see `compute`)
    bosses        {(boss, difficulty): [pull, ...]} - the structure `dash.page.build_html` receives. Fields read from a
                  pull dict: `night` (str; derived from `absolute_start_ms` when missing), `night_type` ("main" default),
                  `absolute_start_ms` (fallback `start_ms`), `duration_seconds`, `participants` {label: class} and
                  `deaths[0]` -> `player`, `has_cast_data`, `defensives`, `externals` (the `nodef` metric).
    pm_by_key     {(boss, difficulty): [{label: vec}, ...]} aligned index-for-index with `bosses[key]`; `vec` is a
                  (possibly trailing-trimmed) list in `cols` order, small ints or None.
    specs_by_key  same alignment, {label: spec_token}; role via `specs.role_of_token`, support flag via `specs.SPECS`.
    cols          the PM column list (Contract A).

Output
    {"sev": {label: {night: [item, ...]}}, "advice": ADVICE, "nights": [[night, type, startMs], ...]}
    item = [metric, value, baseline, bkind, level, score, tpl, affected, pulls]
        metric    PM column name or `nodef` | `prepot` | `dps_ratio`
        value     the night value (see `aggregate_night`), rounded to 2 decimals
        baseline  number or None; bkind in own | role | cotank | band | None
        level     good | watch | note
        score     |value - baseline| / tolerance x affected / pulls (0 for Note-only metrics)
        tpl       ADVICE key (equals metric)
        affected  Watch/Note: pulls worse than the baseline beyond the tolerance; Good: pulls better beyond the
                  tolerance; prep/prepot: missed pulls; nodef: first deaths without a defensive (always). Fills `{n}`.
        pulls     pulls the value covers (denominator of `affected`). Fills `{pulls}`.
    With `named=True` every item gets a 10th element `rank` ("3 of 12" among same-role players present on >= 25 % of
    the night's pulls, 1 = best); `named=False` emits exactly 9 elements.

Pinned definitions (plan T4) and judgement calls are listed in the module constants and in `.claude/CHANGES.md`.
"""

from __future__ import annotations

import math
from datetime import datetime
from statistics import median

import specs

SHORT_PULL_S = 60.0           # pulls shorter than this are excluded from SHORT_EXCLUDED metrics
PRESENCE_MIN = 0.25           # a peer must be on >= 25 % of the night's pulls to feed a role median / rank
OWN_HISTORY_MIN_NIGHTS = 2    # own-history baseline needs >= 2 earlier nights of the same type
ROLE_MIN_OTHERS = 3           # role median needs >= 3 other players (tanks use the co-tank instead)
WATCH_MIN_PULLS = 3           # Watch needs affected >= max(3, ceil(0.25 * pulls))
WATCH_MIN_SHARE = 0.25

# metric -> (tolerance, "abs" | "rel", better when "lower" | "higher", tier)   (design §7.3)
RULES: dict[str, tuple[float, str, str, int]] = {
    "dth": (0.15, "abs", "lower", 1),
    "fd": (10.0, "abs", "lower", 1),
    "avm": (0.25, "rel", "lower", 2),
    "nodef": (25.0, "abs", "lower", 3),
    "am": (5.0, "abs", "higher", 3),
    "prep": (1.0, "abs", "lower", 4),
    "act": (3.0, "abs", "higher", 5),
    "dps_ratio": (0.08, "rel", "higher", 6),
    "hps": (0.08, "rel", "higher", 6),
    "oh": (5.0, "abs", "lower", 6),
}
# Note-only metrics -> better when (used only for the named rank); never Watch or Good, score 0
NOTE_ONLY: dict[str, str] = {
    "prepot": "lower", "ilvl": "higher", "rp": "higher", "bp": "higher", "gap": "lower", "ir": "higher", "ds": "higher",
}
NOTE_TIER = 9
BANDS: dict[str, float] = {"act": 90.0, "oh": 30.0, "am": 80.0, "nodef": 50.0}
SHORT_EXCLUDED = frozenset({"act", "dps_ratio", "hps", "oh", "am"})
FIXED_TARGET = frozenset({"prep", "prepot"})   # baseline 0 misses, bkind "band"; prep stays Watch-eligible
LEVEL_ORDER = {"watch": 0, "good": 1, "note": 2}

ADVICE: dict[str, str] = {
    "dth": "Deaths {value} per pull vs {baseline}. Look at the recap of each death: was a defensive or a position available?",
    "fd": "First to die on {value}% of pulls vs {baseline}%. Check what hit you in the seconds before each first death.",
    "avm": "Avoidable hits {value} per minute alive vs {baseline}. Open the avoidable table for the abilities that hit you most.",
    "nodef": "No defensive before {n} of {pulls} first deaths ({value}% vs {baseline}%). Bind a defensive next to your main rotation keys.",
    "am": "Active mitigation up on {value}% of hits taken vs {baseline}%. Keep the mitigation buff rolling before each tank hit.",
    "prep": "Flask, food or rune missing on {n} of {pulls} pulls. Check buffs before every pull, not just the first.",
    "prepot": "Pre-pot flagged on {n} of {pulls} pulls - WCL only sees potions pressed after the pull starts, so this under-reports.",
    "act": "Active {value}% of the pull vs {baseline}%. Fewer gaps between casts: plan movement around your cast queue.",
    "dps_ratio": "Active DPS at {value}% of the other players in your role vs {baseline}%. Compare uptime and cooldown usage on the kill pulls.",
    "hps": "Active HPS {value}k vs {baseline}k. Compare healing cooldown timing with the damage pattern of the fight.",
    "oh": "Overheal {value}% vs {baseline}%. Favour targets that are actually missing health; let HoTs do the top-ups.",
    "ilvl": "Item level {value} (reference {baseline}). See the gear list for enchants and sockets.",
    "rp": "Parse percentile on kills: {value} (reference {baseline}).",
    "bp": "Bracket percentile on kills: {value} (reference {baseline}).",
    "gap": "{value} gear gaps on your latest pull. See the gear list.",
    "ir": "Interrupts {value} per pull (reference {baseline}). Assignment-dependent - informational only.",
    "ds": "Dispels {value} per pull (reference {baseline}). Assignment-dependent - informational only.",
}

_SUPPORT_TOKENS = frozenset(tok for _c, tok, _r, _s, sup in specs.SPECS.values() if sup)


# --------------------------------------------------------------------------
# Pull records
# --------------------------------------------------------------------------

def _night_of(p: dict) -> tuple[str, str, int]:
    """(night, night_type, startMs). `night` falls back to the collector's own format (`%a %Y-%m-%d` + ' open')."""
    ntype = p.get("night_type") or "main"
    start = p.get("absolute_start_ms")
    if start is None:
        start = p.get("start_ms") or 0
    night = p.get("night")
    if not night:
        night = datetime.fromtimestamp(start / 1000).strftime("%a %Y-%m-%d") + (" open" if ntype == "open" else "")
    return str(night), str(ntype), int(start)


def _vec_dict(vec, cols: list[str]) -> dict:
    """Non-null entries of a (possibly trimmed) PM vector keyed by column name."""
    if not vec:
        return {}
    return {cols[i]: v for i, v in enumerate(vec) if i < len(cols) and v is not None}


def _nodef(p: dict, label: str):
    """1 / 0 for the first death of the pull when it is this player's and cast data exists, else None.
    Reads deaths[0].player, .has_cast_data, .defensives, .externals."""
    deaths = p.get("deaths") or []
    if not deaths:
        return None
    d = deaths[0]
    if d.get("player") != label or not d.get("has_cast_data"):
        return None
    return 0 if (d.get("defensives") or d.get("externals")) else 1


def _pull_records(bosses: dict, pm_by_key: dict, specs_by_key: dict, cols: list[str]):
    """-> (nights {night: [type, startMs]}, recs {(label, night): [rec, ...]} in pull order, night_pulls {night: n}).
    rec = {vec, dur, kill, role, spec, support, nodef, ratio, start}."""
    nights: dict[str, list] = {}
    recs: dict[tuple[str, str], list[dict]] = {}
    night_pulls: dict[str, int] = {}
    flat = []
    for key, pulls in bosses.items():
        pms = pm_by_key.get(key) or []
        sps = specs_by_key.get(key) or []
        for i, p in enumerate(pulls):
            flat.append((p, pms[i] if i < len(pms) else {}, sps[i] if i < len(sps) else {}))
    flat.sort(key=lambda t: _night_of(t[0])[2])
    for p, pm, sp in flat:
        pm = pm or {}
        sp = sp or {}
        night, ntype, start = _night_of(p)
        ent = nights.setdefault(night, [ntype, start])
        ent[1] = min(ent[1], start)
        night_pulls[night] = night_pulls.get(night, 0) + 1
        labels = set(pm) | set(p.get("participants") or {})
        info: dict[str, dict] = {}
        for lab in sorted(labels):   # sorted: dict / JSON key order must not depend on set iteration (PYTHONHASHSEED)
            tok = sp.get(lab) or ""
            info[lab] = {
                "vec": _vec_dict(pm.get(lab), cols), "dur": float(p.get("duration_seconds") or 0), "kill": bool(p.get("kill")),
                "role": specs.role_of_token(tok), "spec": tok, "support": tok in _SUPPORT_TOKENS,
                "nodef": _nodef(p, lab), "ratio": None, "start": start,
            }
        # dps_ratio: own active dps vs the median of the other same-role non-support dps players in this pull (>= 3 others)
        dps_players = [(lab, r["vec"]["dps"]) for lab, r in info.items()
                       if r["role"] == "dps" and not r["support"] and r["vec"].get("dps") is not None]
        for lab, own in dps_players:
            others = [v for l2, v in dps_players if l2 != lab]
            if len(others) >= ROLE_MIN_OTHERS:
                m = median(others)
                if m > 0:
                    info[lab]["ratio"] = 100.0 * own / m
        for lab, r in info.items():
            recs.setdefault((lab, night), []).append(r)
    return nights, recs, night_pulls


# --------------------------------------------------------------------------
# Night aggregation
# --------------------------------------------------------------------------

def dominant_role(recs: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in recs:
        counts[r["role"]] = counts.get(r["role"], 0) + 1
    return max(counts, key=lambda k: (counts[k], k)) if counts else "dps"


def aggregate_night(recs: list[dict], role: str) -> dict[str, dict]:
    """Night values for one player from their pull records (chronological).
    -> {metric: {"value": float, "per_pull": [float], "pulls": int}}; metrics without data are absent.

    dth = sum dth / pulls; fd = 100 * first deaths / pulls attended (null fd counts as 0); avm = sum avh / (sum alv / 60)
    over pulls with avh; nodef = 100 * first deaths with cast data and no defensive/external / first deaths with cast
    data (needs >= 2); prep = pulls missing flask, food or rune (bits 1/2/4); prepot = pulls missing bit 8 (only when
    >= 1); act, dps_ratio (dps role), hps + oh (healers), am (tanks) = median over pulls >= 60 s; Note-only: ilvl and
    gap latest, rp/bp mean over kills, ir/ds per pull (only when > 0). Role metrics use pulls played in `role`."""
    out: dict[str, dict] = {}
    n_att = len(recs)
    if not n_att:
        return out

    def put(metric, value, per_pull, pulls):
        out[metric] = {"value": float(value), "per_pull": [float(x) for x in per_pull], "pulls": int(pulls)}

    dth = [r["vec"]["dth"] for r in recs if r["vec"].get("dth") is not None]
    if dth:
        put("dth", sum(dth) / len(dth), dth, len(dth))
    fd = [100.0 * (r["vec"].get("fd") or 0) for r in recs]
    put("fd", sum(fd) / n_att, fd, n_att)
    av = [(r["vec"]["avh"], max(r["vec"].get("alv") or 0, 1)) for r in recs if r["vec"].get("avh") is not None]
    if av:
        alv_total = sum(a for _h, a in av)
        put("avm", sum(h for h, _a in av) / (alv_total / 60.0), [h / (a / 60.0) for h, a in av], len(av))
    nd = [r["nodef"] for r in recs if r["nodef"] is not None]
    if len(nd) >= 2:
        put("nodef", 100.0 * sum(nd) / len(nd), [100.0 * x for x in nd], len(nd))
    prep = [r["vec"]["prep"] for r in recs if r["vec"].get("prep") is not None]
    if prep:
        misses = [0 if (int(v) & 7) == 7 else 1 for v in prep]
        put("prep", sum(misses), misses, len(prep))
        nopot = [0 if (int(v) & 8) else 1 for v in prep]
        if sum(nopot):
            put("prepot", sum(nopot), nopot, len(prep))

    long = [r for r in recs if r["dur"] >= SHORT_PULL_S]
    role_long = [r for r in long if r["role"] == role]
    act = [r["vec"]["act"] for r in long if r["vec"].get("act") is not None]
    if act:
        put("act", median(act), act, len(act))
    if role == "dps":
        ratios = [r["ratio"] for r in role_long if r["ratio"] is not None and not r["support"]]
        if ratios:
            put("dps_ratio", median(ratios), ratios, len(ratios))
    if role == "healer":
        for m in ("hps", "oh"):
            xs = [r["vec"][m] for r in role_long if r["vec"].get(m) is not None]
            if xs:
                put(m, median(xs), xs, len(xs))
    if role == "tank":
        am = [r["vec"]["am"] for r in role_long if r["vec"].get("am") is not None]
        if am:
            put("am", median(am), am, len(am))

    for m in ("ilvl", "gap"):
        xs = [r["vec"][m] for r in recs if r["vec"].get(m) is not None]
        if xs:
            put(m, xs[-1], [], len(xs))
    for m in ("rp", "bp"):
        xs = [r["vec"][m] for r in recs if r["kill"] and r["vec"].get(m) is not None]
        if xs:
            put(m, sum(xs) / len(xs), [], len(xs))
    for m in ("ir", "ds"):
        xs = [r["vec"][m] for r in recs if r["vec"].get(m) is not None]
        if xs and sum(xs) > 0:
            put(m, sum(xs) / len(xs), [], len(xs))
    return out


# --------------------------------------------------------------------------
# Baseline, tolerance, score, level
# --------------------------------------------------------------------------

def baseline(metric: str, own_history: list[float], peers: list[float], role: str) -> tuple[float | None, str | None]:
    """First available of: fixed target (prep/prepot -> 0 misses, 'band'); own history (median of >= 2 earlier nights
    of the same type, 'own'); peers (tanks: median of the co-tank(s), 'cotank'; others: median of >= 3, 'role');
    fixed band (BANDS, not for Note-only metrics); (None, None)."""
    if metric in FIXED_TARGET:
        return 0.0, "band"
    if len(own_history) >= OWN_HISTORY_MIN_NIGHTS:
        return float(median(own_history)), "own"
    if peers:
        if role == "tank":
            return float(median(peers)), "cotank"
        if len(peers) >= ROLE_MIN_OTHERS:
            return float(median(peers)), "role"
    if metric in BANDS and metric not in NOTE_ONLY:
        return BANDS[metric], "band"
    return None, None


def tolerance(metric: str, base: float | None) -> float:
    """Absolute tolerance for a metric. Relative tolerances scale with the baseline; a zero/negative baseline uses the
    relative factor itself as an absolute floor (so an avm baseline of 0 tolerates 0.25 hits per minute)."""
    tol, kind, _dir, _tier = RULES.get(metric, (0.0, "abs", "lower", NOTE_TIER))
    if kind == "rel":
        return tol * base if base is not None and base > 0 else tol
    return tol


def score(value: float, base: float | None, tol: float, affected: int, pulls: int) -> float:
    """|value - baseline| / tolerance x affected / pulls; 0 without a baseline or pulls."""
    if base is None or not pulls or tol <= 0:
        return 0.0
    return abs(value - base) / tol * affected / pulls


def _worse_by(metric: str, value: float, base: float) -> float:
    direction = RULES[metric][2] if metric in RULES else NOTE_ONLY.get(metric, "lower")
    return (value - base) if direction == "lower" else (base - value)


def _num(x):
    if x is None:
        return None
    r = round(float(x), 2)
    return int(r) if r == int(r) else r


def _item(metric: str, agg: dict, base: float | None, bkind: str | None) -> tuple[list, int]:
    """One sev item (9 elements) + its tier for ordering."""
    value, per_pull, pulls = agg["value"], agg["per_pull"], agg["pulls"]
    if metric in NOTE_ONLY:
        affected = int(value) if metric == "prepot" else 0
        return [metric, _num(value), _num(base), bkind, "note", 0, metric, affected, pulls], NOTE_TIER
    tier = RULES[metric][3]
    if base is None:
        return [metric, _num(value), None, None, "note", 0, metric, 0, pulls], tier
    tol = tolerance(metric, base)
    worse = _worse_by(metric, value, base)
    good = worse <= tol
    if metric == "prep":
        affected = int(value)                                   # missed pulls
    elif metric == "nodef":
        affected = int(round(sum(per_pull) / 100.0))            # first deaths without a defensive / external
    elif good:
        affected = sum(1 for v in per_pull if _worse_by(metric, v, base) < -tol)
    else:
        affected = sum(1 for v in per_pull if _worse_by(metric, v, base) > tol)
    sc = score(value, base, tol, affected, pulls)
    if bkind == "band" and metric != "prep":
        level = "note"
    elif good:
        level = "good"
    elif affected >= max(WATCH_MIN_PULLS, math.ceil(WATCH_MIN_SHARE * pulls)):
        level = "watch"
    else:
        level = "note"
    return [metric, _num(value), _num(base), bkind, level, _num(sc), metric, affected, pulls], tier


def _rank(metric: str, value: float, peer_values: list[float]) -> str:
    direction = RULES[metric][2] if metric in RULES else NOTE_ONLY.get(metric, "lower")
    better = sum(1 for v in peer_values if (v < value if direction == "lower" else v > value))
    return f"{better + 1} of {len(peer_values) + 1}"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def compute(bosses: dict, pm_by_key: dict, specs_by_key: dict, cols: list[str], named: bool = False) -> dict:
    """{"sev": {label: {night: [items]}}, "advice": ADVICE, "nights": [[night, type, startMs], ...]} (see module doc)."""
    nights, recs, night_pulls = _pull_records(bosses, pm_by_key, specs_by_key, cols)
    night_list = sorted(nights.items(), key=lambda kv: (kv[1][1], kv[0]))
    night_order = {n: i for i, (n, _m) in enumerate(night_list)}

    # pass A: aggregates per (label, night)
    aggs: dict[tuple[str, str], dict] = {}
    roles: dict[tuple[str, str], str] = {}
    presence: dict[tuple[str, str], float] = {}
    for (lab, night), rs in recs.items():
        role = dominant_role(rs)
        roles[(lab, night)] = role
        aggs[(lab, night)] = aggregate_night(rs, role)
        presence[(lab, night)] = len(rs) / night_pulls[night] if night_pulls.get(night) else 0.0

    # pass B: baselines, levels, scores
    sev: dict[str, dict[str, list]] = {}
    for (lab, night), agg in aggs.items():
        role = roles[(lab, night)]
        ntype = nights[night][0]
        support = any(r["support"] for r in recs[(lab, night)])
        peers_all = [(l2, aggs[(l2, n2)]) for (l2, n2) in aggs
                     if n2 == night and l2 != lab and roles[(l2, n2)] == role
                     and presence[(l2, n2)] >= PRESENCE_MIN and not any(r["support"] for r in recs[(l2, n2)])]
        items: list[tuple[tuple, list]] = []
        for metric, a in agg.items():
            if metric == "dps_ratio" and support:
                continue
            own_hist = [aggs[(lab, n2)][metric]["value"] for (l2, n2) in aggs
                        if l2 == lab and n2 != night and night_order[n2] < night_order[night]
                        and nights[n2][0] == ntype and metric in aggs[(lab, n2)]]
            own_hist.sort()
            peers = [pa[metric]["value"] for _l2, pa in peers_all if metric in pa]
            base, bkind = baseline(metric, own_hist, peers, role)
            item, tier = _item(metric, a, base, bkind)
            if named:
                item.append(_rank(metric, a["value"], peers))
            items.append(((LEVEL_ORDER[item[4]], tier, -float(item[5] or 0), metric), item))
        items.sort(key=lambda t: t[0])
        sev.setdefault(lab, {})[night] = [it for _k, it in items]

    return {
        "sev": sev,
        "advice": dict(ADVICE),
        "nights": [[n, meta[0], meta[1]] for n, meta in night_list],
    }
