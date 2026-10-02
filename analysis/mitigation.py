"""
Tank active mitigation and the per-player event digest (Contract C of the Phase 1 plan).

`digest_events()` turns the raw damage-taken events of one pull into a few integers per player so the pull dict can
drop the events; `dash/payload.py` assembles the metric vector from the digest (analysis/player_metrics.py).

Config: config/tank_mitigation.json, `{"<spec label>": {"am": [{"id", "name"}], "major": [...]}}` where the label is
the specs.py spec token ("Vengeance", "Blood", ...) or "<Spec> <Class>" when the token is shared by two classes
("Protection Paladin", "Protection Warrior"). `am` = active-mitigation auras checked on every connected hit;
`major` = major cooldowns (unused in Phase 1, validated at build time).

Imported from collect_data: must not import anything from dash/ or collect_data (import cycle). `specs` is fine.
"""

import json
import os
from collections import Counter

import specs
from path import CONFIG_DIR

TANK_MITIGATION_FILE = os.path.join(CONFIG_DIR, "tank_mitigation.json")

# WCL hitType values: 0 miss, 1 hit, 2 crit, 4 blocked hit, 5 blocked crit, 7 dodge, 8 parry, 10 immune ...
CONNECTED_HIT_TYPES = frozenset({1, 2, 4, 5})
DODGE_PARRY_MISS_TYPES = frozenset({0, 7, 8})
# `am` / `amw` are blank when more than this share of a tank's connected hits lacks the `buffs` key
AM_BUFFS_MISSING_MAX = 0.30

# {spec label: Counter({buff id: hits it was up on})} over every tank's connected hits in the current build;
# cleared by collect() and written to data/tank_buffs_seen.json by build_dashboard.
TANK_BUFFS_SEEN: dict[str, Counter] = {}

_cfg_cache: dict | None = None
_noted_missing: set[str] = set()


