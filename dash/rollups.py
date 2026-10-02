"""
Players-tab rollups (Phase 1 T8).

Team numbers without names (`night_series`, `prep_rates`: the public team strip and the Home "Preparation"
insight) and the named-only "Raid lead" section (`rollups_named`). The named section is rendered only for
`--callouts named` builds, which are never posted to Discord. Every table goes through common.table();
headings are h2 / h3 only; no colours here (status = tag class + word).
"""

from collections import Counter, defaultdict
from statistics import median as _median

from collect_data import normalize
from analysis.player_metrics import COL, PM_COLS, role_of
from analysis.severity import LEVEL_ORDER
from .common import (esc, table, kpis, section_note, empty_state, player_cell, avoidable_set, ignore_set, pull_specs,
                     ROLE_LABEL)

LEVEL_WORD = {"watch": "Watch", "good": "Good", "note": "Note"}
LEVEL_TAG = {"watch": "warn", "good": "good", "note": "note"}
BKIND_WORD = {"own": "your earlier nights", "role": "role median", "cotank": "co-tank", "band": "target"}
METRIC_LABEL = {
    "act": "Active time %", "dps": "Active DPS (k)", "hps": "Active HPS (k)", "dth": "Deaths per pull",
    "fd": "First death % of pulls", "alv": "Seconds alive", "avh": "Avoidable hits", "avm": "Avoidable hits / min alive",
    "dtk": "Damage taken (k)", "dtps": "Damage taken / s (k)", "prep": "Pulls missing flask, food or rune",
    "pot": "Combat potions", "hs": "Healing potions + healthstones", "ir": "Interrupts per pull",
    "ds": "Dispels per pull", "ilvl": "Item level", "rp": "Parse %", "bp": "Bracket parse %", "oh": "Overheal %",
    "mit": "Mitigated %", "am": "Active mitigation % of hits", "amw": "Active mitigation % of damage",
    "gap": "Gear gaps", "nodef": "First deaths without a defensive %", "prepot": "Pulls without a pre-pot",
    "dps_ratio": "Active DPS % of role",
}
WATCH_SHOWN = 3            # top Watch items per raider in R1
TOP_ABILITIES = 5          # R3


# --------------------------------------------------------------------------
# Shared night series (no names)
# --------------------------------------------------------------------------

def _num(x) -> str:
    if x is None:
        return "-"
    return f"{x:.0f}" if abs(x - round(x)) < 1e-9 else f"{x:.1f}" if abs(x) >= 10 else f"{x:.2f}".rstrip("0").rstrip(".")


def _v(vec, col: str):
    i = COL[col]
    return vec[i] if vec and i < len(vec) else None


def _flat(bosses: dict, pm_by_key: dict | None) -> list[tuple[tuple, dict, dict]]:
    """[(key, pull, {label: vec})] chronological over every boss."""
    out = []
    for key, pulls in bosses.items():
        pms = (pm_by_key or {}).get(key) or []
        for i, p in enumerate(pulls):
            out.append((key, p, pms[i] if i < len(pms) else {}))
    out.sort(key=lambda t: t[1].get("absolute_start_ms") or 0)
    return out


def nights_in_order(pulls: list[dict]) -> list[str]:
    first: dict[str, int] = {}
    for p in pulls:
        first[p["night"]] = min(first.get(p["night"], p["absolute_start_ms"]), p["absolute_start_ms"])
    return sorted(first, key=first.get)


def prep_rates(pulls: list[dict]) -> dict | None:
    """
    Preparation over player-pulls (same rule as common.night_stats 'prep'): `ff` = share with flask and food among
    player-pulls where both were checked, `rune` = share with a rune among player-pulls where rune was checked
    (None when never checked), `n` = player-pulls checked. None when no pull has consumable data.
    """
    flags = [c for p in pulls for c in (p.get("consumables") or {}).values() if "flask" in c and "food" in c]
    if not flags:
        return None
    runes = [c for p in pulls for c in (p.get("consumables") or {}).values() if "rune" in c]
    return {"n": len(flags), "ff": sum(1 for c in flags if c["flask"] and c["food"]) / len(flags),
            "rune": (sum(1 for c in runes if c["rune"]) / len(runes)) if runes else None}


