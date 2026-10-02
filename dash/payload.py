"""
Per-boss pull grid (server-rendered click surface) and the compressed per-pull
JSON payload that dash.js renders every boss-tab section from.
"""

import base64
import gzip
import json
from collections import Counter

import specs
from collect_data import NIGHT_FIGHTS, normalize
from .common import (esc, fmt_duration, hp_band, detect_breaks, break_minutes, avoidable_set, ignore_set, pull_specs,
                     SUPPORT_SPECS)
from analysis.player_metrics import PM_COLS, player_metrics, trim
from analysis.mitigation import am_ids_for, parse_buffs
from analysis import gear as gear_mod
from analysis import severity

CONSUMABLE_ORDER = ["flask", "food", "vantus", "rune", "prepot"]
USE_ORDER = ["combat_potion", "healing_potion", "healthstone", "mana_potion"]


# loading placeholder inside #detail_tabN until the payloads are inflated (dash.js removes it)
SKELETON = "<div class='skeleton' aria-hidden='true'><span></span><span></span><span></span></div>"


def pull_grid(pulls: list[dict], tab_id: str) -> str:
    """WCL-style pull boxes. Click = inspect that pull; ctrl/shift-click = add to selection; night chip = whole night."""
    nights = []
    for p in pulls:
        if p["night"] not in nights:
            nights.append(p["night"])
    chips = "".join(
        f"<button type='button' class='chip' data-night='{esc(n)}' aria-pressed='false'>{esc(n)} "
        f"({sum(1 for p in pulls if p['night'] == n)})</button>"
        for n in nights)
    breaks_after = {br["after"]: br["gap_min"] for br in detect_breaks(pulls)}
    boxes = ""
    for idx, p in enumerate(pulls, start=1):
        cls = hp_band(p["boss_percentage"], p["kill"])
        label = "KILL" if p["kill"] else f"{p['boss_percentage']:.1f}%"
        fp = p.get("fight_percentage")
        fight_line = (f"<div class='pb-fight' title='fight progress left (WCL fight %, accounts for phases)'>fight {fp:.0f}%</div>"
                      if (not p["kill"] and fp is not None and abs(fp - p["boss_percentage"]) > 1) else "")
        phase = f"<div class='pb-phase' title='phase the pull ended in'>{esc(p['phase'])}</div>" if p.get("phase") else ""
        deaths = len(p["deaths"])
        pb = p.get("pulled_by") or {}
        puller = f" - pulled by {esc(pb['player'])}" if pb.get("player") else ""
        aria = (f"Pull {idx}, {label}{'' if p['kill'] else ' boss HP left'}, {esc(p['night'])} {esc(p['pull_time'])}, "
                f"{fmt_duration(p['duration_seconds'])}, {deaths} deaths" + (f", ended in {esc(p['phase'])}" if p.get("phase") else "")
                + (f", pulled by {esc(pb['player'])}" if pb.get("player") else ""))
        boxes += (
            f"<button type='button' class='pull-box {cls}' data-idx='{idx}' data-night='{esc(p['night'])}' "
            f"aria-pressed='false' aria-label='{aria}. Click to inspect' title='Pull #{idx} - {esc(p['report_title'])} - fight {p['fight_id']}{puller} - click to inspect'>"
            f"<div class='pb-pct'>{label}</div>"
            f"<div class='pb-meta'>#{idx} &middot; {esc(p['night'][4:])} {esc(p['pull_time'])}</div>"
            f"<div class='pb-meta pb-more'>{fmt_duration(p['duration_seconds'])} &middot; {deaths} <span aria-hidden='true'>&#8224;</span></div>"
            f"{fight_line}{phase}</button>"
        )
        if idx in breaks_after:
            boxes += (f"<div class='pull-break' role='note' aria-label='{breaks_after[idx]:.0f} minute break before the next pull'>"
                      f"<span class='pb-break-label'>break</span>{breaks_after[idx]:.0f} min</div>")
    has_phase = any(p.get("phase") for p in pulls)
    has_fp = any((not p["kill"]) and p.get("fight_percentage") is not None and abs(p["fight_percentage"] - p["boss_percentage"]) > 1 for p in pulls)
    swatches = " ".join(f"<i class='swatch {b}' aria-hidden='true'></i> {t} &middot;"
                        for b, t in (("kill", "Kill"), ("near", "Under 10 %"), ("mid", "10-40 %"), ("far", "40 % and more")))
    legend = ("<p class='section-note grid-legend'>boss HP left: " + swatches + " each box: #pull &middot; date and start time &middot; "
              "duration &middot; deaths"
              + (" &middot; <span class='pb-fight'>fight %</span> = WCL fight progress left when it differs from boss HP (phases, council bosses)" if has_fp else "")
              + (" &middot; <span class='pb-phase'>phase the pull ended in</span>" if has_phase else "") + "</p>")
    return (f"<div class='chips'>{chips}<label class='filter' style='margin:0'><input type='checkbox' class='compactGrid'> compact grid</label>"
            f"<span class='hint muted'>click a pull to inspect it &middot; ctrl/shift-click to add &middot; Esc clears</span></div>"
            f"{legend}"
            f"<div class='pull-grid' data-tab='{tab_id}' role='group' aria-label='Pulls'>{boxes}</div>"
            f"<div class='pull-detail open' id='detail_{tab_id}' aria-live='polite'>{SKELETON}</div>")


