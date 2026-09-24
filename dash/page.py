"""Page assembly: header, toolbar, tab bar, one section per tab, static CSS + JS."""

import os
from collections import Counter
from datetime import datetime

from collect_data import normalize, zone_encounter_order
from .common import esc, json_for_script, load_avoidable, player_role_labels, PLOTLY_CDN
from .payload import pull_grid, pull_payload
from .home import home_tab
from .raid import raid_tab
from .players import players_tab
from .mplus_tab import mplus_tab

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def static_file(name: str) -> str:
    with open(os.path.join(STATIC_DIR, name), encoding="utf-8") as f:
        return f.read()


def boss_tab(pulls: list[dict], boss_name: str, difficulty: str, avoidable_cfg: dict, tab_id: str, compress: bool) -> str:
    mime, text = pull_payload(pulls, boss_name, difficulty, avoidable_cfg, compress=compress)
    return f"""
    <script type='{mime}' id='data_{tab_id}'>{text}</script>
    <h2>Pulls</h2>
    {pull_grid(pulls, tab_id)}
    """


DIFFICULTY_RANK = {"Lfr": 0, "Normal": 1, "Heroic": 2, "Mythic": 3}


def boss_order_key(bosses: dict):
    """
    Tabs sorted by difficulty (Normal -> Heroic -> Mythic), then by the zone's
    boss order from WCL (first boss -> last boss). BOSS_ORDER in .env puts named
    bosses first, in the order given (e.g. a rare/world boss that WCL lists last).
    """
    forced = [normalize(x) for x in os.getenv("BOSS_ORDER", "").split(",") if x.strip()]
    zone_ids = {p.get("zone_id") for pulls in bosses.values() for p in pulls if p.get("zone_id")}
    enc_pos: dict = {}
    for zid in zone_ids:
        enc_pos.update(zone_encounter_order(zid))

    def key(item):
        (name, diff), pulls = item
        n = normalize(name)
        forced_pos = forced.index(n) if n in forced else len(forced)
        enc_ids = [p.get("encounter_id") for p in pulls if p.get("encounter_id")]
        zone_pos = min((enc_pos.get(e, 10_000 + e) for e in enc_ids), default=10_000)
        return (DIFFICULTY_RANK.get(diff, 9), forced_pos, zone_pos, pulls[0]["absolute_start_ms"])
    return key


def _tab_button(tab_id: str, label_html: str, extra_class: str = "", active: bool = False, attrs: str = "") -> str:
    return (f"<button type='button' role='tab' id='btn_{tab_id}' class='tab-btn {extra_class}{' active' if active else ''}' "
            f"data-tab='{tab_id}' aria-selected='{'true' if active else 'false'}' aria-controls='{tab_id}' "
            f"tabindex='{'0' if active else '-1'}'{attrs}>{label_html}</button>")


def _tab_panel(tab_id: str, body: str, active: bool = False) -> str:
    return (f"<section id='{tab_id}' class='tab-panel{' active' if active else ''}' role='tabpanel' "
            f"aria-labelledby='btn_{tab_id}'{'' if active else ' hidden'}>{body}</section>")


