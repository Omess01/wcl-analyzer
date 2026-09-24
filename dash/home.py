"""Home tab: where are we, what happened last night, what to look at."""

import json
import os
from collections import Counter, defaultdict

import plotly.graph_objects as go

from collect_data import NIGHT_FIGHTS, NIGHT_PLAYERS, normalize
from .common import (esc, fmt_duration, pct_color, cards, table, gotab, fig_html, median, avoidable_set, player_roles,
                     all_pulls, filter_bosses_by_type, regulars, player_stats, boss_status, night_stats, MPLUS_FILE,
                     LINE_DASHES, MARKERS)

SEVERITY_LABEL = {"warn": "warning", "good": "good", "info": "note"}


def progress_strip(ordered: list) -> str:
    boxes = ""
    for i, ((name, diff), pulls) in enumerate(ordered):
        if not pulls:
            continue
        s = boss_status(pulls)
        if s["killed"]:
            top = "<div class='ps-top kill'>&#10003; killed</div>"
            sub = f"{s['kills']} kill{'s' if s['kills'] != 1 else ''} &middot; first {esc(s['first_kill'][4:])} &middot; {s['prog_pulls']} pulls to kill"
            cls = "killed"
        else:
            top = f"<div class='ps-top' style='color:{pct_color(s['best'])}'>{s['best']:.1f}% best</div>"
            sub = f"{s['pulls']} pulls &middot; last {esc(s['last_night'][4:])}"
            cls = "prog"
        boxes += (f"<button type='button' class='ps-box {cls} gotab' data-tab='tab{i}'><div class='ps-name'>{esc(name)} <span class='diff'>{esc(diff)}</span></div>"
                  f"{top}<div class='ps-sub'>{sub}</div></button>")
    return f"<div class='progress-strip'>{boxes}</div>"


def progression_timeline(ordered: list) -> str:
    """
    Progression by first kills, per difficulty: a step chart of how many bosses
    had been killed at least once by the end of each raid night, plus a table
    (bosses in zone order) with first-kill night, pulls and nights it took.
    """
    by_diff: dict[str, list] = defaultdict(list)
    for (name, diff), pulls in ordered:
        if pulls:
            by_diff[diff].append((name, pulls))
    if not by_diff:
        return ""
    nights_all = sorted({p["night"] for _, pulls in ordered for p in pulls},
                        key=lambda n: min(p["absolute_start_ms"] for _, pulls in ordered for p in pulls if p["night"] == n))
    fig = go.Figure()
    rows = ""
    for diff, bosses in by_diff.items():
        first_kills: dict[str, list[str]] = defaultdict(list)     # night -> bosses first killed that night
        for name, pulls in bosses:
            kill_idx = next((i for i, p in enumerate(pulls) if p["kill"]), None)
            nights_here = []
            for p in pulls:
                if p["night"] not in nights_here:
                    nights_here.append(p["night"])
            if kill_idx is not None:
                kp = pulls[kill_idx]
                first_kills[kp["night"]].append(name)
                nights_to = nights_here.index(kp["night"]) + 1
                rows += (f"<tr><td class='muted'>{esc(diff)}</td><td>{esc(name)}</td>"
                         f"<td data-sort='{kp['absolute_start_ms']}'><span class='tag good'>killed</span> {esc(kp['night'])}</td>"
                         f"<td>{kill_idx + 1}</td><td>{nights_to}</td>"
                         f"<td>{sum(1 for p in pulls if p['kill'])} kill{'s' if sum(1 for p in pulls if p['kill']) != 1 else ''} in {len(pulls)} pulls</td></tr>")
            else:
                best = min(p["boss_percentage"] for p in pulls)
                rows += (f"<tr><td class='muted'>{esc(diff)}</td><td>{esc(name)}</td>"
                         f"<td data-sort='9999999999999'><span class='tag warn'>in progress</span> best {best:.1f}% left</td>"
                         f"<td>{len(pulls)} so far</td><td>{len(nights_here)} so far</td><td>last pulled {esc(pulls[-1]['night'])}</td></tr>")
        total = len(bosses)
        cum, ys, hover = 0, [], []
        for n in nights_all:
            cum += len(first_kills.get(n, []))
            ys.append(cum)
            hover.append(f"{n}<br>{cum} of {total} {diff} bosses killed at least once"
                         + ("<br>first kills: " + ", ".join(first_kills[n]) if first_kills.get(n) else ""))
        i = len(fig.data)
        fig.add_trace(go.Scatter(x=[n[4:] for n in nights_all], y=ys, mode="lines+markers+text", name=diff,
                                 line=dict(shape="hv", dash=LINE_DASHES[i % len(LINE_DASHES)]),
                                 marker=dict(symbol=MARKERS[i % len(MARKERS)], size=9),
                                 text=[diff if j == len(ys) - 1 else "" for j in range(len(ys))], textposition="middle right",
                                 hovertext=hover, hoverinfo="text"))
    max_total = max(len(b) for b in by_diff.values())
    fig.update_layout(title="Bosses killed at least once, by raid night (first kills, per difficulty)",
                      yaxis=dict(title="Bosses down", range=[0, max_total + 0.6], dtick=1), xaxis=dict(title="Raid night"),
                      legend=dict(orientation="h", y=1.08, x=0), margin=dict(l=45, r=60, t=80, b=45))
    return (fig_html(fig, height=320)
            + "<details><summary class='muted'>First kill per boss and difficulty (table)</summary>"
            + table([("Difficulty", "str"), ("Boss", "str"), ("First kill", "num"), ("Pulls to first kill", "num"),
                     ("Nights to first kill", "num"), ("Since", "str")], rows, caption="First kill per boss and difficulty")
            + "</details>"
            + "<p class='muted'>Progression measured by first kills: how many bosses of each difficulty had gone down at least once by the end of "
              "each night, and what the first kill of each boss cost. Bosses are in zone order.</p>")


