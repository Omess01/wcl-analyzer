"""
Mythic+ activity tracker (Raider.IO).

Pulls each roster member's recent Mythic+ runs from Raider.IO's public API
and merges them into a local history file, so that over time you get a full
per-week record of how many keys people ran and at what level.

Raider.IO only exposes the CURRENT and PREVIOUS week (up to ~10 highest
runs each) plus the ~10 most recent runs, so run this at least once a week -
ideally right before reset - to never lose a week.

Usage:
    python mplus.py                          # update history from roster.txt
    python mplus.py --roster-from-raid 2026-09-01 2026-09-21
                                             # build roster.txt from everyone who
                                             # was in a raid pull in that range
    python mplus.py --show                   # print the last weeks as a table

roster.txt format - one character per line, realm as the URL slug:
    Omess,tarren-mill
    Somedude,silvermoon

Region comes from GUILD_SERVER_REGION in .env (US/EU/KR/TW), override with RIO_REGION.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
ROSTER_FILE = os.path.join(HERE, "roster.txt")
HISTORY_FILE = os.path.join(HERE, "mplus_history.json")

RIO_URL = "https://raider.io/api/v1/characters/profile"
RIO_FIELDS = ",".join([
    "mythic_plus_scores_by_season:current",
    "mythic_plus_weekly_highest_level_runs",
    "mythic_plus_previous_weekly_highest_level_runs",
    "mythic_plus_recent_runs",
])

# Weekly reset, in UTC. Override with RESET_WEEKDAY (0=Mon..6=Sun) and RESET_HOUR_UTC.
DEFAULT_RESET = {"us": (1, 15), "eu": (2, 4), "kr": (2, 22), "tw": (2, 22), "cn": (2, 22)}


def requirement() -> dict:
    """Weekly requirement: N runs at key level >= L (optionally timed). From .env."""
    def _int(name, default):
        try:
            return int(os.getenv(name, default))
        except ValueError:
            return default
    return {
        "runs": _int("MPLUS_REQUIRED_RUNS", 4),
        "level": _int("MPLUS_REQUIRED_LEVEL", 10),
        "timed": (os.getenv("MPLUS_REQUIRE_TIMED", "false").lower() in ("1", "true", "yes")),
    }


def region() -> str:
    return (os.getenv("RIO_REGION") or os.getenv("GUILD_SERVER_REGION") or "us").lower()


def reset_rule() -> tuple[int, int]:
    wd, hr = DEFAULT_RESET.get(region(), (1, 15))
    wd = int(os.getenv("RESET_WEEKDAY", wd))
    hr = int(os.getenv("RESET_HOUR_UTC", hr))
    return wd, hr


def week_start(dt: datetime) -> str:
    """Date (YYYY-MM-DD) of the reset that started the week containing dt."""
    wd, hr = reset_rule()
    dt = dt.astimezone(timezone.utc)
    days_back = (dt.weekday() - wd) % 7
    candidate = (dt - timedelta(days=days_back)).replace(hour=hr, minute=0, second=0, microsecond=0)
    if candidate > dt:
        candidate -= timedelta(days=7)
    return candidate.strftime("%Y-%m-%d")


def current_week() -> str:
    return week_start(datetime.now(timezone.utc))


def hours_since_reset() -> float:
    """Hours since the current week's reset (used to soften 'nobody has done their keys' right after reset)."""
    wd, hr = reset_rule()
    start = datetime.strptime(current_week(), "%Y-%m-%d").replace(hour=hr, tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - start).total_seconds() / 3600, 0.0)


# --------------------------------------------------------------------------
# Roster
# --------------------------------------------------------------------------

