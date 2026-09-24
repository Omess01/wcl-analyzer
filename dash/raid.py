"""Raid tab: the raid as an organisation, across all bosses."""

from collections import Counter, defaultdict
from datetime import datetime

import plotly.graph_objects as go

from collect_data import NIGHT_FIGHTS, NIGHT_PLAYERS, busy_ms_between, get_timezone
from .common import (esc, fmt_duration, cards, table, fig_html, median, parse_class, break_minutes, all_pulls,
                     filter_bosses_by_type, pull_specs, spec_role, player_role_labels)


def night_report(pulls_all: list[dict]) -> str:
    thr = break_minutes()
    nights: dict[str, list[dict]] = defaultdict(list)
    for p in pulls_all:
        nights[p["night"]].append(p)
    rows = ""
    chart_nights, chart_series = [], defaultdict(list)
    tz = get_timezone()
    for night, ps in sorted(nights.items(), key=lambda kv: kv[1][0]["absolute_start_ms"]):
        ps.sort(key=lambda p: p["absolute_start_ms"])
        combat = sum(p["duration_seconds"] for p in ps)
        night_start, night_end = ps[0]["absolute_start_ms"], ps[-1]["absolute_start_ms"] + ps[-1]["duration_seconds"] * 1000
        span = (night_end - night_start) / 1000
        trash = sum((e - a) / 1000 for a, e, is_boss in NIGHT_FIGHTS.get(night, []) if not is_boss and a >= night_start and e <= night_end)
        idle = max(span - combat - trash, 0)
        gaps = []
        for i in range(1, len(ps)):
            prev_end = ps[i - 1]["absolute_start_ms"] + ps[i - 1]["duration_seconds"] * 1000
            g = (ps[i]["absolute_start_ms"] - prev_end) / 60000
            gaps.append(g - busy_ms_between(night, prev_end, ps[i]["absolute_start_ms"]) / 60000)
        breaks = [g for g in gaps if g >= thr]
        recover = [g for g in gaps if 0 <= g < thr]
        med_recover = median(recover) if recover else 0
        per_boss = Counter(p["boss"] for p in ps)
        kills_by_boss = Counter(p["boss"] for p in ps if p["kill"])
        boss_txt = ", ".join(f"{esc(bn.split(' (')[0])} {n}{' &#10003;' * kills_by_boss[bn]}" for bn, n in per_boss.most_common())
        players = {name for p in ps for name in p["participants"]}
        bench = sorted(set(NIGHT_PLAYERS.get(night, {})) - players)
        bench_cell = (f"<td data-sort='{len(bench)}' title='{esc(', '.join(bench))}'>{len(bench)} <span class='sub'>{esc(', '.join(bench[:4]))}"
                      f"{' &hellip;' if len(bench) > 4 else ''}</span></td>") if bench else "<td data-sort='0'>0</td>"
        pph = len(ps) / (span / 3600) if span else 0
        end_txt = datetime.fromtimestamp(night_end / 1000, tz=tz).strftime("%H:%M")
        rows += (f"<tr{' class=open-night' if ps[0].get('night_type') == 'open' else ''}><td>{esc(night)}</td><td class='muted'>{ps[0]['pull_time']} - {end_txt}</td>"
                 f"<td>{boss_txt}</td><td>{len(ps)}</td><td>{sum(kills_by_boss.values())}</td>"
                 f"<td data-sort='{combat}'>{fmt_duration(combat)}</td><td data-sort='{trash}'>{fmt_duration(trash)}</td>"
                 f"<td data-sort='{idle}'>{fmt_duration(idle)} <span class='muted'>({idle / span * 100 if span else 0:.0f}%)</span></td>"
                 f"<td data-sort='{pph:.2f}'>{pph:.1f}</td><td data-sort='{med_recover:.1f}'>{med_recover:.1f} min</td>"
                 f"<td>{len(breaks)}{(' (' + ', '.join(f'{g:.0f}m' for g in breaks) + ')') if breaks else ''}</td><td>{len(players)}</td>{bench_cell}</tr>")
        chart_nights.append(night)
        for bn, _ in per_boss.most_common():
            chart_series[bn].append((night, sum(p["duration_seconds"] for p in ps if p["boss"] == bn) / 60))
    fig = go.Figure()
    for bn, pts in chart_series.items():
        d = dict(pts)
        fig.add_trace(go.Bar(name=bn.split(" (")[0], x=chart_nights, y=[d.get(n, 0) for n in chart_nights]))
    fig.update_layout(barmode="stack", title="Minutes in combat per night, by boss", yaxis_title="Minutes",
                      legend=dict(orientation="h", y=1.08, x=0), margin=dict(l=45, r=20, t=80, b=45))
    return (table([("Night", "str"), ("Raid time", "str"), ("Bosses (pulls, ✓ = kill)", "str"), ("Pulls", "num"), ("Kills", "num"),
                   ("Boss combat", "num"), ("Trash", "num"), ("Idle", "num"), ("Pulls / hour", "num"), ("Median recovery", "num"),
                   ("Breaks", "str"), ("Players", "num"), ("Bench", "num")], rows, caption="Night report")
            + "<p class='muted'>Raid time runs from the first boss pull to the end of the last one - trash before the first boss isn't counted. "
              "<b>Trash</b> is time in non-boss fights (WCL logs them too). <b>Idle</b> is everything else: run-backs, breaks, talking. "
              f"<b>Median recovery</b> is the typical idle gap from a wipe to the next pull, breaks ({break_minutes():g}+ idle min) excluded; "
              "trash cleared in between doesn't count against it. <b>Bench</b> = players who were in a fight that night (trash counts) but in no boss pull.</p>"
            + fig_html(fig, height=360))