def _nodef_first(p: dict):
    """True / False for the pull's first death when cast data exists (no defensive and no external), else None."""
    deaths = p.get("deaths") or []
    if not deaths or not deaths[0].get("has_cast_data"):
        return None
    return not (deaths[0].get("defensives") or deaths[0].get("externals"))


def night_series(bosses: dict, pm_by_key: dict | None) -> list[dict]:
    """
    One dict per night, chronological: {night, pulls, prep (prep_rates), avm (non-tank sum avh / (sum alv / 60)
    over player-pulls with an avoidable list; None without one), nodef (share of first deaths with cast data and no
    defensive/external), nodef_n, irpp (raid interrupts per pull over pulls with interrupt data)}.
    """
    by_night: dict[str, list] = defaultdict(list)
    for key, p, vecs in _flat(bosses, pm_by_key):
        by_night[p["night"]].append((p, vecs))
    out = []
    for night in nights_in_order([p for rows in by_night.values() for p, _ in rows]):
        rows = by_night[night]
        avh = alv = 0
        any_av = False
        ir_sum, ir_pulls = 0, 0
        nodef = [x for x in (_nodef_first(p) for p, _ in rows) if x is not None]
        for p, vecs in rows:
            tokens = pull_specs(p)
            irs = [_v(vec, "ir") for vec in vecs.values()]
            irs = [x for x in irs if x is not None]
            if irs:
                ir_sum += sum(irs)
                ir_pulls += 1
            for label, vec in vecs.items():
                h = _v(vec, "avh")
                if h is None or role_of(p, label, tokens) == "tank":
                    continue
                any_av = True
                avh += h
                alv += _v(vec, "alv") or 0
        out.append({"night": night, "pulls": len(rows), "prep": prep_rates([p for p, _ in rows]),
                    "avm": (avh / (alv / 60)) if any_av and alv else None,
                    "nodef": (sum(nodef) / len(nodef)) if nodef else None, "nodef_n": len(nodef),
                    "irpp": (ir_sum / ir_pulls) if ir_pulls else None})
    return out


# --------------------------------------------------------------------------
# Named-only "Raid lead" section
# --------------------------------------------------------------------------

def _item_text(item) -> str:
    metric, value, base, bkind = item[0], item[1], item[2], item[3]
    out = f"{METRIC_LABEL.get(metric, metric)} {_num(value)}"
    if base is not None:
        out += f" vs {_num(base)} ({BKIND_WORD.get(bkind, bkind or 'reference')})"
    return out


def _latest_items(sev_by_night: dict, night_order: list[str]) -> tuple[str | None, list]:
    for night in reversed(night_order):
        if night in sev_by_night:
            return night, sev_by_night[night]
    return None, []


def _r1_rows(players_block: dict) -> list[tuple[tuple, str]]:
    """[(sort key, row html)] for R1, sorted by level (watch first) then score (highest first) then name. A raider's
    level / score = their worst item on their latest night (highest-scoring Watch item, else the first item)."""
    roster, sev = players_block.get("roster") or {}, players_block.get("sev") or {}
    order = [n[0] for n in players_block.get("nights") or []]
    out = []
    for label, r in roster.items():
        night, items = _latest_items(sev.get(label) or {}, order)
        if night is None:
            continue
        watch = sorted((it for it in items if it[4] == "watch"), key=lambda it: -float(it[5] or 0))
        top = watch[:WATCH_SHOWN] if watch else items[:1]
        level = top[0][4] if top else "note"
        score = max((float(it[5] or 0) for it in top), default=0.0)
        key = (LEVEL_ORDER.get(level, 9), -score, label.lower())
        what = "; ".join(esc(_item_text(it)) for it in top) if watch else "Nothing to watch"
        out.append((key, f"<tr data-level='{level}' data-score='{score:.2f}'>"
                         f"<td>{player_cell(label, r.get('cl', ''))}</td><td>{esc(ROLE_LABEL.get(r.get('role', ''), r.get('role', '')))}</td>"
                         f"<td data-sort='{key[0]}'><span class='tag {LEVEL_TAG.get(level, 'note')}'>{LEVEL_WORD.get(level, level)}</span></td>"
                         f"<td class='right' data-sort='{score:.2f}'>{score:.2f}</td><td>{what}</td><td>{esc(night)}</td></tr>"))
    out.sort(key=lambda t: t[0])
    return out