def _night_score(pulls: list[dict]) -> float:
    """A night's progress on a boss: median of its 3 best pulls (damps the single lucky pull)."""
    best3 = sorted(p["boss_percentage"] for p in pulls)[:3]
    return median(best3)


def insights(bosses: dict, ordered: list, avoidable_cfg: dict, mode: str = "anonymous") -> list[tuple[str, str, str]]:
    """
    Rule-based callouts: (severity, title, text). severity: 'good' | 'warn' | 'info'.

    mode controls whether individual players are named on the Home page:
      'named'     - names in the outlier / attendance / M+ cards (a private build for the raid lead)
      'anonymous' - same facts, no names; the tables further in still have everything (default)
      'off'       - no callouts about individuals at all
    """
    out = []
    named = mode == "named"
    people = mode != "off"
    pulls_all = all_pulls(bosses)
    if not pulls_all:
        return out
    tab_of = {key: f"tab{i}" for i, (key, _) in enumerate(ordered)}

    # --- progression boss: the unkilled boss with the most pulls
    unkilled = [(key, pulls) for key, pulls in ordered if pulls and not any(p["kill"] for p in pulls)]
    prog_key, prog_pulls = (max(unkilled, key=lambda kv: len(kv[1])) if unkilled else (None, None))
    if prog_key:
        name = prog_key[0]
        nights = []
        for p in prog_pulls:
            if p["night"] not in nights:
                nights.append(p["night"])
        by_night = {n: [p for p in prog_pulls if p["night"] == n] for n in nights}
        best = min(p["boss_percentage"] for p in prog_pulls)
        txt = f"{len(prog_pulls)} pulls over {len(nights)} night{'s' if len(nights) != 1 else ''}, best {best:.1f}% left."
        if len(nights) >= 2:
            a, b2 = _night_score(by_night[nights[-2]]), _night_score(by_night[nights[-1]])
            txt += (f" Last night's typical good pull {b2:.1f}% vs {a:.1f}% the night before (median of the 3 best pulls each night)"
                    + (" - progress." if b2 < a - 2 else " - no real movement." if abs(b2 - a) <= 2 else " - a step back."))
        # phases in the order they occur in the fight; how many pulls reached the deepest one seen
        order: list[str] = []
        reached = Counter()
        for p in prog_pulls:
            for ph, _ in (p.get("phase_timeline") or []):
                if ph not in order:
                    order.append(ph)
            for ph, _ in (p.get("phase_timeline") or [])[1:]:
                reached[ph] += 1
        if reached:
            deepest = [ph for ph in order if ph in reached][-1]
            txt += f" {reached[deepest]} of {len(prog_pulls)} pulls reached {esc(deepest)}."
        out.append(("info", f"Progression: {name}", txt + " " + gotab(tab_of[prog_key], "open tab &rarr;")))

        # wipe-starters on the prog boss
        firsts = [p["deaths"][0] for p in prog_pulls if p["deaths"]]
        if firsts:
            by_c = Counter(d.get("top_contributor", d["ability"]) for d in firsts)
            ab, n_ab = by_c.most_common(1)[0]
            out.append(("info", "What starts the wipes", f"{esc(ab)} caused {n_ab} of {len(firsts)} first deaths ({n_ab / len(firsts) * 100:.0f}%)."))
            with_casts = [d for d in firsts if d.get("has_cast_data")]
            if len(with_casts) >= 5:
                no_def = sum(1 for d in with_casts if not d.get("defensives"))
                out.append(("info" if no_def / len(with_casts) < 0.5 else "warn",
                            f"{no_def / len(with_casts) * 100:.0f}% of first deaths had no defensive cast in the last seconds",
                            f"{no_def} of {len(with_casts)} first deaths on {esc(name)} show no personal defensive, healthstone or potion "
                            f"in the death window. The Deaths tables list what was cast."))
            stats = player_stats(prog_pulls)
            regs = regulars(prog_pulls)
            rates = {n: s["first_deaths"] / max(s["pulls"], 1) for n, s in stats.items() if n in regs}
            if len(rates) >= 5:
                med = median(list(rates.values()))
                worst_name, worst_rate = max(rates.items(), key=lambda kv: kv[1])
                if people and worst_rate >= max(0.15, 2.5 * med) and stats[worst_name]["first_deaths"] >= 4:
                    cause = stats[worst_name]["causes"].most_common(1)[0][0] if stats[worst_name]["causes"] else "?"
                    who = esc(worst_name) if named else "One regular"
                    out.append(("warn", f"{who} starts the wipe in {worst_rate * 100:.0f}% of pulls",
                                f"{stats[worst_name]['first_deaths']} of {stats[worst_name]['pulls']} pulls, mostly to {esc(cause)}. "
                                f"Raid median is {med * 100:.0f}%. "
                                + ("" if named else f"Players table on {esc(name)}, sorted by 'started the wipe'. ")
                                + "Worth a quiet look at what they were doing at the time - it may be an assignment, not a mistake."))
        # avoidable offender
        avoidable = avoidable_set(avoidable_cfg, name)
        if avoidable:
            hits: Counter = Counter()
            pulls_of: Counter = Counter()
            for p in prog_pulls:
                for pl in p["participants"]:
                    pulls_of[pl] += 1
                for d in p["damage_taken"]:
                    if normalize(d["ability"]) in avoidable:
                        hits[d["player"]] += d["hits"]
            roles = player_roles(prog_pulls)
            rates = {n: hits[n] / pulls_of[n] for n in pulls_of if pulls_of[n] >= 0.5 * len(prog_pulls) and roles.get(n) != "tank"}
            if len(rates) >= 5:
                med = median(list(rates.values()))
                worst_name, worst_rate = max(rates.items(), key=lambda kv: kv[1])
                if people and med > 0 and worst_rate >= 2 * med and worst_rate >= 1:
                    who = esc(worst_name) if named else "One non-tank"
                    out.append(("warn", f"{who} takes {worst_rate:.1f} avoidable hits per pull",
                                f"Non-tank median is {med:.1f}. Damage taken heatmap on {esc(name)}."))
        # preparation
        prepared = [(pl, c) for p in prog_pulls for pl, c in (p.get("consumables") or {}).items()]
        if prepared:
            miss = Counter()
            for pl, c in prepared:
                for cat in ("flask", "food"):
                    if cat in c and not c[cat]:
                        miss[cat] += 1
            share = sum(miss.values()) / (2 * len(prepared))
            if share > 0.05:
                out.append(("warn", f"{share * 100:.0f}% of player-pulls on {esc(name)} started without flask or food",
                            f"Missing flask on {miss['flask']} and food on {miss['food']} of {len(prepared)} player-pulls. Preparation table on the boss tab."))
    elif any(pulls for _, pulls in ordered):
        out.append(("good", "Full clear", "Every boss in the selection has been killed. Farm kill times are on the Raid tab."))

    # --- last night: efficiency
    nights: dict[str, list[dict]] = defaultdict(list)
    for p in pulls_all:
        nights[p["night"]].append(p)
    last_night = max(nights, key=lambda n: nights[n][0]["absolute_start_ms"])
    ps = nights[last_night]
    combat = sum(p["duration_seconds"] for p in ps)
    n_start, n_end = ps[0]["absolute_start_ms"], ps[-1]["absolute_start_ms"] + ps[-1]["duration_seconds"] * 1000
    span = (n_end - n_start) / 1000
    trash = sum((e - a) / 1000 for a, e, is_boss in NIGHT_FIGHTS.get(last_night, []) if not is_boss and a >= n_start and e <= n_end)
    idle_share = max(span - combat - trash, 0) / span if span else 0
    if span > 3600 and idle_share > 0.5:
        out.append(("warn", f"Last night was {idle_share * 100:.0f}% idle",
                    f"{fmt_duration(combat)} on bosses and {fmt_duration(trash)} on trash in {fmt_duration(span)} of raid. Run-backs, breaks and explanations were the rest. Raid tab &rarr; Night report."))
    elif span > 3600:
        out.append(("good", f"Last night: {(1 - idle_share) * 100:.0f}% of raid time fighting", f"{len(ps)} pulls, {fmt_duration(combat)} on bosses, {fmt_duration(trash)} on trash, in {fmt_duration(span)}."))

    # --- attendance: regulars who missed the last main night
    main_nights = [n for n in nights if not n.endswith(" open")]
    if main_nights:
        last_main = max(main_nights, key=lambda n: nights[n][0]["absolute_start_ms"])
        regs = regulars([p for p in pulls_all if not p["night"].endswith(" open")])
        present = {name for p in nights[last_main] for name in p["participants"]}
        missing = sorted(regs - present)
        if missing and people:
            out.append(("info", f"{len(missing)} regular{'s' if len(missing) != 1 else ''} missing on {last_main[4:]}",
                        ", ".join(esc(m) for m in missing) if named else "Raid tab &rarr; Attendance."))

    # --- avoidable list review flags
    flagged = []
    for (name, diff), pulls in ordered:
        avoidable = avoidable_set(avoidable_cfg, name)
        if not avoidable or not pulls:
            continue
        regs = regulars(pulls)
        pulls_of = Counter(pl for p in pulls for pl in p["participants"])
        hits_by: dict[str, Counter] = defaultdict(Counter)
        for p in pulls:
            for d in p["damage_taken"]:
                if normalize(d["ability"]) in avoidable:
                    hits_by[d["ability"]][d["player"]] += d["hits"]
        for ab, c in hits_by.items():
            rates = [c[pl] / pulls_of[pl] for pl in regs if pulls_of[pl]]
            if len(rates) < 5:
                continue
            mean = sum(rates) / len(rates)
            cv = (sum((r - mean) ** 2 for r in rates) / len(rates)) ** 0.5 / mean if mean else 0
            share = sum(1 for r in rates if r) / len(rates)
            if cv < 0.3 and share >= 0.8 and mean >= 0.5:
                flagged.append(f"{ab} ({name} {diff})")
    if flagged:
        out.append(("info", f"{len(flagged)} avoidable-listed abilit{'y' if len(flagged) == 1 else 'ies'} hit the raid like unavoidable damage",
                    ", ".join(esc(f) for f in flagged[:6]) + (" &hellip;" if len(flagged) > 6 else "") + ". Keep them only if they are fail-triggered raid damage."))

    # --- M+ requirement
    if os.path.exists(MPLUS_FILE):
        try:
            from mplus import weeks_in_history, week_summary, requirement, hours_since_reset
            with open(MPLUS_FILE, encoding="utf-8") as f:
                hist = json.load(f)
            players = hist.get("players") or {}
            if players:
                cur = weeks_in_history(hist, 1)[0]
                req = requirement()
                met = [p.get("name", k) for k, p in players.items() if week_summary([r for r in p["runs"].values() if r["week"] == cur])["met"]]
                missing = sorted(p.get("name", k) for k, p in players.items() if p.get("name", k) not in met)
                fresh = hours_since_reset() < 48
                sev = "good" if len(met) == len(players) else "info" if fresh else "warn" if len(met) < 0.75 * len(players) else "info"
                detail = ("Everyone is done." if not missing else
                          ("Missing: " + ", ".join(esc(m) for m in missing[:12]) + (" &hellip;" if len(missing) > 12 else "")) if named else
                          "Mythic+ tab has the list.")
                if fresh and missing:
                    detail = f"The week reset {hours_since_reset():.0f} h ago - too early to judge. " + detail
                out.append((sev, f"Mythic+: {len(met)} of {len(players)} have done {req['runs']} x +{req['level']} this week", detail))
        except Exception:
            pass
    return out


