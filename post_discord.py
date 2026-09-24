"""
Post a dashboard file to a Discord channel through a webhook.

    python post_discord.py dashboard_2026-09-01_to_2026-09-21.html [--message "..."]

Needs DISCORD_WEBHOOK_URL in .env (Server settings -> Integrations -> Webhooks).
Discord accepts files up to 10 MB without Nitro; the build prints the size.
See systemd/ for a timer that builds and posts after every raid night.
"""

import argparse
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()


def post(path: str, message: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        sys.exit("DISCORD_WEBHOOK_URL is not set in .env")
    size = os.path.getsize(path)
    if size > 10 * 1024 * 1024:
        sys.exit(f"{path} is {size / 1e6:.1f} MB - over Discord's 10 MB limit; build a shorter range or host the file instead")
    with open(path, "rb") as f:
        r = requests.post(url, data={"content": message}, files={"file": (os.path.basename(path), f, "text/html")}, timeout=60)
    r.raise_for_status()
    print(f"Posted {os.path.basename(path)} ({size / 1e6:.1f} MB) to Discord")


def main() -> None:
    ap = argparse.ArgumentParser(description="Post a dashboard HTML file to Discord via webhook")
    ap.add_argument("file")
    ap.add_argument("--message", default="Raid dashboard updated - download and open in a browser.")
    args = ap.parse_args()
    post(args.file, args.message)


if __name__ == "__main__":
    main()
