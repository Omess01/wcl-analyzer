#!/usr/bin/env bash
# Build the dashboard for the current tier-to-date range and post it to Discord.
# Called by wcl-dashboard.timer; adjust START to the tier's first raid night.
set -euo pipefail
cd "$(dirname "$0")/.."
START="${WCL_RANGE_START:-2026-08-23}"
END="$(date +%F)"
OUT="dashboards/dashboard_${START}_to_${END}.html"
venv/bin/python build_dashboard.py "$START" "$END" -o "$OUT"
venv/bin/python post_discord.py "$OUT" --message "Raid dashboard ${START} to ${END}"