def _delta(cur: float, prev: float | None, fmt, lower_is_better: bool = False, unit: str = "") -> str:
    """'▲ +12% vs previous night' style sub-line; colour and glyph agree with the text so colour is never the only signal."""
    if prev is None:
        return "<span class='vs'>first night in range</span>"
    diff = cur - prev
    if abs(diff) < 1e-9:
        return "<span class='vs'>same as previous night</span>"
    better = (diff < 0) if lower_is_better else (diff > 0)
    glyph = "&#9650;" if diff > 0 else "&#9660;"
    return (f"<span class='vs' style='color:{'#8ce0a8' if better else '#e08a8a'}'>{glyph} {'+' if diff > 0 else ''}{fmt(diff)}{unit} "
            f"vs previous night ({fmt(prev)}{unit}) - {'better' if better else 'worse'}</span>")


def last_night_panel(bosses: dict, ordered: list) -> str:
    pulls_all = all_pulls(bosses)
    nights: dict[str, list[dict]] = defaultdict(list)
    for p in pulls_all:
        nights[p["night"]].append(p)
    ordered_nights = sorted(nights, key=lambda n: nights[n][0]["absolute_start_ms"])
    last = ordered_nights[-1]
    prev = ordered_nights[-2] if len(ordered_nights) > 1 else None
    ps = nights[last]
    cur = night_stats(last, ps)
    before = night_stats(prev, nights[prev]) if prev else None
    combat = cur["combat"]
    span = cur["span"]
    per_boss = Counter(p["boss"] for p in ps)
    kills = Counter(p["boss"] for p in ps if p["kill"])
    tab_of = {f"{k[0]} ({k[1]})": f"tab{i}" for i, (k, _) in enumerate(ordered)}
    rows = ""
    for bn, n in per_boss.most_common():
        bp = [p for p in ps if p["boss"] == bn]
        best = "KILL" if kills[bn] else f"{min(p['boss_percentage'] for p in bp):.1f}%"
        firsts = [p["deaths"][0] for p in bp if p["deaths"]]
        starter = Counter(d.get("top_contributor", d["ability"]) for d in firsts).most_common(1)[0][0] if firsts else "-"
        rows += (f"<tr><td>{gotab(tab_of.get(bn, ''), esc(bn.split(' (')[0]))}</td><td>{n}</td>"
                 f"<td>{kills[bn]}</td><td>{esc(best)}</td><td>{fmt_duration(sum(p['duration_seconds'] for p in bp))}</td><td>{esc(starter)}</td></tr>")
    players = {name for p in ps for name in p["participants"]}
    bench = sorted(set(NIGHT_PLAYERS.get(last, {})) - players)
    pct = lambda x: f"{x * 100:.0f}"
    kpis = [
        ("Night", f"<span class='card-text'>{esc(last)}</span>"), ("Pulls", str(len(ps))), ("Kills", str(sum(kills.values()))),
        ("In combat", esc(fmt_duration(combat))), ("Raid time", esc(fmt_duration(span))),
        ("Pulls / hour", f"{cur['pph']:.1f}" + _delta(cur["pph"], before["pph"] if before else None, lambda v: f"{v:.1f}")),
        ("Idle share", f"{pct(cur['idle_share'])}%" + _delta(cur["idle_share"] * 100, before["idle_share"] * 100 if before else None,
                                                             lambda v: f"{v:.0f}", lower_is_better=True, unit="%")),
        ("Players in pulls", f"{len(players)}" + (f"<span class='vs'>{len(bench)} more in the raid but in no boss pull (Raid tab)</span>" if bench else "")),
    ]
    prep = cur.get("prep")
    if prep is not None:
        kpis.append(("Flask + food at pull start", f"{pct(prep)}%" + _delta(prep * 100, before["prep"] * 100 if before and before.get("prep") is not None else None,
                                                                          lambda v: f"{v:.0f}", unit="%")))
    cards_html = "<div class='cards'>" + "".join(
        f"<div class='card'><div class='card-value'>{v}</div><div class='card-label'>{esc(l)}</div></div>" for l, v in kpis) + "</div>"
    return f"""
    {cards_html}
    {table([("Boss", "str"), ("Pulls", "num"), ("Kills", "num"), ("Best", "str"), ("In combat", "str"), ("Top wipe-starter", "str")], rows, caption="Last raid night per boss")}
    """


