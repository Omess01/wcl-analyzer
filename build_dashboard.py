"""
Builds a single HTML dashboard with one tab per boss plus Home, Raid, Players
and Mythic+ tabs. Rendering lives in the `dash` package; boss tabs are
rendered in the browser from a compressed per-boss payload (dash/static/dash.js).

Usage examples:
    python build_dashboard.py 2026-09-01 2026-09-21
    python build_dashboard.py 2026-09-01 2026-09-21 --boss "Ula'tek"
    python build_dashboard.py 2026-09-01 2026-09-21 --zone Manaforge --progression-only
    python build_dashboard.py 2026-09-01 2026-09-21 --player Somedude
    python build_dashboard.py 2026-09-01 2026-09-21 --difficulty heroic -o out.html
"""

import argparse
import json
import os
import sys
from collections import Counter

try:
    import requests, dotenv, plotly  # noqa: F401,E401  - fail early with a useful message
except ImportError as exc:
    sys.exit(
        f"Missing dependency: {exc.name}. The virtual environment is probably not active.\n"
        "  fish:      source venv/bin/activate.fish\n"
        "  bash/zsh:  source venv/bin/activate\n"
        "  or run:    venv/bin/python build_dashboard.py ...\n"
        "  (first time: python -m venv venv && pip install -r requirements.txt)"
    )

from collect_data import collect, default_difficulties, HERE
from dash.page import build_html
from dash.mplus_tab import update_mplus_if_stale