def _r1(players_block: dict) -> str:
    rows = [r for _, r in _r1_rows(players_block)]
    if not rows:
        return "<h3>Who needs help with what</h3>" + empty_state("raiders", "no severity data in this selection")
    return ("<h3>Who needs help with what</h3>"
            + section_note("One row per raider: their top Watch items on their latest night, with the number and the "
                           "baseline it was compared with. Sorted by level, then by how far past the tolerance it was.")
            + table([("Player", "str"), ("Role", "str"), ("Level", "num"), ("Score", "num"), ("Top items", "str"),
                     ("Night", "str")], rows, caption="Raiders by most urgent item", limit=15))


def _r2(pulls: list[dict]) -> str:
    seen, miss = Counter(), defaultdict(Counter)
    cls: dict[str, str] = {}
    for p in pulls:
        for label, c in (p.get("consumables") or {}).items():
            if not c:
                continue
            seen[label] += 1
            cls[label] = (p.get("participants") or {}).get(label, cls.get(label, ""))
            for cat in ("flask", "food", "rune"):
                if cat in c and not c[cat]:
                    miss[label][cat] += 1
            if any(cat in c and not c[cat] for cat in ("flask", "food", "rune")):
                miss[label]["any"] += 1
    head = "<h3>Preparation misses</h3>"
    if not seen:
        return head + empty_state("consumable data", "WCL returned no buff tables for these pulls")
    rows = []
    for label in sorted((lab for lab in seen if miss[lab]["any"]), key=lambda lab: (-miss[lab]["any"] / seen[lab], lab.lower())):
        m, n = miss[label], seen[label]
        rows.append(f"<tr><td>{player_cell(label, cls.get(label, ''))}</td><td class='right'>{n}</td>"
                    f"<td class='right'>{m['flask']}</td><td class='right'>{m['food']}</td><td class='right'>{m['rune']}</td>"
                    f"<td class='right' data-sort='{m['any'] / n:.3f}'>{m['any'] / n * 100:.0f}%</td></tr>")
    if not rows:
        return head + section_note("Everyone had flask, food and rune on every checked pull.")
    return head + table([("Player", "str"), ("Pulls checked", "num"), ("No flask", "num"), ("No food", "num"),
                         ("No rune", "num"), ("Missing something", "num")], rows, caption="Pulls started without consumables",
                        limit=15)


def _r3(bosses: dict, flat: list, series: list[dict], avoidable_cfg: dict) -> str:
    head = "<h3>Avoidable damage</h3>"
    if not any(s["avm"] is not None for s in series):
        return head + empty_state("avoidable data", "no boss in this selection has an avoidable list (config/avoidable.json)")
    trend = "".join(f"<tr><td>{esc(s['night'])}</td><td class='right'>{s['pulls']}</td>"
                    f"<td class='right' data-sort='{s['avm'] if s['avm'] is not None else -1:.3f}'>{_num(s['avm'])}</td></tr>"
                    for s in series)
    ignored = ignore_set(avoidable_cfg)
    hits: Counter = Counter()
    who: dict[tuple, Counter] = defaultdict(Counter)
    for key, p, _vecs in flat:
        avoid = avoidable_set(avoidable_cfg, key[0]) - ignored
        if not avoid:
            continue
        cutoff = p.get("wipe_cutoff_s")
        tokens = pull_specs(p)
        for row in p.get("damage_taken") or []:
            if normalize(row["ability"]) not in avoid or role_of(p, row["player"], tokens) == "tank":
                continue
            n = sum(1 for t in (row.get("times") or []) if cutoff is None or t <= cutoff)
            if n:
                hits[(row["ability"], key[0])] += n
                who[(row["ability"], key[0])][row["player"]] += n
    top = ""
    for (ab, boss), n in hits.most_common(TOP_ABILITIES):
        names = ", ".join(f"{esc(pl)} ({c})" for pl, c in who[(ab, boss)].most_common(5))
        top += f"<tr><td>{esc(ab)}</td><td>{esc(boss)}</td><td class='right'>{n}</td><td>{names}</td></tr>"
    return (head + section_note("Non-tank players only; hits after the wipe started are not counted.")
            + table([("Night", "str"), ("Pulls", "num"), ("Avoidable hits / min alive", "num")], trend,
                    caption="Avoidable hits per minute alive, per night")
            + (table([("Ability", "str"), ("Boss", "str"), ("Hits", "num"), ("Who (top 5)", "str")], top,
                     caption=f"Top {TOP_ABILITIES} avoidable abilities") if top else ""))