def _death_payload(d: dict, first: bool, avoid: set | None = None, tank_spec: str | None = None) -> dict:
    """
    One death for the browser. `avoid` = normalised (avoidable - ignored) ability names of the boss; `av` is 1 when
    the killing blow is one of them or they did >= 50 % of `window_damage`. `tank_spec` (spec token, dying player is
    a tank) adds a 6th recap element: 1/0 = an active-mitigation aura of that spec was up on the hit, null = the
    event has no `buffs` data (or the spec has no tank_mitigation.json entry).
    """
    am = am_ids_for(tank_spec, d.get("class")) if tank_spec else None
    events = d.get("recap") or []
    recap = []
    for e in events[-8:]:
        row = [round(max(d["seconds_into_fight"] - e["seconds"], 0), 1), e["ability"], e["source"], e["amount"], bool(e.get("self"))]
        if tank_spec:
            b = e.get("buffs")
            row.append(None if (b is None or am is None) else (1 if parse_buffs(b) & am else 0))
        recap.append(row)
    avoid = avoid or set()
    av = 0
    if avoid:
        if normalize(d.get("ability") or "") in avoid:
            av = 1
        else:
            total = d.get("window_damage") or 0
            part = sum(e.get("amount") or 0 for e in events if normalize(e.get("ability") or "") in avoid)
            av = 1 if total > 0 and part >= 0.5 * total else 0
    out = {"pl": d["player"], "cl": d["class"], "s": d["seconds_into_fight"], "kb": d["ability"],
           "tc": d.get("top_contributor", d["ability"]), "os": bool(d.get("one_shot")),
           "w": d.get("window_damage", 0), "av": av, "recap": recap}
    if first and d.get("has_cast_data"):
        out["hc"] = True
        out["def"] = [[b, n] for b, n in d.get("defensives") or []]
        out["cs"] = [[b, n] for b, n in d.get("casts") or []]
        out["ext"] = [[b, n, c] for b, n, c in d.get("externals") or []]
    return out


def _ilvl(e: dict):
    il = e.get("ilvl")
    return int(round(il)) if il else None


def _phase_counts(times: list[float], timeline: list[list]) -> list[int] | None:
    """How many of the instance times fall in each phase of the pull's timeline (None when the pull has no phases)."""
    if not timeline:
        return None
    starts = [t for _, t in timeline]
    counts = [0] * len(starts)
    for t in times:
        idx = 0
        for i, s in enumerate(starts):
            if t >= s:
                idx = i
        counts[idx] += 1
    return counts


def _puller_payload(pb: dict | None) -> list | None:
    """pulled_by -> [label, ability, offset_ms, "d"|"c"] (the class is in the pull's parts), None when unknown."""
    if not pb or not pb.get("player"):
        return None
    return [pb["player"], pb.get("ability") or "", int(pb.get("offset_ms") or 0), "c" if pb.get("kind") == "cast" else "d"]


def _encode(obj, compress: bool) -> tuple[str, str]:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if not compress:
        return "application/json", text.replace("</", "<\\/")
    blob = gzip.compress(text.encode("utf-8"), compresslevel=9)
    return "application/gzip+base64", base64.b64encode(blob).decode("ascii")


