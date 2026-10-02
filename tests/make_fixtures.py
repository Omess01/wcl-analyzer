"""
Populate tests/fixtures/ from WCL (needs network + .env once).

    venv/bin/python tests/make_fixtures.py --clean [REPORT_CODE]   # real re-record (default 3w1jJ8BZ2m9kMrYG)
    venv/bin/python tests/make_fixtures.py [REPORT_CODE]           # record, reusing cached responses
    venv/bin/python tests/make_fixtures.py --slim                  # re-slim existing fixtures only, no network

Re-record procedure: always use --clean. The recorder points cache.CACHE_DIR at
tests/fixtures/cache, so without wiping it first the already-slimmed bundles are
cache hits (gear/talents never come back) and entries under old cache keys stay
behind as orphans. --clean is ignored together with --slim.

Size budget: the fixture cache must stay <= 7.5 MB; the recorder prints the final
size and exits with an error above it.

Runs the real collector for ONE small report with the cache pointed at
tests/fixtures/cache, so exactly the responses that report needs end up
there, then stores the report's metadata in tests/fixtures/report.json.
The tests replay from these files with the network switched off.
"""

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cache                      # noqa: E402
import collect_data               # noqa: E402
from dash.common import spec_role  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
DEFAULT_CODE = "3w1jJ8BZ2m9kMrYG"   # a 4-pull Normal night: small, but has deaths, phases, casts
SIZE_BUDGET = 7.5e6                  # bytes; fixture cache must stay at or below this


def clean(cache_dir: str) -> None:
    """Remove everything inside cache_dir (the directory itself is kept)."""
    if not os.path.isdir(cache_dir):
        return
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def dir_size(path: str) -> int:
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs)


def check_budget(cache_dir: str) -> None:
    size = dir_size(cache_dir)
    print(f"fixture cache size: {size / 1e6:.2f} MB (budget {SIZE_BUDGET / 1e6:.1f} MB)")
    if size > SIZE_BUDGET:
        raise SystemExit(f"fixture cache {size / 1e6:.2f} MB exceeds the {SIZE_BUDGET / 1e6:.1f} MB budget; "
                         "slim more aggressively or pick a smaller report")