def _r5(pulls: list[dict], series: list[dict]) -> str:
    head = "<h3>First deaths without a defensive</h3>"
    by_night: dict[str, Counter] = defaultdict(Counter)
    for p in pulls:
        if _nodef_first(p):
            by_night[p["night"]][p["deaths"][0]["player"]] += 1
    rows = ""
    for s in series:
        if not s["nodef_n"]:
            continue
        names = ", ".join(f"{esc(pl)} ({c})" if c > 1 else esc(pl) for pl, c in by_night[s["night"]].most_common()) or "-"
        rows += (f"<tr><td>{esc(s['night'])}</td><td class='right'>{s['nodef_n']}</td>"
                 f"<td class='right'>{sum(by_night[s['night']].values())}</td>"
                 f"<td class='right' data-sort='{s['nodef']:.3f}'>{s['nodef'] * 100:.0f}%</td><td>{names}</td></tr>")
    if not rows:
        return head + empty_state("first deaths with cast data", "no pull in this selection has defensive-cast data for its first death")
    return head + table([("Night", "str"), ("First deaths with cast data", "num"), ("No defensive", "num"), ("Share", "num"),
                         ("Who", "str")], rows, caption="First deaths with no defensive or external in the death window")


def _r7(flat: list, roster: dict) -> str:
    head = "<h3>Interrupts</h3>"
    total, pulls_with = Counter(), Counter()
    for _key, _p, vecs in flat:
        for label, vec in vecs.items():
            ir = _v(vec, "ir")
            if ir is not None:
                total[label] += ir
                pulls_with[label] += 1
    if not pulls_with:
        return head + empty_state("interrupt data", "WCL returned no Interrupts tables for these pulls")
    rows = []
    for label in sorted(pulls_with, key=lambda lab: (-total[lab] / pulls_with[lab], lab.lower())):
        r = roster.get(label) or {}
        rate = total[label] / pulls_with[label]
        rows.append(f"<tr><td>{player_cell(label, r.get('cl', ''))}</td><td>{esc(ROLE_LABEL.get(r.get('role', ''), r.get('role', '')))}</td>"
                    f"<td class='right'>{pulls_with[label]}</td><td class='right'>{total[label]}</td>"
                    f"<td class='right' data-sort='{rate:.3f}'>{rate:.1f}</td></tr>")
    return (head + section_note("Interrupts land only when someone is assigned to kick, so read this against your "
                                "assignments. WCL lists only spells that were interrupted, so there is no 'missed' count.")
            + table([("Player", "str"), ("Role", "str"), ("Pulls", "num"), ("Interrupts", "num"), ("Per pull", "num")],
                    rows, caption="Interrupts per pull per player", limit=15))


TANK_METRICS = [("am", "Active mitigation % of hits"), ("amw", "Active mitigation % of damage"),
                ("mit", "Mitigated %"), ("dtps", "Damage taken / s alive (k)")]