def pull_payload(pulls: list[dict], boss_name: str, difficulty: str, avoidable_cfg: dict, compress: bool = True,
                 pm: list[dict] | None = None) -> tuple[str, str]:
    """
    (mime type, text) for the <script> element: compact per-pull JSON, gzip +
    base64 unless compress=False. Everything the boss tab shows in the
    browser comes from here.

    `pm` = per-pull {label: PM vector} aligned with `pulls` (all_metrics()[key]); None computes the vectors here
    without gear gaps (`gap` null).
    """
    avoidable = avoidable_set(avoidable_cfg, boss_name)
    ignored = ignore_set(avoidable_cfg)
    avoid = avoidable - ignored
    sources: dict[str, Counter] = {}
    cats = [c for c in CONSUMABLE_ORDER if any(c in v for p in pulls for v in (p.get("consumables") or {}).values())]
    for p in pulls:
        for c in (p.get("consumables") or {}).values():
            for k in c:
                if k not in cats:
                    cats.append(k)
    usecats = [c for c in USE_ORDER if any(c in v for p in pulls for v in (p.get("consumable_use") or {}).values())]
    for p in pulls:
        for c in (p.get("consumable_use") or {}).values():
            for k in c:
                if k not in usecats:
                    usecats.append(k)
    out = []
    for idx, p in enumerate(pulls, start=1):
        tokens = pull_specs(p)
        deaths = [_death_payload(d, i == 0, avoid,
                                 tokens.get(d["player"]) if specs.role_of_token(tokens.get(d["player"], "")) == "tank" else None)
                  for i, d in enumerate(p["deaths"])]
        vecs = pm[idx - 1] if pm is not None and idx - 1 < len(pm) else player_metrics(p, avoidable, ignored)
        timeline = p.get("phase_timeline") or []
        dt = []
        for x in p["damage_taken"]:
            row = [x["player"], x["ability"], x["hits"], x["amount"],
                   [int(t) for t in x.get("times") or []] if normalize(x["ability"]) in avoidable else None,
                   _phase_counts(x.get("times") or [], timeline)]
            while row and row[-1] is None:
                row.pop()
            dt.append(row)
            src = sources.setdefault(x["ability"], Counter())
            src.update(x.get("sources") or {})
        cons = {name: [1 if c.get(k) else 0 for k in cats] for name, c in (p.get("consumables") or {}).items()}
        out.append({
            "i": idx, "n": p["night"], "t": p["pull_time"], "k": p["kill"],
            "p": round(p["boss_percentage"], 1), "fp": round(p.get("fight_percentage", p["boss_percentage"]), 1),
            "d": p["duration_seconds"], "a": p["absolute_start_ms"], "o": p.get("night_type") == "open",
            "ph": p.get("phase") or "", "pt": timeline,
            "code": p["report_code"], "fid": p["fight_id"],
            "parts": p["participants"],
            "specs": tokens,
            "deaths": deaths,
            "dt": dt,
            "parses": p.get("parses") or {},
            "dd": [[e["name"], e["class"], e["spec"], e["total"], round(e["active_seconds"], 1), _ilvl(e)] for e in (p.get("damage_done") or [])],
            "hd": [[e["name"], e["class"], e["spec"], e["total"], round(e["active_seconds"], 1), _ilvl(e)] for e in (p.get("healing_done") or [])],
            "ir": p.get("interrupts") or {}, "ds": p.get("dispels") or {},
            "use": {name: [u.get(k, 0) for k in usecats] for name, u in (p.get("consumable_use") or {}).items()},
            "cons": cons, "hx": bool(p.get("has_extras")),
            "pb": _puller_payload(p.get("pulled_by")),
            "pm": {label: trim(vec) for label, vec in (vecs or {}).items()},   # last: measured smallest gzip output here
            "wc": p.get("wipe_cutoff_s"),
        })
    nights_here = {p["night"] for p in pulls}
    busy = {n: [[int(a), int(e)] for a, e, _ in NIGHT_FIGHTS.get(n, [])] for n in nights_here}
    payload = {
        "boss": boss_name, "diff": difficulty,
        "avoidable": sorted(avoidable), "ignored": sorted(ignored), "break_minutes": break_minutes(), "busy": busy,
        "src": {ab: [s for s, _ in c.most_common(3)] for ab, c in sources.items()},
        "cats": cats, "usecats": usecats, "pmcols": PM_COLS,
        "pulls": out,
    }
    return _encode(payload, compress)


# --------------------------------------------------------------------------
# Phase 1: per-player metric vectors and the Players-tab data block (Contract E)
# --------------------------------------------------------------------------

def _all_pulls(bosses: dict) -> list[dict]:
    return [p for pulls in bosses.values() for p in pulls]


def gear_rules_for(bosses: dict, gear_cfg: dict | None = None) -> dict:
    """Required enchant / gem slots from the roster majority over every player's latest gear in the build."""
    return gear_mod.roster_rules(gear_mod.latest_gear(_all_pulls(bosses)), gear_cfg)


