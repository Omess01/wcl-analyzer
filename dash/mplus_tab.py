"""Mythic+ tab (from mplus.py's history file) and the automatic Raider.IO refresh."""

import json
import os
from datetime import datetime

import plotly.graph_objects as go

from .common import esc, cards, table, fig_html, MPLUS_FILE


def mplus_tab(n_weeks: int = 8) -> str | None:
    if not os.path.exists(MPLUS_FILE):
        return None
    try:
        from mplus import weeks_in_history, week_summary, requirement
    except ImportError:
        return None
    with open(MPLUS_FILE, encoding="utf-8") as f:
        history = json.load(f)
    players = history.get("players") or {}
    if not players:
        return None

    req = requirement()
    weeks = weeks_in_history(history, n_weeks)
    cur = weeks[-1]
    all_runs = [r for p in players.values() for r in p["runs"].values()]
    first_seen = min((r.get("completed_at") or "9999") for r in all_runs)[:10] if all_runs else "9999"

    def cell(s: dict, week: str) -> str:
        if week < first_seen and not s["count"]:
            return "<td class='mp-unknown' title='before tracking started' aria-label='before tracking started'>?</td>"
        if not s["count"]:
            return f"<td class='mp-fail' data-sort='0'><b>0/{req['runs']}</b><span class='sub'>no runs</span></td>"
        cls = "mp-ok" if s["met"] else ("mp-part" if s["qualifying"] else "mp-fail")
        levels = ", ".join(f"+{l}" for l in s["levels"])
        tip = f"{s['count']} runs: {levels}&#10;{s['timed']}/{s['count']} timed&#10;{s['qualifying']} at +{req['level']} or higher"
        state = "met" if s["met"] else "partial" if s["qualifying"] else "none"
        return (f"<td class='{cls}' data-sort='{s['qualifying']}' title='{esc(tip)}'>"
                f"<b>{s['qualifying']}/{req['runs']}</b><span class='sub'>+{s['highest']} &middot; {s['count']} runs &middot; {state}</span></td>")

    rows = ""
    met_now = 0
    heat_players, heat_z = [], []
    for key, p in sorted(players.items(), key=lambda kv: -(kv[1].get("score") or 0)):
        summaries = [week_summary([r for r in p["runs"].values() if r["week"] == w]) for w in weeks]
        tracked = [s for s, w in zip(summaries, weeks) if w >= first_seen or s["count"]]
        weeks_met = sum(1 for s in tracked if s["met"])
        met_now += summaries[-1]["met"]
        total = sum(s["count"] for s in summaries)
        best = max((s["highest"] for s in summaries), default=0)
        status = "met" if summaries[-1]["met"] else "missing"
        link = (f"<a href='{esc(p.get('profile_url', '#'))}' target='_blank' rel='noopener' "
                f"class='{esc(p.get('class', '').replace(' ', ''))}'>{esc(p.get('name', key))}</a>")
        rows += (f"<tr data-status='{status}'><td>{link}</td><td class='muted'>{esc(p.get('spec', ''))}</td>"
                 f"<td data-sort='{p.get('score', 0)}'>{p.get('score', 0):.0f}</td>"
                 + "".join(cell(s, w) for s, w in zip(summaries, weeks))
                 + f"<td data-sort='{weeks_met / max(len(tracked), 1):.3f}'>{weeks_met}/{len(tracked)}</td>"
                 f"<td data-sort='{total}'>{total}</td><td data-sort='{best}'>+{best}</td></tr>")
        heat_players.append(p.get("name", key))
        heat_z.append([s["qualifying"] for s in summaries])

    headers = [("Player", "str"), ("Spec", "str"), ("Score", "num")]
    headers += [(w[5:], "num") for w in weeks]
    headers += [("Weeks met", "num"), (f"Runs ({n_weeks}w)", "num"), ("Best key", "num")]
    tbl = table(headers, rows, extra_class="mplus", caption="Mythic+ weekly requirement per player")

    fig = go.Figure(go.Heatmap(z=heat_z, x=[w[5:] for w in weeks], y=heat_players, colorscale="Blues",
                               zmin=0, zmax=max(req["runs"], max((max(z) for z in heat_z), default=0)),
                               texttemplate="%{z}", textfont=dict(size=11), colorbar=dict(title="qualifying runs"),
                               hovertemplate="%{y}<br>week of %{x}<br>%{z} qualifying runs<extra></extra>"))
    fig.update_layout(title=f"Qualifying keys (+{req['level']} or higher) per week", yaxis=dict(autorange="reversed"))
    heat = fig_html(fig, height=max(320, 22 * len(heat_players) + 120))

    updated = (history.get("updated") or "")[:16].replace("T", " ")
    timed = " timed" if req["timed"] else ""
    return f"""
    <h1>Mythic+ <span class='diff'>weekly requirement</span></h1>
    {cards([
        ("Requirement", f"{req['runs']} x +{req['level']}{timed} / week"),
        ("Met this week", f"{met_now} / {len(players)}"),
        ("Missing this week", len(players) - met_now),
        ("Week of", cur),
    ])}
    <p class='muted'>Source: Raider.IO, last updated {esc(updated)} UTC. Cells = qualifying runs / required, with the
    highest key and total runs that week; hover for every key level. Green = met, amber = partial, red = none.
    "?" = before tracking started. Change the rule with <code>MPLUS_REQUIRED_RUNS</code>, <code>MPLUS_REQUIRED_LEVEL</code>
    and <code>MPLUS_REQUIRE_TIMED</code> in .env. Run <code>python mplus.py</code> weekly, before reset.</p>
    <label class='filter'><input type='checkbox' id='mpOnlyMissing'> Show only players missing this week's requirement</label>
    {tbl}
    {heat}
    """


def update_mplus_if_stale(force: bool = False, max_age_hours: float | None = None) -> None:
    """
    Refresh mplus_history.json from Raider.IO if roster.txt exists and the
    history is missing or older than MPLUS_MAX_AGE_HOURS (default 12).
    Raider.IO only exposes the current and previous week, so this is what
    keeps the Mythic+ history from developing holes.
    """
    try:
        import mplus
    except ImportError:
        return
    if not os.path.exists(mplus.ROSTER_FILE):
        print("Mythic+: no roster.txt - skipping (python mplus.py --roster-from-raid <start> <end> to create one)")
        return
    if max_age_hours is None:
        try:
            max_age_hours = float(os.getenv("MPLUS_MAX_AGE_HOURS", "12"))
        except ValueError:
            max_age_hours = 12.0
    age_hours = None
    if os.path.exists(mplus.HISTORY_FILE):
        age_hours = (datetime.now().timestamp() - os.path.getmtime(mplus.HISTORY_FILE)) / 3600
    if not force and age_hours is not None and age_hours < max_age_hours:
        print(f"Mythic+: history is {age_hours:.1f}h old - using it (refreshes after {max_age_hours:g}h, or --mplus to force)")
        return
    print("Mythic+: refreshing from Raider.IO" + (f" (history {age_hours:.1f}h old)" if age_hours is not None else " (no history yet)"))
    try:
        roster = mplus.load_roster()
        mplus.update_history(roster)
    except SystemExit as exc:
        print(f"Mythic+: {exc}")
    except Exception as exc:
        print(f"Mythic+: refresh failed ({exc}) - using existing history if any")