def attendance_matrix(pulls_all: list[dict]) -> str:
    # Attendance is about the main roster: open nights don't count. (If the file
    # was built from open nights only, there is nothing else to show, so keep them.)
    main = [p for p in pulls_all if p.get("night_type") != "open"]
    open_nights = len({p["night"] for p in pulls_all if p.get("night_type") == "open"})
    note = (f"<p class='muted'>{open_nights} open night{'s' if open_nights != 1 else ''} excluded - attendance counts main raid nights only.</p>"
            if main and open_nights else "")
    pulls_all = main or pulls_all
    nights = []
    for p in pulls_all:
        if p["night"] not in nights:
            nights.append(p["night"])
    per_night_total = Counter(p["night"] for p in pulls_all)
    att: dict[str, Counter] = defaultdict(Counter)
    first_pull: dict[tuple[str, str], int] = {}     # (player, night) -> 1-based index of their first pull that night
    classes: dict[str, str] = {}
    night_pulls: dict[str, list[dict]] = defaultdict(list)
    for p in pulls_all:
        night_pulls[p["night"]].append(p)
    for n, ps in night_pulls.items():
        for idx, p in enumerate(sorted(ps, key=lambda q: q["absolute_start_ms"]), start=1):
            for name, cls in p["participants"].items():
                att[name][n] += 1
                classes[name] = cls
                first_pull.setdefault((name, n), idx)
    total_pulls = len(pulls_all)
    role_labels = player_role_labels(pulls_all)
    rows = ""
    hidden = 0
    late_any = False
    for name, c in sorted(att.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(c.values())
        low = tot < 0.25 * total_pulls
        hidden += low
        cells = ""
        for n in nights:
            k, tn = c.get(n, 0), per_night_total[n]
            if not k:
                if name in NIGHT_PLAYERS.get(n, {}):
                    cells += "<td class='att-0' data-sort='0' title='in the raid that night (trash fights) but in no boss pull'>bench</td>"
                else:
                    cells += "<td class='att-0' data-sort='0' aria-label='absent'>&ndash;</td>"
            else:
                share = k / tn
                fp = first_pull.get((name, n), 1)
                late = f"<span class='sub'>from #{fp}</span>" if fp > 1 else ""
                late_any = late_any or fp > 1
                cells += (f"<td class='att' style='background:rgba(122,162,227,{0.12 + 0.5 * share:.2f})' data-sort='{share:.3f}' "
                          f"title='{k} of {tn} pulls{f', first pull #{fp}' if fp > 1 else ''}'>{k}<span class='sub'>/{tn}</span>{late}</td>")
        nights_present = sum(1 for n in nights if c.get(n))
        rows += (f"<tr{' class=lowpart' if low else ''}><td class='{esc(classes[name])}'>{esc(name)}</td><td class='muted'>{esc(role_labels.get(name, ''))}</td>"
                 f"{cells}<td data-sort='{nights_present}'>{nights_present}/{len(nights)}</td>"
                 f"<td data-sort='{tot / total_pulls:.3f}'>{tot} <span class='muted'>({tot / total_pulls * 100:.0f}%)</span></td></tr>")
    headers = [("Player", "str"), ("Role", "str")] + [(n[4:], "num") for n in nights] + [("Nights", "num"), ("Pulls", "num")]
    label = (f"<label class='filter'><input type='checkbox' class='showLow'> Show {hidden} hidden player{'s' if hidden != 1 else ''} "
             f"with under 25% of main-night pulls</label>") if hidden else ""
    legend = ("<p class='muted'>&ndash; = not in the raid; <b>bench</b> = in the raid (trash fights) but in no boss pull"
              + ("; <b>from #n</b> = joined at that pull, not from the first" if late_any else "") + ".</p>")
    return note + label + table(headers, rows, extra_class="attendance", caption="Attendance per night") + legend


def parse_table(pulls_all: list[dict]) -> str:
    """Average WCL percentile per player across every kill - fair across bosses and specs."""
    per: dict[str, dict] = {}
    for p in pulls_all:
        if not p["kill"] or not p.get("parses"):
            continue
        specs = pull_specs(p)
        for name, pr in p["parses"].items():
            role = spec_role(specs.get(name, ""))
            metric = "hps" if role == "healer" else "dps"
            val = pr.get(metric)
            if val is None:
                val = pr.get("dps", pr.get("hps"))
            if val is None:
                continue
            e = per.setdefault(name, {"class": p["participants"].get(name, ""), "vals": [], "by_boss": [], "metric": metric})
            e["vals"].append(val)
            e["by_boss"].append(f"{p['boss'].split(' (')[0]} {val:.0f}")
    if not per:
        return "<p class='muted'>No kills with rankings in this range yet.</p>"
    rows = ""
    for name, e in sorted(per.items(), key=lambda kv: -(sum(kv[1]["vals"]) / len(kv[1]["vals"]))):
        avg = sum(e["vals"]) / len(e["vals"])
        rows += (f"<tr><td class='{esc(e['class'])}'>{esc(name)}</td><td class='muted'>{e['metric'].upper()}</td>"
                 f"<td data-sort='{avg:.1f}' class='{parse_class(avg)}'><b>{avg:.0f}</b></td>"
                 f"<td data-sort='{max(e['vals']):.0f}' class='{parse_class(max(e['vals']))}'>{max(e['vals']):.0f}</td>"
                 f"<td data-sort='{min(e['vals']):.0f}' class='{parse_class(min(e['vals']))}'>{min(e['vals']):.0f}</td>"
                 f"<td>{len(e['vals'])}</td><td class='muted'>{esc(', '.join(e['by_boss']))}</td></tr>")
    return table([("Player", "str"), ("Metric", "str"), ("Avg parse", "num"), ("Best", "num"), ("Worst", "num"),
                  ("Kills", "num"), ("Per kill", "str")], rows, caption="Average parse per player across kills")


def kill_time_trend(bosses: dict) -> str:
    fig = go.Figure()
    any_trace = False
    for (name, diff), pulls in bosses.items():
        kills = [p for p in pulls if p["kill"]]
        if len(kills) < 2:
            continue
        any_trace = True
        fig.add_trace(go.Scatter(x=[k["night"][4:] for k in kills], y=[k["duration_seconds"] for k in kills],
                                 mode="lines+markers", name=name,
                                 hovertext=[f"{name}<br>{k['night']}<br>{fmt_duration(k['duration_seconds'])} - {len(k['deaths'])} deaths" for k in kills],
                                 hoverinfo="text"))
    if not any_trace:
        return ""
    fig.update_layout(title="Kill time on farm bosses, per week (faster = the payoff of better play)", yaxis_title="Kill duration (s)",
                      legend=dict(orientation="h", y=1.08, x=0), margin=dict(l=45, r=20, t=80, b=45))
    return "<h3>Farm kill times</h3>" + fig_html(fig, height=360)


def raid_tab(bosses: dict, night_type: str | None = None) -> str:
    bosses = filter_bosses_by_type(bosses, night_type)
    pulls_all = all_pulls(bosses)
    if not pulls_all:
        return "<p class='muted'>No pulls.</p>"
    label = {"main": "main raid nights", "open": "open nights", None: "across all bosses"}[night_type]
    nights = len({p["night"] for p in pulls_all})
    combat = sum(p["duration_seconds"] for p in pulls_all)
    kills = sum(1 for p in pulls_all if p["kill"])
    roster = {name for p in pulls_all for name in p["participants"]}
    return f"""
    <h1>Raid <span class='diff'>{label}</span></h1>
    <p class='muted'>Nothing here is a sum of boss numbers - those don't compare across fights. This is the raid as an organisation:
    how the nights are spent, who shows up, and the one performance number that is fair across bosses (WCL parse).
    {"Open nights are on their own Raid tab." if night_type == "main" else "Main raid nights are on their own Raid tab." if night_type == "open" else ""}</p>
    {cards([("Raid nights", nights), ("Pulls", len(pulls_all)), ("Kills", kills), ("Time in combat", fmt_duration(combat)),
            ("Different players", len(roster))])}
    <h2>Night report</h2>
    {night_report(pulls_all)}
    <h2>Attendance</h2>
    <p class='muted'>Main raid nights only. Pulls attended out of pulls that night; darker = more of the night; &ndash; = absent. Sorted by total attendance.</p>
    {attendance_matrix(pulls_all)}
    <h2>Performance across kills</h2>
    <p class='muted'>Average WCL percentile per player over every kill in the range - DPS parse for damage dealers and tanks, HPS parse for healers.
    Percentiles already account for boss and spec, so unlike DPS this is comparable across the whole tier.</p>
    {parse_table(pulls_all)}
    {kill_time_trend(bosses)}
    """
