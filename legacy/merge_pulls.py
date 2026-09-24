"""
Step 3: Fetch fight/pull data from each report found in step 2, filter
down to a specific boss + difficulty, and merge all matching pulls
from across every report into one combined list - this is the core
"multiple report analysis" behavior.

Usage:
    python merge_pulls.py 2026-09-01 2026-09-21 "Ula'tek" Heroic
"""

import sys
from datetime import datetime, timezone

from fetch_reports import fetch_guild_reports
from wcl_client import run_query

DIFFICULTY_MAP = {
    "lfr": 1,
    "normal": 3,
    "heroic": 4,
    "mythic": 5,
}

FIGHTS_QUERY = """
query ReportFights($code: String!, $difficulty: Int!) {
    reportData {
        report(code: $code) {
            fights(difficulty: $difficulty) {
                id
                name
                difficulty
                kill
                startTime
                endTime
                bossPercentage
                fightPercentage
            }
        }
    }
}
"""


def get_report_fights(report_code: str, difficulty: int) -> list[dict]:
    data = run_query(FIGHTS_QUERY, {"code": report_code, "difficulty": difficulty})
    report = data["reportData"]["report"]
    if report is None:
        # Report code was invalid, deleted, or private
        return []
    return report["fights"] or []


def normalize(name: str) -> str:
    """Lowercase and strip punctuation so 'Ula'tek' matches 'Ula tek' etc."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def merge_pulls(start_date: str, end_date: str, boss_name: str, difficulty_name: str) -> list[dict]:
    difficulty = DIFFICULTY_MAP.get(difficulty_name.lower())
    if difficulty is None:
        raise ValueError(
            f"Unknown difficulty '{difficulty_name}'. Use one of: {list(DIFFICULTY_MAP)}"
        )

    reports = fetch_guild_reports(start_date, end_date)
    target = normalize(boss_name)

    all_pulls = []
    for report in reports:
        fights = get_report_fights(report["code"], difficulty)
        for fight in fights:
            if normalize(fight["name"]) == target:
                duration_seconds = (fight["endTime"] - fight["startTime"]) / 1000
                # fight.startTime is milliseconds *since the report started*,
                # not an absolute timestamp - add the report's own startTime
                # (absolute, epoch ms) to get the pull's real-world moment.
                absolute_start_ms = report["startTime"] + fight["startTime"]
                pull_dt = datetime.fromtimestamp(absolute_start_ms / 1000, tz=timezone.utc)
                all_pulls.append(
                    {
                        "report_code": report["code"],
                        "report_title": report["title"],
                        "fight_id": fight["id"],
                        "kill": fight["kill"],
                        "boss_percentage": fight.get("bossPercentage"),
                        "duration_seconds": round(duration_seconds, 1),
                        "absolute_start_ms": absolute_start_ms,
                        "pull_datetime": pull_dt,
                    }
                )

    # Sort chronologically by real-world time - the API's report order
    # is not guaranteed to match the actual dates.
    all_pulls.sort(key=lambda p: p["absolute_start_ms"])

    return all_pulls


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print('Usage: python merge_pulls.py <start_date> <end_date> "<boss name>" <difficulty>')
        print('Example: python merge_pulls.py 2026-09-01 2026-09-21 "Ula\'tek" Heroic')
        sys.exit(1)

    start_date, end_date, boss_name, difficulty_name = sys.argv[1:5]
    pulls = merge_pulls(start_date, end_date, boss_name, difficulty_name)

    if not pulls:
        print(f"No pulls found for '{boss_name}' ({difficulty_name}) in that date range.")
        sys.exit(0)

    kills = [p for p in pulls if p["kill"]]
    wipes = [p for p in pulls if not p["kill"]]

    print(f"Found {len(pulls)} pull(s) across all reports: {len(kills)} kill(s), {len(wipes)} wipe(s)\n")

    current_date = None
    for i, p in enumerate(pulls, start=1):
        pull_date = p["pull_datetime"].strftime("%Y-%m-%d")
        if pull_date != current_date:
            current_date = pull_date
            print(f"\n--- {pull_date} ({p['report_title']}) ---")

        time_str = p["pull_datetime"].strftime("%H:%M:%S")
        result = "KILL" if p["kill"] else f"wipe @ {p['boss_percentage']}%"
        print(f"  pull #{i}  [{time_str} UTC]  [{p['report_code']}] fight {p['fight_id']}  |  {result}  |  {p['duration_seconds']}s")