"""
Populate tests/fixtures/ from WCL (needs network + .env once).

    python tests/make_fixtures.py [REPORT_CODE]

Runs the real collector for ONE small report with the cache pointed at
tests/fixtures/cache, so exactly the responses that report needs end up
there, then stores the report's metadata in tests/fixtures/report.json.
The tests replay from these files with the network switched off.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cache                      # noqa: E402
import collect_data               # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
DEFAULT_CODE = "3w1jJ8BZ2m9kMrYG"   # a 4-pull Normal night: small, but has deaths, phases, casts


def main(code: str = DEFAULT_CODE) -> None:
    cache_dir = os.path.join(FIXTURES, "cache")
    os.makedirs(cache_dir, exist_ok=True)
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


# WCL's damage/healing tables carry every player's gear, talents and per-ability breakdown;
# the collector only reads name/id/type/icon/total/activeTime/itemLevel. Combatant-info events
# carry full stat blocks; only sourceID + auras are read. Dropping the rest keeps fixtures small.
_TABLE_DROP = {"gear", "talents", "abilities", "damageAbilities", "targets", "given", "taken", "pets"}
_CINFO_KEEP = {"timestamp", "type", "fight", "sourceID", "auras", "specID"}
_EVENT_KEEP = {"timestamp", "type", "sourceID", "targetID", "abilityGameID", "fight", "tick", "amount", "absorbed",
               "overkill", "unmitigatedAmount"}


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
        if not (isinstance(data, dict) and "cinfo" in data):
            continue   # not a fight bundle
        for key in ("damage", "healing"):
            table = data.get(key) or {}
            inner = table.get("data", table)
            for e in inner.get("entries") or []:
                for k in list(e):
                    if k in _TABLE_DROP:
                        e[k] = [] if isinstance(e[k], list) else None
        data["cinfo"] = [{k: v for k, v in ev.items() if k in _CINFO_KEEP} for ev in data.get("cinfo") or []]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--slim":
        slim(os.path.join(FIXTURES, "cache"))
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CODE)
