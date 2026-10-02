"""Gear checks: per-player item level and gear gaps (missing enchants, empty sockets, low slots).

Pure module (stdlib + json + path.CONFIG_DIR). Input rows follow Contract C of the Phase 1 plan:
``pull["gear"] = {label: [[slot, item_ilvl, enchant_id_or_0, n_gems, item_id], ...]}``.

Which slots must carry an enchant / a gem is decided by the roster majority (Midnight's
enchantable and socketed slots differ from older expansions): a slot is required when strictly
more than ``majority`` of the roster's non-empty items in that slot carry an enchant (or at least
one gem). Explicit slot lists in ``config/gear_checks.json`` override ``"auto"``.
"""
import copy
import json
import os

from path import CONFIG_DIR

GEAR_CHECKS_FILE = os.path.join(CONFIG_DIR, "gear_checks.json")

SLOT_NAMES = {
    "0": "head", "1": "neck", "2": "shoulder", "3": "shirt", "4": "chest", "5": "waist",
    "6": "legs", "7": "feet", "8": "wrist", "9": "hands", "10": "ring 1", "11": "ring 2",
    "12": "trinket 1", "13": "trinket 2", "14": "back", "15": "main hand", "16": "off hand",
    "17": "tabard",
}

DEFAULTS = {
    "enchantable": "auto",
    "socket_slots": "auto",
    "majority": 0.5,
    "skip_slots": [3, 17],
    "low_slot_gap": 15,
    "slot_names": SLOT_NAMES,
}

# Row indices (Contract C).
SLOT, ILVL, ENCHANT, GEMS, ITEM = range(5)


def load_gear_checks(file: str | None = None) -> dict:
    """gear_checks.json merged over DEFAULTS; a missing or unreadable file gives the defaults."""
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(file or GEAR_CHECKS_FILE, encoding="utf-8") as fh:
            user = json.load(fh)
    except (OSError, ValueError):
        return cfg
    if isinstance(user, dict):
        for k, v in user.items():
            if k.startswith("_"):
                continue
            if k == "slot_names" and isinstance(v, dict):
                cfg["slot_names"] = {**cfg["slot_names"], **{str(s): n for s, n in v.items()}}
            else:
                cfg[k] = v
    return cfg


def _cfg(cfg: dict | None) -> dict:
    return {**DEFAULTS, **(cfg or {})}


def slot_name(slot: int, cfg: dict | None = None) -> str:
    """Human name of an inventory slot ('head', 'ring 2', ...); 'slot N' when unknown."""
    names = _cfg(cfg).get("slot_names") or SLOT_NAMES
    return names.get(str(slot)) or SLOT_NAMES.get(str(slot)) or f"slot {slot}"


def _items(rows, skip: set) -> list:
    """Rows that hold a real item: item_id and ilvl non-zero, slot not skipped."""
    out = []
    for r in rows or []:
        if len(r) < 5 or not r[ITEM] or not r[ILVL] or r[SLOT] in skip:
            continue
        out.append(r)
    return out


def roster_rules(gear_by_label: dict, cfg: dict | None = None) -> dict:
    """{"enchant_slots": set, "gem_slots": set} for one roster.

    gear_by_label: {label: rows}. "auto" lists use the strict-majority rule over the non-empty
    items in each slot; an explicit list in cfg is used as is.
    """
    c = _cfg(cfg)
    skip = set(c.get("skip_slots") or [])
    majority = float(c.get("majority", 0.5))
    total, ench, gems = {}, {}, {}
    for rows in (gear_by_label or {}).values():
        for r in _items(rows, skip):
            s = r[SLOT]
            total[s] = total.get(s, 0) + 1
            if r[ENCHANT]:
                ench[s] = ench.get(s, 0) + 1
            if r[GEMS]:
                gems[s] = gems.get(s, 0) + 1

    def pick(key, counts):
        explicit = c.get(key)
        if isinstance(explicit, list):
            return {int(s) for s in explicit}
        return {s for s, n in total.items() if counts.get(s, 0) / n > majority}

    return {"enchant_slots": pick("enchantable", ench), "gem_slots": pick("socket_slots", gems)}


def gear_report(rows, rules: dict, cfg: dict | None = None) -> dict:
    """{"ilvl": int|None, "gaps": [str], "n_gaps": int} for one player's rows.

    ilvl = rounded mean item level over real, non-skipped items (None when there are none).
    Gaps, in slot order: "<slot>: no enchant" (required enchant slot without one),
    "<slot>: empty socket" (required gem slot with 0 gems),
    "<slot> N ilvl below your average" (item ilvl <= mean - low_slot_gap).
    """
    c = _cfg(cfg)
    items = sorted(_items(rows, set(c.get("skip_slots") or [])), key=lambda r: r[SLOT])
    if not items:
        return {"ilvl": None, "gaps": [], "n_gaps": 0}
    mean = sum(r[ILVL] for r in items) / len(items)
    low = c.get("low_slot_gap", 15)
    ench_req = (rules or {}).get("enchant_slots") or set()
    gem_req = (rules or {}).get("gem_slots") or set()
    gaps = []
    for r in items:
        name = slot_name(r[SLOT], c)
        if r[SLOT] in ench_req and not r[ENCHANT]:
            gaps.append(f"{name}: no enchant")
        if r[SLOT] in gem_req and not r[GEMS]:
            gaps.append(f"{name}: empty socket")
        if low is not None and r[ILVL] <= mean - low:
            gaps.append(f"{name} {round(mean - r[ILVL])} ilvl below your average")
    return {"ilvl": round(mean), "gaps": gaps, "n_gaps": len(gaps)}


def latest_gear(pulls_by_label) -> dict:
    """{label: rows} from each player's most recent pull that carries gear for them.

    Accepts {label: [pull, ...]} or a plain list of pulls (every label in each pull's "gear").
    "Most recent" = highest absolute_start_ms; pulls without it keep their list order.
    """
    if isinstance(pulls_by_label, dict):
        items = [(label, pulls) for label, pulls in pulls_by_label.items()]
    else:
        pulls = list(pulls_by_label or [])
        labels = {lb for p in pulls for lb in (p.get("gear") or {})}
        items = [(label, pulls) for label in sorted(labels)]
    out = {}
    for label, pulls in items:
        best, best_key = None, None
        for i, p in enumerate(pulls or []):
            rows = (p.get("gear") or {}).get(label)
            if not rows:
                continue
            key = (p.get("absolute_start_ms") or 0, i)
            if best_key is None or key >= best_key:
                best, best_key = rows, key
        if best is not None:
            out[label] = best
    return out
