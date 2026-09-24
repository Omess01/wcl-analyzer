"""
Step 2: Auto-fetch all of a guild's reports within a date range.

Usage:
    python fetch_reports.py 2026-09-01 2026-09-21

This just lists the reports found - later steps will pull fight/pull
data out of each one and filter down to a specific boss + difficulty.
"""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from wcl_client import run_query

load_dotenv()

REPORTS_QUERY = """
query GuildReports(
    $guildName: String!,
    $guildServerSlug: String!,
    $guildServerRegion: String!,
    $startTime: Float!,
    $endTime: Float!,
    $page: Int!
) {
    reportData {
        reports(
            guildName: $guildName,
            guildServerSlug: $guildServerSlug,
            guildServerRegion: $guildServerRegion,
            startTime: $startTime,
            endTime: $endTime,
            page: $page
        ) {
            data {
                code
                title
                startTime
                endTime
                zone { id name }
            }
            has_more_pages
        }
    }
}
"""


def date_to_ms(date_str: str) -> float:
    """Converts a YYYY-MM-DD string (UTC) to epoch milliseconds."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp() * 1000


def fetch_guild_reports(start_date: str, end_date: str) -> list[dict]:
    guild_name = os.getenv("GUILD_NAME")
    server_slug = os.getenv("GUILD_SERVER_SLUG")
    server_region = os.getenv("GUILD_SERVER_REGION")

    if not all([guild_name, server_slug, server_region]):
        raise RuntimeError(
            "GUILD_NAME / GUILD_SERVER_SLUG / GUILD_SERVER_REGION not set. "
            "Fill these in your .env file."
        )

    start_ms = date_to_ms(start_date)
    # add a day's worth of ms so the end date is inclusive
    end_ms = date_to_ms(end_date) + 24 * 60 * 60 * 1000

    all_reports = []
    page = 1

    while True:
        data = run_query(
            REPORTS_QUERY,
            {
                "guildName": guild_name,
                "guildServerSlug": server_slug,
                "guildServerRegion": server_region,
                "startTime": start_ms,
                "endTime": end_ms,
                "page": page,
            },
        )

        page_data = data["reportData"]["reports"]
        all_reports.extend(page_data["data"])

        if not page_data["has_more_pages"]:
            break
        page += 1

    return all_reports


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python fetch_reports.py <start_date> <end_date>")
        print("Dates in YYYY-MM-DD format, e.g. 2026-09-01 2026-09-21")
        sys.exit(1)

    start_date, end_date = sys.argv[1], sys.argv[2]
    reports = fetch_guild_reports(start_date, end_date)

    if not reports:
        print(f"No reports found between {start_date} and {end_date}.")
    else:
        print(f"Found {len(reports)} report(s):\n")
        for r in reports:
            print(f"  {r['code']}  |  {r['title']}  |  zone: {r['zone']['name']}")