def _r8(flat: list) -> str:
    head = "<h3>Tanks side by side</h3>"
    per: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))   # night -> tank -> [vec]
    tanks: Counter = Counter()
    nights: list[str] = []
    for _key, p, vecs in flat:
        tokens = pull_specs(p)
        for label, vec in vecs.items():
            if role_of(p, label, tokens) != "tank":
                continue
            tanks[label] += 1
            per[p["night"]][label].append(vec)
            if p["night"] not in nights:
                nights.append(p["night"])
    if not tanks:
        return head + empty_state("tanks", "no tank spec was played in this selection")
    cols = sorted(tanks, key=str.lower)

    def value(vs: list, metric: str):
        if metric == "dtps":   # sum damage taken / sum seconds alive -> k/s
            dtk = [(_v(v, "dtk"), _v(v, "alv")) for v in vs]
            dtk = [(d, a) for d, a in dtk if d is not None and a]
            return (sum(d for d, _ in dtk) / sum(a for _, a in dtk)) if dtk else None
        xs = [_v(v, metric) for v in vs]
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    rows = ""
    for night in nights:
        for metric, label in TANK_METRICS:
            cells = ""
            for t in cols:
                vs = per[night].get(t)
                x = value(vs, metric) if vs else None
                cells += f"<td class='right' data-sort='{x if x is not None else -1:.3f}'>{_num(x)}</td>"
            rows += f"<tr><td>{esc(night)}</td><td>{esc(label)}</td>{cells}</tr>"
    return (head + section_note("Mean of the per-pull values for each night (damage taken per second: total damage taken "
                                "over total seconds alive). Hits after the wipe started are not counted; '-' = not on that "
                                "night or no aura data.")
            + table([("Night", "str"), ("Metric", "str")] + [(t, "num") for t in cols], rows,
                    caption="Tank metrics per night"))


def _r9(players_block: dict) -> str:
    head = "<h3>Gear readiness</h3>"
    gear, roster = players_block.get("gear") or {}, players_block.get("roster") or {}
    ilvls = [g["ilvl"] for g in gear.values() if g.get("ilvl") is not None]
    if not ilvls:
        return head + empty_state("gear data", "WCL returned no gear for these pulls")
    tiles = kpis([("Lowest item level", str(min(ilvls))), ("Median item level", _num(_median(ilvls))),
                  ("Highest item level", str(max(ilvls))), ("Players with gear gaps", str(sum(1 for g in gear.values() if g.get("gaps"))))])
    rows = []
    for label in sorted((lab for lab, g in gear.items() if g.get("gaps")), key=lambda lab: (-len(gear[lab]["gaps"]), lab.lower())):
        g = gear[label]
        rows.append(f"<tr><td>{player_cell(label, (roster.get(label) or {}).get('cl', ''))}</td>"
                    f"<td class='right'>{_num(g.get('ilvl'))}</td><td class='right'>{len(g['gaps'])}</td>"
                    f"<td>{esc('; '.join(g['gaps']))}</td></tr>")
    body = (table([("Player", "str"), ("Item level", "num"), ("Gaps", "num"), ("What", "str")], rows,
                  caption="Players with gear gaps on their latest pull", limit=15)
            if rows else section_note("Nobody has a missing enchant, empty socket or low slot on their latest pull."))
    return head + tiles + body


def rollups_named(bosses: dict, ordered: list, players_block: dict, pm_by_key: dict | None = None,
                  avoidable_cfg: dict | None = None) -> str:
    """The named-only 'Raid lead' section (h2 + h3 subsections). Only call it for `--callouts named` builds."""
    keys = [key for key, _ in ordered] if ordered else list(bosses)
    bosses = {k: bosses[k] for k in keys if k in bosses}
    flat = _flat(bosses, pm_by_key)
    pulls = [p for _k, p, _v in flat]
    series = night_series(bosses, pm_by_key)
    roster = players_block.get("roster") or {}
    return ("<h2 id='raid_lead'>Raid lead</h2>"
            + section_note("Named build only: this section is not rendered in the public dashboard.")
            + _r1(players_block) + _r2(pulls) + _r3(bosses, flat, series, avoidable_cfg or {})
            + _r5(pulls, series) + _r7(flat, roster) + _r8(flat) + _r9(players_block))


__all__ = ["night_series", "prep_rates", "nights_in_order", "rollups_named", "PM_COLS"]
