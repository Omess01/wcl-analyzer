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

from collect_data import collect, default_difficulties
from wcl_client import WCLRateLimited, RATE_QUERY, RATE_REFRESH_MAX_FRACTION
import wcl_client
from path import DATA_DIR, DASHBOARD_DIR
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
    path = os.path.join(DATA_DIR, "abilities_seen.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return path


def write_tank_buffs_seen() -> str | None:
    """
    data/tank_buffs_seen.json = {spec label: {buff id: connected hits it was up on}} (top 25 per tank spec in this build)
    - the input for verifying the ids in config/tank_mitigation.json. Not written (None) when no tank hit carried aura data.
    """
    from analysis.mitigation import TANK_BUFFS_SEEN
    if not TANK_BUFFS_SEEN:
        return None
    out = {spec: {str(bid): n for bid, n in counter.most_common(25)} for spec, counter in sorted(TANK_BUFFS_SEEN.items())}
    path = os.path.join(DATA_DIR, "tank_buffs_seen.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return path


def tank_mitigation_warnings() -> list[str]:
    """Unknown spec keys in tank_mitigation.json, and configured ids never seen on that spec's tanks in this build."""
    import specs
    from analysis.mitigation import load_tank_mitigation, spec_label, mitigation_entry, TANK_BUFFS_SEEN, TANK_MITIGATION_FILE
    fname = os.path.basename(TANK_MITIGATION_FILE)
    cfg = load_tank_mitigation()
    if not cfg:
        return []
    labels = {}
    for cls, token, role, _simc, _sup in specs.SPECS.values():
        if role == "tank":
            labels[spec_label(cls, token)] = (cls, token)
    resolved = {}
    for label, (cls, token) in labels.items():
        entry = mitigation_entry(token, cls)
        if entry is not None:
            for key, val in cfg.items():
                if val is entry:
                    resolved[key] = label
    warnings = []
    for key in cfg:
        if key not in resolved:
            warnings.append(f"{fname}: unknown spec key '{key}' is ignored (expected one of {', '.join(sorted(labels))})")
    for key, label in resolved.items():
        seen = TANK_BUFFS_SEEN.get(label)
        if not seen:
            continue   # no tank of this spec in the build: nothing to check against
        entry = cfg[key]
        missing = sorted((entry["am"] | entry["major"]) - set(seen))
        if missing:
            names = ", ".join(f"{entry['names'].get(i, 'id')} ({i})" for i in missing)
            warnings.append(f"{fname}: {label} ids never seen in any {label} tank's buffs in this range: {names} "
                            f"- check the ids against data/tank_buffs_seen.json")
    return warnings


def validate_config(bosses: dict) -> None:
    """Warn about config that cannot do what it says: typos in avoidable.json, contradictory nights.json entries,
    tank_mitigation.json ids never seen on a tank."""
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
    warnings.extend(tank_mitigation_warnings())
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
        # A full re-download burns thousands of points: refuse up front if most of the hour is already spent.
        try:
            wcl_client.run_query(RATE_QUERY)
        except WCLRateLimited as exc:
            print(f"stopped: {exc}")
            sys.exit(3)
        rate = dict(wcl_client.last_rate)
        spent, limit = rate.get("pointsSpentThisHour") or 0, rate.get("limitPerHour") or 0
        if limit and spent > RATE_REFRESH_MAX_FRACTION * limit:
            print(f"stopped: --refresh refused, {spent:.0f} of {limit:.0f} hourly points already spent "
                  f"(> {RATE_REFRESH_MAX_FRACTION:.0%}); resets in {rate.get('pointsResetIn', 0):.0f} s")
            sys.exit(3)
        import cache
        cache.FORCE_REFRESH = True
        print("--refresh: ignoring cache, re-downloading everything")

    if args.add_report:
        from collect_data import add_report_to_includes
        for code in args.add_report:
            add_report_to_includes(code)

    if not args.no_mplus:
        update_mplus_if_stale(force=args.mplus)

    def _stop_rate_limited(exc: WCLRateLimited):
        reset_in = exc.reset_in if exc.reset_in is not None else wcl_client.last_rate.get("pointsResetIn", 0)
        print(f"\nstopped: hourly points exhausted, resets in {reset_in:.0f} s; "
              "finished fights are cached, re-run later")
        sys.exit(3)

    try:
        bosses = collect(args.start, args.end, difficulties=args.difficulty, boss=args.boss,
                         zone=args.zone, player=args.player, progression_only=args.progression_only, nights=args.nights,
                         reports=args.reports)
    except WCLRateLimited as exc:
        _stop_rate_limited(exc)
    if not bosses:
        print("No matching boss pulls found.")
        return

    print(f"\nBosses found: {len(bosses)}")
    for (name, diff), pulls in bosses.items():
        print(f"  {name} ({diff}): {len(pulls)} pull(s)")

    seen_path = write_abilities_seen(bosses)
    print(f"Abilities per boss (with hit counts and who cast them) written to {os.path.basename(seen_path)}")
    tank_path = write_tank_buffs_seen()
    if tank_path:
        print(f"Buff ids seen on tanks when hit (to verify tank_mitigation.json) written to {os.path.basename(tank_path)}")
    validate_config(bosses)

    output = args.output or os.path.join(DASHBOARD_DIR, f"dashboard_{args.start}_to_{args.end}.html")
    try:
        # build_html -> zone_encounter_order -> cached_query can hit the API when a
        # zone order is not cached yet, so it can run out of points too.
        html = build_html(bosses, args)
    except WCLRateLimited as exc:
        _stop_rate_limited(exc)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDashboard written to: {os.path.abspath(output)} ({len(html.encode('utf-8')) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