def write_abilities_seen(bosses: dict) -> str:
    """Every ability seen per boss with hit counts and casters - the input for avoidable.json."""
    seen: dict[str, dict[str, dict]] = {}
    for (name, diff), pulls in bosses.items():
        boss_seen = seen.setdefault(name, {})
        for p in pulls:
            for d in p["damage_taken"]:
                a = boss_seen.setdefault(d["ability"], {"hits": 0, "sources": Counter()})
                a["hits"] += d["hits"]
                a["sources"].update(d.get("sources", {}))
    out = {}
    for boss, abilities in seen.items():
        out[boss] = {
            ab: {"hits": info["hits"], "sources": [s for s, _ in info["sources"].most_common(3)]}
            for ab, info in sorted(abilities.items(), key=lambda kv: -kv[1]["hits"])
        }
    path = os.path.join(HERE, "abilities_seen.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return path


def validate_config(bosses: dict) -> None:
    """Warn about config that cannot do what it says: typos in avoidable.json, contradictory nights.json entries."""
    from collect_data import normalize, night_overrides, excluded_bosses, NIGHTS_FILE, clean_code
    from dash.common import load_avoidable, AVOIDABLE_FILE
    warnings = []
    seen_by_boss: dict[str, set] = {}
    for (name, _diff), pulls in bosses.items():
        s = seen_by_boss.setdefault(normalize(name), set())
        for p in pulls:
            s.update(normalize(d["ability"]) for d in p["damage_taken"])
    cfg = load_avoidable()
    for boss_key, abilities in cfg.items():
        if boss_key in ("*", "_ignore"):
            continue
        if boss_key not in seen_by_boss:
            if boss_key not in excluded_bosses():
                warnings.append(f"avoidable.json: boss '{boss_key}' has no pulls in this range (spelling?)")
            continue
        for ab in sorted(abilities):
            if ab not in seen_by_boss[boss_key]:
                warnings.append(f"avoidable.json: '{ab}' never hit anyone on '{boss_key}' in this range - check the spelling against abilities_seen.json")
    ov = night_overrides()
    known = {"_comment", "_open_days", "_exclude_bosses", "_include", "_ignore", "_changelog"}
    for key, val in ov.items():
        if key.startswith("_") and key not in known:
            warnings.append(f"{os.path.basename(NIGHTS_FILE)}: unknown key '{key}' is ignored")
        elif not key.startswith("_") and val not in ("main", "open", "skip", "ignore"):
            warnings.append(f"{os.path.basename(NIGHTS_FILE)}: '{key}' -> '{val}' is not main/open/skip")
    both = {clean_code(c) for c in ov.get("_include") or []} & set(ov.get("_ignore") or [])
    if both:
        warnings.append(f"{os.path.basename(NIGHTS_FILE)}: {', '.join(sorted(both))} are in both _include and _ignore (ignore wins)")
    for w in warnings:
        print(f"  ! {w}")
    if warnings:
        print(f"  ({len(warnings)} config warning{'s' if len(warnings) != 1 else ''}; {os.path.basename(AVOIDABLE_FILE)} names are matched ignoring case and punctuation)")


def main():
    ap = argparse.ArgumentParser(description="Build a multi-report raid dashboard from Warcraft Logs.")
    ap.add_argument("start", help="start date YYYY-MM-DD")
    ap.add_argument("end", help="end date YYYY-MM-DD (inclusive)")
    ap.add_argument("--difficulty", nargs="+", default=default_difficulties(),
                    choices=["lfr", "normal", "heroic", "mythic"],
                    help="difficulties to include (default: DIFFICULTIES in .env, else heroic mythic)")
    ap.add_argument("--zone", help="only reports from this raid, e.g. 'Manaforge'")
    ap.add_argument("--boss", help="only this boss, e.g. \"Ula'tek\"")
    ap.add_argument("--player", help="only pulls this player participated in")
    ap.add_argument("--progression-only", action="store_true", help="only pulls up to and including the first kill")
    ap.add_argument("--callouts", choices=["anonymous", "named", "off"], default=None,
                    help="Home page callouts about individuals: anonymous (default), named (private RL build), off")
    ap.add_argument("--nights", choices=["all", "main", "open"], default="all",
                    help="main = only MAIN_RAID_DAYS nights, open = only the others (default all)")
    ap.add_argument("--reports", nargs="+", metavar="CODE",
                    help="build from ONLY these WCL report codes/URLs instead of the guild's reports in the date range")
    ap.add_argument("--add-report", nargs="+", metavar="CODE",
                    help="add these report codes/URLs to nights.json _include (permanently part of the dataset), then build")
    ap.add_argument("-o", "--output", help="output .html path")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache and re-download everything from WCL")
    ap.add_argument("--no-mplus", action="store_true", help="don't refresh Mythic+ data from Raider.IO")
    ap.add_argument("--mplus", action="store_true", help="force a Mythic+ refresh even if the history is fresh")
    ap.add_argument("--uncompressed", action="store_true",
                    help="embed the per-boss data as plain JSON instead of gzip (bigger file; handy for debugging)")
    args = ap.parse_args()
    if args.refresh:
        import cache
        cache.FORCE_REFRESH = True
        print("--refresh: ignoring cache, re-downloading everything")

    if args.add_report:
        from collect_data import add_report_to_includes
        for code in args.add_report:
            add_report_to_includes(code)

    if not args.no_mplus:
        update_mplus_if_stale(force=args.mplus)

    bosses = collect(args.start, args.end, difficulties=args.difficulty, boss=args.boss,
                     zone=args.zone, player=args.player, progression_only=args.progression_only, nights=args.nights,
                     reports=args.reports)
    if not bosses:
        print("No matching boss pulls found.")
        return

    print(f"\nBosses found: {len(bosses)}")
    for (name, diff), pulls in bosses.items():
        print(f"  {name} ({diff}): {len(pulls)} pull(s)")

    seen_path = write_abilities_seen(bosses)
    print(f"Abilities per boss (with hit counts and who cast them) written to {os.path.basename(seen_path)}")
    validate_config(bosses)

    output = args.output or f"dashboard_{args.start}_to_{args.end}.html"
    html = build_html(bosses, args)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard written to: {os.path.abspath(output)} ({len(html.encode('utf-8')) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
