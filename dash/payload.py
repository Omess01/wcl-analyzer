"""
Per-boss pull grid (server-rendered click surface) and the compressed per-pull
JSON payload that dash.js renders every boss-tab section from.
"""

import base64
import gzip
import json
from collections import Counter

from collect_data import NIGHT_FIGHTS, normalize
from .common import (esc, fmt_duration, pct_color, detect_breaks, break_minutes, avoidable_set, ignore_set, pull_specs)

CONSUMABLE_ORDER = ["flask", "food", "vantus", "rune", "prepot"]
USE_ORDER = ["combat_potion", "healing_potion", "healthstone", "mana_potion"]


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
        if p["kill"]:
            color, label, cls = "#2e8b57", "KILL", "kill"
        else:
            color, label, cls = pct_color(p["boss_percentage"]), f"{p['boss_percentage']:.1f}%", "wipe"
        fp = p.get("fight_percentage")
        fight_line = (f"<div class='pb-fight' title='fight progress left (WCL fight %, accounts for phases)'>fight {fp:.0f}%</div>"
                      if (not p["kill"] and fp is not None and abs(fp - p["boss_percentage"]) > 1) else "")
        phase = f"<div class='pb-phase' title='phase the pull ended in'>{esc(p['phase'])}</div>" if p.get("phase") else ""
        deaths = len(p["deaths"])
        aria = (f"Pull {idx}, {label}{'' if p['kill'] else ' boss HP left'}, {esc(p['night'])} {esc(p['pull_time'])}, "
                f"{fmt_duration(p['duration_seconds'])}, {deaths} deaths" + (f", ended in {esc(p['phase'])}" if p.get("phase") else ""))
        boxes += (
            f"<button type='button' class='pull-box {cls}' data-idx='{idx}' data-night='{esc(p['night'])}' style='border-left-color:{color}' "
            f"aria-pressed='false' aria-label='{aria}. Click to inspect' title='Pull #{idx} - {esc(p['report_title'])} - fight {p['fight_id']} - click to inspect'>"
            f"<div class='pb-pct' style='color:{color}'>{label}</div>"
            f"<div class='pb-meta'>#{idx} &middot; {esc(p['night'][4:])} {esc(p['pull_time'])}</div>"
            f"<div class='pb-meta pb-more'>{fmt_duration(p['duration_seconds'])} &middot; {deaths} <span aria-hidden='true'>&#8224;</span></div>"
            f"{fight_line}{phase}</button>"
        )
        if idx in breaks_after:
            boxes += (f"<div class='pull-break' role='note' aria-label='{breaks_after[idx]:.0f} minute break before the next pull'>"
                      f"<span class='pb-break-label'>break</span>{breaks_after[idx]:.0f} min</div>")
    has_phase = any(p.get("phase") for p in pulls)
    has_fp = any((not p["kill"]) and p.get("fight_percentage") is not None and abs(p["fight_percentage"] - p["boss_percentage"]) > 1 for p in pulls)
    legend = ("<div class='grid-legend muted'>each box: <b>boss HP left</b> (or KILL; red = far from a kill, green = close) &middot; #pull &middot; date and start time &middot; "
              "duration &middot; deaths"
              + (" &middot; <span class='pb-fight'>fight %</span> = WCL fight progress left when it differs from boss HP (phases, council bosses)" if has_fp else "")
              + (" &middot; <span class='pb-phase'>phase the pull ended in</span>" if has_phase else "") + "</div>")
    return (f"<div class='chips'>{chips}<label class='filter' style='margin:0'><input type='checkbox' class='compactGrid'> compact grid</label>"
            f"<span class='muted chip-hint'>click a pull to inspect it &middot; ctrl/shift-click to add &middot; Esc clears</span></div>"
            f"{legend}"
            f"<div class='pull-grid' data-tab='{tab_id}' role='group' aria-label='Pulls'>{boxes}</div>"
            f"<div class='pull-detail open' id='detail_{tab_id}' aria-live='polite'></div>")


def _death_payload(d: dict, first: bool) -> dict:
    recap = [[round(max(d["seconds_into_fight"] - e["seconds"], 0), 1), e["ability"], e["source"], e["amount"], bool(e.get("self"))]
             for e in (d.get("recap") or [])][-8:]
    out = {"pl": d["player"], "cl": d["class"], "s": d["seconds_into_fight"], "kb": d["ability"],
           "tc": d.get("top_contributor", d["ability"]), "os": bool(d.get("one_shot")),
           "w": d.get("window_damage", 0), "recap": recap}
    if first and d.get("has_cast_data"):
        out["hc"] = True
        out["def"] = [[b, n] for b, n in d.get("defensives") or []]
        out["cs"] = [[b, n] for b, n in d.get("casts") or []]
        out["ext"] = [[b, n, c] for b, n, c in d.get("externals") or []]
    return out


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


def pull_payload(pulls: list[dict], boss_name: str, difficulty: str, avoidable_cfg: dict, compress: bool = True) -> tuple[str, str]:
    """
    (mime type, text) for the <script> element: compact per-pull JSON, gzip +
    base64 unless compress=False. Everything the boss tab shows in the
    browser comes from here.
    """
    avoidable = avoidable_set(avoidable_cfg, boss_name)
    ignored = ignore_set(avoidable_cfg)
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
        deaths = [_death_payload(d, i == 0) for i, d in enumerate(p["deaths"])]
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
            "specs": pull_specs(p),
            "deaths": deaths,
            "dt": dt,
            "parses": p.get("parses") or {},
            "dd": [[e["name"], e["class"], e["spec"], e["total"], round(e["active_seconds"], 1)] for e in (p.get("damage_done") or [])],
            "hd": [[e["name"], e["class"], e["spec"], e["total"], round(e["active_seconds"], 1)] for e in (p.get("healing_done") or [])],
            "ir": p.get("interrupts") or {}, "ds": p.get("dispels") or {},
            "use": {name: [u.get(k, 0) for k in usecats] for name, u in (p.get("consumable_use") or {}).items()},
            "cons": cons, "hx": bool(p.get("has_extras")),
        })
    nights_here = {p["night"] for p in pulls}
    busy = {n: [[int(a), int(e)] for a, e, _ in NIGHT_FIGHTS.get(n, [])] for n in nights_here}
    payload = {
        "boss": boss_name, "diff": difficulty,
        "avoidable": sorted(avoidable), "ignored": sorted(ignored), "break_minutes": break_minutes(), "busy": busy,
        "src": {ab: [s for s, _ in c.most_common(3)] for ab, c in sources.items()},
        "cats": cats, "usecats": usecats,
        "pulls": out,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if not compress:
        return "application/json", text.replace("</", "<\\/")
    blob = gzip.compress(text.encode("utf-8"), compresslevel=9)
    return "application/gzip+base64", base64.b64encode(blob).decode("ascii")