def load_tank_mitigation(force: bool = False) -> dict:
    """{spec label: {"am": {ids}, "major": {ids}, "names": {id: name}}} from tank_mitigation.json ({} when absent / invalid)."""
    global _cfg_cache
    if _cfg_cache is not None and not force:
        return _cfg_cache
    raw = None
    try:
        with open(TANK_MITIGATION_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = None
    out: dict[str, dict] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            entry = {"am": set(), "major": set(), "names": {}}
            for kind in ("am", "major"):
                for item in val.get(kind) or []:
                    sid = item.get("id") if isinstance(item, dict) else item
                    if isinstance(sid, bool) or not isinstance(sid, int):
                        continue
                    entry[kind].add(sid)
                    if isinstance(item, dict) and item.get("name"):
                        entry["names"][sid] = str(item["name"])
            out[key] = entry
    _cfg_cache = out
    return out


_TANK_TOKEN_CLASSES: dict[str, set[str]] = {}
for _cls, _tok, _role, _simc, _sup in specs.SPECS.values():
    if _role == "tank":
        _TANK_TOKEN_CLASSES.setdefault(_tok, set()).add(_cls)


def spec_label(cls: str | None, spec_token: str) -> str:
    """Config / counter key for a tank spec: the token alone unless two classes share it ("Protection Paladin")."""
    classes = _TANK_TOKEN_CLASSES.get(spec_token)
    if classes and len(classes) > 1 and cls:
        return f"{spec_token} {cls}"
    return spec_token


def _candidate_keys(spec_token: str, cls: str | None) -> list[str]:
    keys = [spec_token]
    if cls:
        spaced = "".join(" " + c if c.isupper() and i else c for i, c in enumerate(cls))  # DeathKnight -> Death Knight
        for c in dict.fromkeys([cls, spaced]):
            keys += [f"{spec_token} {c}", f"{c} {spec_token}", f"{c}-{spec_token}", f"{spec_token}-{c}"]
    return keys


def mitigation_entry(spec_token: str, cls: str | None = None) -> dict | None:
    """The config entry for a tank spec, or None. Without a class, a token shared by two classes resolves to the union."""
    cfg = load_tank_mitigation()
    if not spec_token:
        return None
    for key in _candidate_keys(spec_token, cls):
        if key in cfg:
            return cfg[key]
    if cls is None:
        classes = _TANK_TOKEN_CLASSES.get(spec_token) or set()
        merged = {"am": set(), "major": set(), "names": {}}
        found = False
        for c in sorted(classes):
            for key in _candidate_keys(spec_token, c):
                if key in cfg:
                    found = True
                    merged["am"] |= cfg[key]["am"]
                    merged["major"] |= cfg[key]["major"]
                    merged["names"].update(cfg[key]["names"])
                    break
        if found:
            return merged
    return None


def am_ids_for(spec_token: str, cls: str | None = None) -> set[int] | None:
    """Active-mitigation aura ids for a tank spec token (class disambiguates "Protection"); None when not configured."""
    entry = mitigation_entry(spec_token, cls)
    return set(entry["am"]) if entry else None


def parse_buffs(buffs) -> set[int]:
    """WCL's dot-separated buff string ("203819.187827.") -> {203819, 187827}."""
    if not buffs:
        return set()
    out = set()
    for part in str(buffs).split("."):
        if part.isdigit():
            out.add(int(part))
    return out


def _tank_spec(spec_ref) -> tuple[str, str] | None:
    """(class, spec token) for a specID (int) or spec token (str) when it is a tank spec, else None."""
    if isinstance(spec_ref, str):
        if specs.role_of_token(spec_ref) != "tank":
            return None
        classes = _TANK_TOKEN_CLASSES.get(spec_ref) or set()
        return (next(iter(classes)) if len(classes) == 1 else None, spec_ref)
    known = specs.spec_of(spec_ref)
    if not known or known[2] != "tank":
        return None
    return known[0], known[1]


def _is_connected(e: dict) -> bool:
    ht = e.get("hit_type")
    if ht is None:   # no hitType (older cache): a connected hit is one that did something
        return not e.get("avoided")
    return ht in CONNECTED_HIT_TYPES


def digest_events(events: list[dict], participants: dict, spec_ids: dict, cutoff: float | None) -> dict[str, dict]:
    """
    {label: {dtk, hits, hits_buffs, dodge_parry_miss[, am_up, amw_num, amw_den, mit_num, mit_den]}} over the pull's
    damage events with `seconds <= cutoff` (every event when cutoff is None), one entry per participant.

    - enemy source = `source` is not a participant label; self-inflicted events are skipped (like aggregate_damage).
    - dtk: sum of `amount` (includes absorbed) of non-self enemy events.
    - hits: connected (hitType 1/2/4/5), non-tick, non-self enemy hits; hits_buffs: those carrying a `buffs` key.
    - tanks only (spec from `spec_ids`: specID int or spec token str): am_up = hits with an AM aura of the spec in
      `buffs`; amw_num/amw_den = the same weighted by unmitigated amount; mit_num/mit_den = (mitigated + absorbed) /
      unmitigated over every non-self enemy event (ticks included) with unmitigated > 0. A tank whose spec is not in
      tank_mitigation.json gets the mit_* keys but no am_* keys (one console note per spec).
    - also feeds TANK_BUFFS_SEEN with every buff id seen on a tank's connected hits.
    """
    spec_ids = spec_ids or {}
    out: dict[str, dict] = {}
    tanks: dict[str, tuple[str, set[int] | None]] = {}
    for label in participants:
        out[label] = {"dtk": 0, "hits": 0, "hits_buffs": 0, "dodge_parry_miss": 0}
        tank = _tank_spec(spec_ids.get(label))
        if tank:
            cls, token = tank
            label_key = spec_label(cls, token)
            ids = am_ids_for(token, cls)
            out[label].update({"mit_num": 0, "mit_den": 0})
            if ids is None:
                if label_key not in _noted_missing:
                    _noted_missing.add(label_key)
                    print(f"  (tank mitigation: no entry for '{label_key}' in tank_mitigation.json - AM uptime stays blank)")
            else:
                out[label].update({"am_up": 0, "amw_num": 0, "amw_den": 0})
            tanks[label] = (label_key, ids)
    for e in events or []:
        label = e.get("player")
        d = out.get(label)
        if d is None or e.get("self"):
            continue
        if e.get("source") in participants:
            continue   # friendly source (not an enemy hit)
        if cutoff is not None and e.get("seconds", 0.0) > cutoff:
            continue
        amount = e.get("amount") or 0
        d["dtk"] += amount
        tank = tanks.get(label)
        if tank is not None:
            unmit = e.get("unmitigated") or 0
            if unmit > 0:
                d["mit_num"] += (e.get("mitigated") or 0) + (e.get("absorbed") or 0)
                d["mit_den"] += unmit
        if e.get("is_tick"):
            continue
        ht = e.get("hit_type")
        if ht in DODGE_PARRY_MISS_TYPES:
            d["dodge_parry_miss"] += 1
        if not _is_connected(e):
            continue
        d["hits"] += 1
        buffs = e.get("buffs")
        if buffs is None:
            continue
        d["hits_buffs"] += 1
        if tank is None:
            continue
        label_key, ids = tank
        up = parse_buffs(buffs)
        if up:
            TANK_BUFFS_SEEN.setdefault(label_key, Counter()).update(up)
        if ids is None:
            continue
        weight = e.get("unmitigated") or amount
        d["amw_den"] += weight
        if up & ids:
            d["am_up"] += 1
            d["amw_num"] += weight
    return out