def all_metrics(bosses: dict, avoidable_cfg: dict, gear_cfg: dict | None = None) -> dict:
    """
    {(boss, difficulty): [{label: untrimmed PM vector}, ...]} aligned with each key's pull list. `gap` is the
    per-pull gear-gap count against the roster rules (gear_cfg None -> analysis.gear.load_gear_checks()).
    """
    cfg = gear_cfg if gear_cfg is not None else gear_mod.load_gear_checks()
    rules = gear_rules_for(bosses, cfg)
    ignored = ignore_set(avoidable_cfg)
    out = {}
    for key, pulls in bosses.items():
        avoidable = avoidable_set(avoidable_cfg, key[0])
        vecs = []
        for p in pulls:
            gaps = {label: gear_mod.gear_report(rows, rules, cfg)["n_gaps"]
                    for label, rows in (p.get("gear") or {}).items() if rows}
            vecs.append(player_metrics(p, avoidable, ignored, gaps or None))
        out[key] = vecs
    return out


def players_data(bosses: dict, ordered: list, avoidable_cfg: dict, pm_by_key: dict, named: bool,
                 gear_cfg: dict | None = None) -> dict:
    """The Contract E dict (see players_payload)."""
    cfg = gear_cfg if gear_cfg is not None else gear_mod.load_gear_checks()
    keys = [key for key, _ in ordered] if ordered else list(bosses)
    specs_by_key = {key: [pull_specs(p) for p in bosses[key]] for key in keys}
    roster_cls: dict[str, str] = {}
    roster_spec: dict[str, Counter] = {}
    roster_pulls: Counter = Counter()
    last_ilvl: dict[str, tuple] = {}
    for key in keys:
        pms = pm_by_key.get(key) or []
        for i, p in enumerate(bosses[key]):
            sp = specs_by_key[key][i]
            vecs = pms[i] if i < len(pms) else {}
            for label, cls in (p.get("participants") or {}).items():
                roster_cls[label] = cls
                roster_pulls[label] += 1
                if sp.get(label):
                    roster_spec.setdefault(label, Counter())[sp[label]] += 1
                v = vecs.get(label) or []
                il = v[PM_COLS.index("ilvl")] if len(v) > PM_COLS.index("ilvl") else None
                start = p.get("absolute_start_ms") or 0
                if il is not None and (label not in last_ilvl or start >= last_ilvl[label][0]):
                    last_ilvl[label] = (start, il)
    roster = {}
    for label in sorted(roster_cls, key=str.lower):
        spec = roster_spec[label].most_common(1)[0][0] if label in roster_spec else ""
        roster[label] = {"cl": roster_cls[label], "spec": spec, "role": specs.role_of_token(spec) if spec else "dps",
                         "pulls": roster_pulls[label], "support": 1 if spec in SUPPORT_SPECS else 0}
    sev = severity.compute({k: bosses[k] for k in keys}, pm_by_key, specs_by_key, cols=PM_COLS, named=named)
    latest = gear_mod.latest_gear(_all_pulls(bosses))
    rules = gear_mod.roster_rules(latest, cfg)
    gear = {}
    for label in roster:
        rep = gear_mod.gear_report(latest.get(label) or [], rules, cfg)
        ilvl = rep["ilvl"] if rep["ilvl"] is not None else (last_ilvl[label][1] if label in last_ilvl else None)
        gear[label] = {"ilvl": ilvl, "gaps": rep["gaps"]}
    ilvls = [g["ilvl"] for g in gear.values() if g["ilvl"] is not None]
    lo, hi = (min(ilvls), max(ilvls)) if ilvls else (None, None)
    for g in gear.values():
        g["ilvl_min"], g["ilvl_max"] = lo, hi
    return {"cols": PM_COLS, "roster": roster, "nights": sev["nights"], "sev": sev["sev"], "gear": gear,
            "advice": sev["advice"], "named": bool(named)}


def players_payload(bosses: dict, ordered: list, avoidable_cfg: dict, pm_by_key: dict, named: bool,
                    compress: bool = True, gear_cfg: dict | None = None) -> tuple[str, str]:
    """
    (mime, text) for <script id='data_tabPlayers'> (Contract E):
    {cols, roster: {label: {cl, spec, role, pulls, support}}, nights: [[night, type, startMs]], sev: {label: {night:
    [items]}}, gear: {label: {ilvl, gaps, ilvl_min, ilvl_max}}, advice: {tpl: sentence}, named}. ilvl_min / ilvl_max
    are the raid-wide range (same on every entry).
    """
    return _encode(players_data(bosses, ordered, avoidable_cfg, pm_by_key, named, gear_cfg), compress)