def home_section(bosses: dict, ordered: list, avoidable_cfg: dict, mode: str, heading: str | None) -> str:
    pulls_all = all_pulls(bosses)
    if not pulls_all:
        return ""
    nights = {p["night"] for p in pulls_all}
    killed = sum(1 for _, pulls in ordered if pulls and any(p["kill"] for p in pulls))
    seen = sum(1 for _, pulls in ordered if pulls)
    cards_html = cards([("Bosses killed", f"{killed} / {seen}"), ("Raid nights", len(nights)), ("Pulls", len(pulls_all)),
                        ("Time in combat", fmt_duration(sum(p["duration_seconds"] for p in pulls_all))),
                        ("Players seen", len({n for p in pulls_all for n in p["participants"]}))])
    items = insights(bosses, ordered, avoidable_cfg, mode)
    ins = "".join(f"<div class='insight {sev}'><span class='ins-badge {sev}'>{SEVERITY_LABEL.get(sev, sev)}</span>"
                  f"<div class='ins-title'>{title}</div><div class='ins-text'>{text}</div></div>" for sev, title, text in items)
    head = f"<h2 class='home-type'>{esc(heading)}</h2>" if heading else ""
    sub = "h3" if heading else "h2"
    return f"""
    {head}
    {cards_html}
    <{sub}>Progress</{sub}>
    {progress_strip(ordered)}
    <{sub}>Progression by first kills</{sub}>
    {progression_timeline(ordered)}
    <{sub}>Worth a look</{sub}>
    <div class='insights'>{ins or "<p class='muted'>Nothing stands out.</p>"}</div>
    <{sub}>Last raid night</{sub}>
    {last_night_panel(bosses, ordered)}
    """