def build_html(bosses: dict, args) -> str:
    ordered = sorted(bosses.items(), key=boss_order_key(bosses))
    avoidable_cfg = load_avoidable()
    compress = not getattr(args, "uncompressed", False)

    tab_buttons = _tab_button("tabHome", "Home", "home", active=True)
    tab_panels = _tab_panel("tabHome", home_tab(bosses, ordered, avoidable_cfg, args), active=True)
    diffs_present: list[str] = []
    for i, ((name, diff), pulls) in enumerate(ordered):
        tab_id = f"tab{i}"
        kills = sum(1 for p in pulls if p["kill"])
        badge = "✓" if kills else f"{min(p['boss_percentage'] for p in pulls):.0f}%"
        if diff not in diffs_present:
            diffs_present.append(diff)
        tab_buttons += _tab_button(tab_id, f"{esc(name)} <span class='diff'>{esc(diff)}</span> <span class='badge'>{esc(badge)}</span>",
                                   extra_class="boss", attrs=f" data-diff='{esc(diff)}'")
        tab_panels += _tab_panel(tab_id, f"<h1>{esc(name)} <span class='diff'>{esc(diff)}</span></h1>"
                                         + boss_tab(pulls, name, diff, avoidable_cfg, tab_id, compress))
    # difficulty segment: one row of boss tabs at a time when several difficulties are present
    diffbar = ""
    if len(diffs_present) > 1:
        diffbar = ("<div class='diffbar' role='group' aria-label='Show boss tabs for difficulty'><span class='muted'>Boss tabs:</span>"
                   + "".join(f"<button type='button' class='chip diffbtn' data-diff='{esc(d)}' aria-pressed='false'>{esc(d)}</button>" for d in diffs_present)
                   + "<button type='button' class='chip diffbtn' data-diff='all' aria-pressed='false'>All</button></div>")

    types_present = []
    for pulls in bosses.values():
        for p in pulls:
            t = p.get("night_type", "main")
            if t not in types_present:
                types_present.append(t)
    types_present.sort(key=lambda t: 0 if t == "main" else 1)
    if len(types_present) > 1:
        for t in types_present:
            tab_buttons += _tab_button(f"tabRaid_{t}", f"Raid <span class='diff'>{t}</span>", "players" if t == "main" else "")
            tab_panels += _tab_panel(f"tabRaid_{t}", raid_tab(bosses, t))
    else:
        tab_buttons += _tab_button("tabRaid", "Raid", "players")
        tab_panels += _tab_panel("tabRaid", raid_tab(bosses))
    tab_buttons += _tab_button("tabPlayers", "Players")
    tab_panels += _tab_panel("tabPlayers", f"<div class='static' id='static_tabPlayers'>{players_tab(bosses, avoidable_cfg)}</div>"
                                           f"<div class='pull-detail' id='detail_tabPlayers' aria-live='polite'></div>")

    # global filters: every raid night and every player across all bosses
    night_first: dict[str, int] = {}
    player_counts: Counter = Counter()
    player_class: dict[str, str] = {}
    pulls_all = [p for pulls in bosses.values() for p in pulls]
    for p in pulls_all:
        night_first[p["night"]] = min(night_first.get(p["night"], p["absolute_start_ms"]), p["absolute_start_ms"])
        for name, cls in p["participants"].items():
            player_counts[name] += 1
            player_class[name] = cls
    nights_sorted = sorted(night_first, key=night_first.get)
    role_labels = player_role_labels(pulls_all)
    night_opts = "".join(f"<option value='{esc(n)}'>{esc(n)} ({sum(1 for p in pulls_all if p['night'] == n)} pulls)</option>" for n in nights_sorted)
    player_opts = "".join(f"<option value='{esc(n)}' class='{esc(player_class[n])}'>{esc(n)} - {esc(role_labels.get(n, ''))} ({c} pulls)</option>"
                          for n, c in player_counts.most_common())
    tab_names = {f"tab{i}": f"{name} ({diff})" for i, ((name, diff), _) in enumerate(ordered)}
    n_open = len({p["night"] for p in pulls_all if p.get("night_type") == "open"})
    n_main = len(nights_sorted) - n_open
    type_sel = (f"<label>Nights <select id='gType'><option value=''>Main + open ({len(nights_sorted)})</option>"
                f"<option value='main'>Main only ({n_main})</option><option value='open'>Open only ({n_open})</option></select></label>") if n_open else \
               "<select id='gType' hidden aria-hidden='true'><option value=''></option></select>"
    toolbar = f"""
<div class='toolbar' role='region' aria-label='Global filters'>
  {type_sel}
  <label>Raid night <select id='gNight'><option value=''>All nights ({len(nights_sorted)})</option>{night_opts}</select></label>
  <label>Player <select id='gPlayer'><option value=''>All players ({len(player_counts)})</option>{player_opts}</select></label>
  <button type='button' id='gClear' class='chip'>clear filters</button>
  <label class='filter' style='margin:0'><input type='checkbox' id='gWide'> wide layout</label>
  <span class='muted chip-hint'>filters apply to every boss tab and the Players tab &middot; click pulls inside a tab to narrow further</span>
</div>
<script type='application/json' id='tab_names'>{json_for_script(tab_names)}</script>"""
    mplus_html = mplus_tab()
    if mplus_html:
        tab_buttons += _tab_button("tabMplus", "Mythic+")
        tab_panels += _tab_panel("tabMplus", mplus_html)

    guild = os.getenv("GUILD_NAME", "Guild")
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    filters = [f"{args.start} to {args.end}", "/".join(d.capitalize() for d in args.difficulty)]
    if args.zone: filters.append(f"zone: {args.zone}")
    if args.boss: filters.append(f"boss: {args.boss}")
    if args.player: filters.append(f"player: {args.player}")
    if args.progression_only: filters.append("progression pulls only")
    if getattr(args, "nights", "all") != "all": filters.append(f"{args.nights} nights only")
    if getattr(args, "reports", None): filters.append(f"{len(args.reports)} listed report{'s' if len(args.reports) != 1 else ''}")
    zones = sorted({p["zone"] for pulls in bosses.values() for p in pulls if p.get("zone")})

    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{esc(guild)} - Raid dashboard {esc(args.start)} to {esc(args.end)}</title>
<script src='{PLOTLY_CDN}'></script>
<style>
{static_file("tokens.css")}
{static_file("dash.css")}
</style>
</head>
<body>
<a class='skip' href='#main'>Skip to content</a>
<header>
  <div class='title'>{esc(guild)} - Raid dashboard{(' - ' + esc(', '.join(zones))) if zones else ''}</div>
  <div class='sub'>{esc(' · '.join(filters))} &middot; generated {esc(generated)}</div>
</header>
{toolbar}
<div id='jsError' class='note' role='alert' hidden></div>
{diffbar}
<label class='tabselect-wrap'><span class='sr-only'>Go to tab</span><select id='tabSelect' aria-label='Go to tab'></select></label>
<nav class='tabs' role='tablist' aria-label='Dashboard tabs'>{tab_buttons}</nav>
<main id='main'>
{tab_panels}
</main>
<div id='oldBrowser' class='note' hidden>This dashboard needs a browser from 2023 or newer (Chrome 80+, Firefox 113+, Safari 16.4+) to decompress its data. Please update your browser.</div>
<script>
{static_file("dash.js")}
</script>
</body>
</html>"""