def load_roster() -> list[tuple[str, str]]:
    if not os.path.exists(ROSTER_FILE):
        raise SystemExit(
            f"No {os.path.basename(ROSTER_FILE)} found. Create it (Name,realm-slug per line) or run\n"
            "  python mplus.py --roster-from-raid <start> <end>"
        )
    roster = []
    with open(ROSTER_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," in line:
                name, realm = [x.strip() for x in line.split(",", 1)]
            elif "-" in line:
                name, realm = [x.strip() for x in line.split("-", 1)]
            else:
                print(f"  skipping malformed roster line: {line}")
                continue
            roster.append((name, realm.lower().replace(" ", "-").replace("'", "")))
    return roster


def realm_slugs() -> dict[str, str]:
    """
    {combat-log realm name -> Raider.IO slug}. Combat logs write realms with
    spaces/apostrophes stripped ("TarrenMill", "ArgentDawn"); Raider.IO wants
    the URL slug ("tarren-mill", "argent-dawn"). WCL's server list has both.
    """
    from cache import cached_query
    query = """
    query Servers($region: String!, $page: Int!) {
        worldData { region(slug: $region) { servers(page: $page) {
            data { name slug }
            has_more_pages
        } } }
    }"""
    mapping: dict[str, str] = {}
    page = 1
    try:
        while True:
            data = cached_query(query, {"region": region(), "page": page})
            servers = data["worldData"]["region"]["servers"]
            for s in servers["data"]:
                key = "".join(ch for ch in s["name"].lower() if ch.isalnum())
                mapping[key] = s["slug"]
            if not servers.get("has_more_pages"):
                break
            page += 1
    except Exception as exc:
        print(f"  (could not fetch realm list from WCL, using raw names: {exc})")
    return mapping


def roster_from_raid(start_date: str, end_date: str, min_pulls: int = 1, nights: str = "all") -> list[tuple[str, str]]:
    """
    Everyone who participated in at least `min_pulls` boss pulls in the range,
    with their realm resolved to a Raider.IO slug. nights='main' skips open
    nights (so visitors don't inflate the M+ roster), 'open' keeps only those.
    """
    from cache import cached_query
    from fetch_reports import fetch_guild_reports
    from collect_data import classify_night, get_timezone

    query = """
    query Actors($code: String!) {
        reportData { report(code: $code) {
            masterData { actors(type: "Player") { id name server } }
            fights { encounterID friendlyPlayers }
        } }
    }"""
    slugs = realm_slugs()
    pulls: dict[str, int] = {}
    realm_of: dict[str, str] = {}
    tz = get_timezone()
    for report in fetch_guild_reports(start_date, end_date):
        night_dt = datetime.fromtimestamp(report["startTime"] / 1000, tz=tz)
        night_type = classify_night(night_dt, report.get("title", ""), report["code"])
        if night_type is None or (nights != "all" and night_type != nights):
            continue
        data = cached_query(query, {"code": report["code"]})
        rep = data["reportData"]["report"] or {}
        actors = {a["id"]: a for a in (rep.get("masterData") or {}).get("actors", []) or []}
        for fight in rep.get("fights") or []:
            if not fight.get("encounterID"):
                continue
            for pid in fight.get("friendlyPlayers") or []:
                a = actors.get(pid)
                if a and a.get("server"):
                    pulls[a["name"]] = pulls.get(a["name"], 0) + 1
                    raw = a["server"]
                    key = "".join(ch for ch in raw.lower() if ch.isalnum())
                    realm_of[a["name"]] = slugs.get(key) or raw.lower().replace(" ", "-").replace("'", "")

    roster = sorted((n, realm_of[n]) for n, c in pulls.items() if c >= min_pulls)
    skipped = len(pulls) - len(roster)
    with open(ROSTER_FILE, "w", encoding="utf-8") as f:
        f.write(f"# name,realm-slug  (raid participants {start_date}..{end_date}, min {min_pulls} pulls - edit freely)\n")
        for name, realm in roster:
            f.write(f"{name},{realm}\n")
    print(f"Wrote {len(roster)} characters to {ROSTER_FILE}" + (f" ({skipped} skipped with < {min_pulls} pulls)" if skipped else ""))
    return roster


# --------------------------------------------------------------------------
# Raider.IO
# --------------------------------------------------------------------------

def fetch_profile(name: str, realm: str) -> dict | None:
    params = {"region": region(), "realm": realm, "name": name, "fields": RIO_FIELDS}
    for attempt in range(3):
        r = requests.get(RIO_URL, params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(2 + attempt * 3)
            continue
        if r.status_code in (400, 404):
            print(f"  {name}-{realm}: not found on Raider.IO ({r.status_code})")
            return None
        print(f"  {name}-{realm}: HTTP {r.status_code}")
        return None
    return None


def run_key(run: dict) -> str:
    return run.get("url") or f"{run.get('completed_at')}|{run.get('dungeon')}|{run.get('mythic_level')}"


def normalize_run(run: dict) -> dict:
    completed = run.get("completed_at")
    dt = datetime.fromisoformat(completed.replace("Z", "+00:00")) if completed else datetime.now(timezone.utc)
    return {
        "dungeon": run.get("dungeon"),
        "short": run.get("short_name"),
        "level": run.get("mythic_level"),
        "upgrades": run.get("num_keystone_upgrades", 0),
        "timed": (run.get("num_keystone_upgrades") or 0) > 0,
        "completed_at": completed,
        "week": week_start(dt),
        "score": run.get("score"),
    }


def update_history(roster: list[tuple[str, str]]) -> dict:
    history = {"region": region(), "players": {}}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
    players = history.setdefault("players", {})

    for name, realm in roster:
        key = f"{name}-{realm}"
        profile = fetch_profile(name, realm)
        if not profile:
            continue
        entry = players.setdefault(key, {"runs": {}})
        entry.update({
            "name": profile.get("name", name),
            "realm": profile.get("realm", realm),
            "class": profile.get("class", ""),
            "spec": profile.get("active_spec_name", ""),
            "role": profile.get("active_spec_role", ""),
            "profile_url": profile.get("profile_url", ""),
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        seasons = profile.get("mythic_plus_scores_by_season") or []
        if seasons:
            entry["score"] = (seasons[0].get("scores") or {}).get("all", 0)

        new = 0
        for field in ("mythic_plus_weekly_highest_level_runs",
                      "mythic_plus_previous_weekly_highest_level_runs",
                      "mythic_plus_recent_runs"):
            for run in profile.get(field) or []:
                k = run_key(run)
                if k not in entry["runs"]:
                    entry["runs"][k] = normalize_run(run)
                    new += 1
        this_week = sum(1 for r in entry["runs"].values() if r["week"] == current_week())
        print(f"  {key:<32} score {entry.get('score', 0):>6.0f}   +{new} new runs   {this_week} this week")
        time.sleep(0.25)  # be polite to Raider.IO

    history["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=1, ensure_ascii=False)
    return history


# --------------------------------------------------------------------------
# Reporting helpers (also used by the dashboard)
# --------------------------------------------------------------------------

def weeks_in_history(history: dict, n: int) -> list[str]:
    """The last n week-start dates, ending at the current week, oldest first."""
    cur = datetime.strptime(current_week(), "%Y-%m-%d")
    return [(cur - timedelta(days=7 * i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]


def week_summary(runs: list[dict]) -> dict:
    """{count, highest, levels, timed, qualifying, met} for one player-week."""
    req = requirement()
    levels = sorted((r["level"] or 0 for r in runs), reverse=True)
    qualifying = sum(
        1 for r in runs
        if (r["level"] or 0) >= req["level"] and (r.get("timed") or not req["timed"])
    )
    return {
        "count": len(runs),
        "highest": levels[0] if levels else 0,
        "levels": levels,
        "timed": sum(1 for r in runs if r.get("timed")),
        "qualifying": qualifying,
        "met": qualifying >= req["runs"],
    }


def show(history: dict, n_weeks: int = 6, only_failing: bool = False) -> None:
    req = requirement()
    weeks = weeks_in_history(history, n_weeks)
    cur = weeks[-1]
    print(f"\nRequirement: {req['runs']} x +{req['level']}{' timed' if req['timed'] else ''} per week")
    print(f"{'Player':<24}{'Score':>7}  " + "  ".join(f"{w[5:]:^9}" for w in weeks))
    print("-" * (33 + 11 * len(weeks)))
    met_now = 0
    shown = 0
    for key, p in sorted(history["players"].items(), key=lambda kv: -(kv[1].get("score") or 0)):
        summaries = {w: week_summary([r for r in p["runs"].values() if r["week"] == w]) for w in weeks}
        if summaries[cur]["met"]:
            met_now += 1
        if only_failing and summaries[cur]["met"]:
            continue
        shown += 1
        cells = []
        for w in weeks:
            s = summaries[w]
            if not s["count"]:
                cells.append("    -    ")
            else:
                mark = "OK" if s["met"] else "  "
                cells.append(f"{s['qualifying']}/{req['runs']} +{s['highest']:<2}{mark}")
        print(f"{p.get('name', key):<24}{p.get('score', 0):>7.0f}  " + "  ".join(cells))
    print(f"\n{met_now}/{len(history['players'])} players have met the requirement this week (week of {cur}).")
    print("(cell = qualifying runs / required, highest key; OK = requirement met)")


def main():
    ap = argparse.ArgumentParser(description="Track guild Mythic+ activity via Raider.IO")
    ap.add_argument("--roster-from-raid", nargs=2, metavar=("START", "END"),
                    help="generate roster.txt from raid participants in a date range")
    ap.add_argument("--min-pulls", type=int, default=1,
                    help="with --roster-from-raid: only include players with at least this many pulls")
    ap.add_argument("--nights", choices=["all", "main", "open"], default="all",
                    help="with --roster-from-raid: only count main raid nights (MAIN_RAID_DAYS) or only open nights")
    ap.add_argument("--show", action="store_true", help="print history table without fetching")
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--failing", action="store_true", help="only list players who have NOT met this week's requirement")
    args = ap.parse_args()

    if args.roster_from_raid:
        roster_from_raid(*args.roster_from_raid, min_pulls=args.min_pulls, nights=args.nights)
        return

    if args.show:
        if not os.path.exists(HISTORY_FILE):
            raise SystemExit("No history yet - run without --show first.")
        with open(HISTORY_FILE, encoding="utf-8") as f:
            show(json.load(f), args.weeks, args.failing)
        return

    roster = load_roster()
    print(f"Updating M+ history for {len(roster)} characters ({region().upper()}), week of {current_week()}")
    history = update_history(roster)
    show(history, args.weeks, args.failing)


if __name__ == "__main__":
    main()