def main(code: str = DEFAULT_CODE, do_clean: bool = False) -> None:
    cache_dir = os.path.join(FIXTURES, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    if do_clean:
        clean(cache_dir)
    cache.CACHE_DIR = cache_dir
    collect_data.META_FILE = os.path.join(cache_dir, "report_meta.json")

    reports = collect_data.fetch_reports_by_code([code])
    if not reports:
        raise SystemExit(f"report {code} not found")
    with open(os.path.join(FIXTURES, "report.json"), "w", encoding="utf-8") as f:
        json.dump(reports[0], f, indent=1)

    bosses = collect_data.collect("2000-01-01", "2100-01-01", difficulties=["lfr", "normal", "heroic", "mythic"], reports=[code])
    total = sum(len(p) for p in bosses.values())
    slim(cache_dir)
    size = sum(os.path.getsize(os.path.join(cache_dir, f)) for f in os.listdir(cache_dir))
    print(f"fixtures: {len(bosses)} bosses, {total} pulls, {len(os.listdir(cache_dir))} cache files, {size / 1e6:.1f} MB")
    check_budget(cache_dir)


# WCL's damage/healing tables carry every player's gear, talents and per-ability breakdown.
# The collector and per-player analysis read name/id/type/icon/total/activeTime/itemLevel/overheal,
# gear, targets and the top abilities; the rest is dropped and abilities are cut to the top
# _TOP_ABILITIES by total. Combatant-info events carry full stat blocks, gear and talent trees:
# every player keeps _CINFO_KEEP; up to _CINFO_FULL_PLAYERS players per fight (one per role where
# possible, role from the table icon) additionally keep _CINFO_FULL_EXTRA.
# Pull-start entries ({"damage": [...], "casts": [...]}, who pulled) are reduced to the same
# event fields: the detection reads timestamp / type / sourceID / targetID / abilityGameID only.
_TABLE_DROP = {"talents", "damageAbilities", "given", "taken", "pets"}
_TOP_ABILITIES = 8
_CINFO_KEEP = {"timestamp", "type", "fight", "sourceID", "auras", "specID"}
_CINFO_STATS = {"strength", "agility", "stamina", "intellect", "dodge", "parry", "block", "armor",
                "critMelee", "critRanged", "critSpell", "hasteMelee", "hasteRanged", "hasteSpell",
                "speed", "leech", "avoidance", "mastery", "versatilityDamageDone",
                "versatilityHealingDone", "versatilityDamageReduction"}
_CINFO_FULL_EXTRA = {"gear", "talentTree"} | _CINFO_STATS
_CINFO_FULL_PLAYERS = 3
_EVENT_KEEP = {"timestamp", "type", "sourceID", "targetID", "abilityGameID", "fight", "tick", "amount", "absorbed",
               "overkill", "unmitigatedAmount", "buffs", "mitigated", "hitType", "blocked"}


def _table_roles(data: dict) -> dict:
    """actor id -> 'tank' | 'healer' | 'dps' from the damage/healing table icons ("Priest-Holy")."""
    roles: dict = {}
    for key in ("damage", "healing"):
        table = data.get(key) or {}
        inner = table.get("data", table)
        for e in inner.get("entries") or []:
            icon = e.get("icon") or ""
            head, _, spec = icon.partition("-")
            if spec and head == e.get("type") and e.get("id") is not None:
                roles.setdefault(e["id"], spec_role(spec))
    return roles


def _full_cinfo_ids(data: dict) -> set:
    """(fight, sourceID) pairs, up to _CINFO_FULL_PLAYERS per fight: one per role first, then cinfo order."""
    roles = _table_roles(data)
    by_fight: dict = {}
    for ev in data.get("cinfo") or []:
        sid = ev.get("sourceID")
        if sid is not None and sid not in by_fight.setdefault(ev.get("fight"), []):
            by_fight[ev.get("fight")].append(sid)
    keep: set = set()
    for fight, sids in by_fight.items():
        chosen: list = []
        for role in ("tank", "healer", "dps"):
            for sid in sids:
                if roles.get(sid) == role and sid not in chosen:
                    chosen.append(sid)
                    break
        for sid in sids:
            if len(chosen) >= _CINFO_FULL_PLAYERS:
                break
            if sid not in chosen:
                chosen.append(sid)
        keep.update((fight, sid) for sid in chosen[:_CINFO_FULL_PLAYERS])
    return keep


def slim(cache_dir: str) -> None:
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        if not name.endswith(".json") or name == "report_meta.json":
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # damage-taken event pages: keep only the keys the collector reads
        events = (((data.get("reportData") or {}).get("report") or {}).get("events") or {}) if isinstance(data, dict) else {}
        if events.get("data"):
            events["data"] = [{k: v for k, v in ev.items() if k in _EVENT_KEEP} for ev in events["data"]]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            continue
        if isinstance(data, dict) and set(data) == {"damage", "casts"}:   # pull-start events (puller entries)
            for key in ("damage", "casts"):
                data[key] = [{k: v for k, v in ev.items() if k in _EVENT_KEEP} for ev in data.get(key) or []]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            continue
        if not (isinstance(data, dict) and "cinfo" in data):
            continue   # not a fight bundle
        for key in ("damage", "healing"):
            table = data.get(key) or {}
            inner = table.get("data", table)
            for e in inner.get("entries") or []:
                for k in list(e):
                    if k in _TABLE_DROP:
                        e[k] = [] if isinstance(e[k], list) else None
                if isinstance(e.get("abilities"), list):
                    e["abilities"] = sorted(e["abilities"], key=lambda a: -(a.get("total") or 0))[:_TOP_ABILITIES]
        full = _full_cinfo_ids(data)
        data["cinfo"] = [{k: v for k, v in ev.items()
                          if k in _CINFO_KEEP or ((ev.get("fight"), ev.get("sourceID")) in full and k in _CINFO_FULL_EXTRA)}
                         for ev in data.get("cinfo") or []]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--slim" in args:
        cache_dir = os.path.join(FIXTURES, "cache")
        slim(cache_dir)          # never --clean here: that would delete the fixtures it is meant to slim
        check_budget(cache_dir)
    else:
        do_clean = "--clean" in args
        rest = [a for a in args if a != "--clean"]
        main(rest[0] if rest else DEFAULT_CODE, do_clean=do_clean)