def home_tab(bosses: dict, ordered: list, avoidable_cfg: dict, args) -> str:
    pulls_all = all_pulls(bosses)
    if not pulls_all:
        return "<p class='muted'>No pulls.</p>"
    guild = os.getenv("GUILD_NAME", "Guild")
    mode = getattr(args, "callouts", None) or os.getenv("HOME_CALLOUTS", "anonymous")
    types = []
    for p in pulls_all:
        t = p.get("night_type", "main")
        if t not in types:
            types.append(t)
    types.sort(key=lambda t: 0 if t == "main" else 1)
    intro = (f"<p class='muted'>Progress boxes open the boss tab. \"Worth a look\" cards are computed from the data with fixed thresholds - "
             f"not opinions, and not a grading. "
             + ("Individuals are named on this page (private build)." if mode == "named" else
                "No individuals are named on this page; the tables inside have the per-player detail." if mode == "anonymous" else
                "Cards about individuals are switched off.") + "</p>")
    if len(types) == 1:
        body = home_section(bosses, ordered, avoidable_cfg, mode, None)
    else:
        labels = {"main": "Main raid nights", "open": "Open nights"}
        body = ""
        for t in types:
            fb = filter_bosses_by_type(bosses, t)
            f_ordered = [(key, [p for p in pulls if p.get("night_type", "main") == t]) for key, pulls in ordered]
            body += home_section(fb, f_ordered, avoidable_cfg, mode, labels[t])
    return f"""
    <h1>{esc(guild)} <span class='diff'>{esc(args.start)} to {esc(args.end)}</span></h1>
    {intro}
    {body}
    <p class='muted'>Use the pickers at the top to look at another night or a single player; the <b>Raid</b> tab{"s have" if len(types) > 1 else " has"} every night side by side.</p>
    """
