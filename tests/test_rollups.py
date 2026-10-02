"""Players tab Phase 1 T8: public team strip (no names), alphabetical roster, named Raid-lead rollups, Home prep insight."""

import copy
import re
from types import SimpleNamespace

from dash.page import build_html
from dash.rollups import prep_rates, night_series, LEVEL_ORDER

ROSTER_CAPTION = "<caption>Players across all bosses</caption>"


def _args(**kw):
    base = dict(start="2026-09-09", end="2026-09-09", difficulty=["normal", "heroic", "mythic"], zone=None, boss=None,
                player=None, progression_only=False, callouts="anonymous", nights="all", reports=None, uncompressed=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _players_static(html: str) -> str:
    return html.split("<div class='static' id='static_tabPlayers'>")[1].split("<div class='pull-detail' id='detail_tabPlayers'")[0]


def _home(html: str) -> str:
    return html.split("<section id='tabHome'")[1].split("</section>")[0]


def _table_with_caption(html: str, caption: str) -> str:
    start = html.index(caption)
    start = html.rindex("<table", 0, start)
    return html[start:html.index("</table>", start) + len("</table>")]


def _names(bosses) -> set:
    return {n for ps in bosses.values() for p in ps for n in p["participants"]}


def _leaked(html_part: str, names: set) -> list:
    text = re.sub(r"<[^>]+>", " ", html_part)
    return sorted(n for n in names if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text))


def _row_names(table_html: str) -> list[str]:
    return re.findall(r"<tr[^>]*><td><span class='player [^']*'>([^<]+)</span>", table_html)


def test_public_players_tab_names_only_in_roster_rows(bosses):
    static = _players_static(build_html(bosses, _args(callouts="anonymous")))
    names = _names(bosses)
    roster = _table_with_caption(static, ROSTER_CAPTION)
    assert set(_row_names(roster)) == names
    outside = static.replace(roster, "")
    assert not _leaked(outside, names), _leaked(outside, names)
    assert "Raid lead" not in static and "raid_lead" not in static
    # the strip: anonymous KPI tiles + the pointer to the toolbar
    assert "<h2>Team</h2>" in static and "pick your name in the toolbar to see your card" in static
    strip = static.split("<h2>Team</h2>")[1].split("<h2>Roster</h2>")[0]
    for label in ("Flask + food at pull start", "Avoidable hits / min alive (non-tanks)", "First deaths with no defensive",
                  "Raid interrupts per pull"):
        assert f"<dt>{label}</dt>" in strip, label
    assert "first night in range" in strip      # single fixture night -> no previous night


def test_off_mode_is_public_too(bosses):
    static = _players_static(build_html(bosses, _args(callouts="off")))
    assert "Raid lead" not in static
    assert not _leaked(static.replace(_table_with_caption(static, ROSTER_CAPTION), ""), _names(bosses))


def test_public_roster_alphabetical(bosses):
    static = _players_static(build_html(bosses, _args(callouts="anonymous")))
    rows = _row_names(_table_with_caption(static, ROSTER_CAPTION))
    assert rows == sorted(rows, key=str.lower)
    assert "sorted by name" in static


def test_named_build_raid_lead_sections(bosses):
    static = _players_static(build_html(bosses, _args(callouts="named")))
    assert "<h2 id='raid_lead'>Raid lead</h2>" in static
    lead = static.split("<h2 id='raid_lead'>Raid lead</h2>")[1]
    for h in ("Who needs help with what", "Preparation misses", "Avoidable damage", "First deaths without a defensive",
              "Interrupts", "Tanks side by side", "Gear readiness"):
        assert f"<h3>{h}</h3>" in lead, h
    # named roster keeps the first-death sort (fixture: 3 players with one first death each come first)
    roster = _row_names(_table_with_caption(static, ROSTER_CAPTION))
    assert roster[:3] and set(roster[:3]) == {"Maevrin", "Maxiumus", "Totemdave"}


def test_named_r1_rows_sorted_by_level_then_score(bosses):
    static = _players_static(build_html(bosses, _args(callouts="named")))
    r1 = _table_with_caption(static, "<caption>Raiders by most urgent item</caption>")
    keys = [(LEVEL_ORDER[lvl], -float(score)) for lvl, score in re.findall(r"<tr[^>]*? data-level='(\w+)' data-score='([\d.]+)'>", r1)]
    assert len(keys) == len(_names(bosses))          # one row per raider
    assert keys == sorted(keys)
    assert " vs " in r1 and "(role median)" in r1   # value + baseline shown


def test_named_r8_tanks_and_r9_ilvl(bosses):
    static = _players_static(build_html(bosses, _args(callouts="named")))
    r8 = _table_with_caption(static, "<caption>Tank metrics per night</caption>")
    heads = re.findall(r"aria-label='Sort by ([^']+)'", r8)
    assert "Ixavior" in heads and "Airohdh" in heads
    for metric in ("Active mitigation % of hits", "Active mitigation % of damage", "Mitigated %", "Damage taken / s alive (k)"):
        assert f"<td>{metric}</td>" in r8, metric
    r9 = static.split("<h3>Gear readiness</h3>")[1]
    assert "<dt>Lowest item level</dt><dd>312</dd>" in r9 and "<dt>Highest item level</dt><dd>318</dd>" in r9
    assert "<dt>Median item level</dt>" in r9
    gaps = _table_with_caption(r9, "<caption>Players with gear gaps on their latest pull</caption>")
    assert "Ixavior" in gaps and "ilvl below your average" in gaps


def test_home_prep_insight_anonymous(bosses):
    for mode in ("anonymous", "named"):
        home = _home(build_html(bosses, _args(callouts=mode)))
        m = re.search(r"<article class='insight (good|warn|info)'><h4><span class='badge'>\w+</span>Preparation: (\d+)% flask and food</h4><p>(.*?)</p>",
                      home)
        assert m, mode
        assert "player-pulls" in m.group(3) and "with a rune" in m.group(3)
    home = _home(build_html(bosses, _args(callouts="anonymous")))
    assert not _leaked(home, _names(bosses))


def test_players_headings_never_skip(bosses):
    for mode in ("anonymous", "named"):
        html = build_html(bosses, _args(callouts=mode))
        panel = re.search(r"<section id='tabPlayers' class='tab-panel.*?</section>", html, flags=re.S).group(0)
        levels = [int(x) for x in re.findall(r"<h([1-6])", panel)]
        assert levels and levels[0] == 1 and max(levels) <= 3, (mode, levels)
        assert all(b <= a + 1 for a, b in zip(levels, levels[1:])), (mode, levels)


def test_named_build_size(bosses):
    assert len(build_html(bosses, _args(callouts="named")).encode("utf-8")) < 1_500_000


def test_strip_compares_with_previous_night(bosses):
    two = copy.deepcopy(bosses)
    pulls = sorted((p for ps in two.values() for p in ps), key=lambda p: p["absolute_start_ms"])
    for p in pulls[:2]:
        p["night"] = "Mon 2026-09-07 open"
    series = night_series(two, None)
    assert [s["night"] for s in series] == ["Mon 2026-09-07 open", pulls[-1]["night"]]
    static = _players_static(build_html(two, _args(callouts="anonymous")))
    strip = static.split("<h2>Team</h2>")[1].split("<h2>Roster</h2>")[0]
    assert "vs previous night" in strip or "same as previous night" in strip


def test_prep_rates_synthetic():
    pulls = [{"consumables": {"a": {"flask": True, "food": True, "rune": False}, "b": {"flask": False, "food": True, "rune": True}}},
             {"consumables": {"a": {"flask": True, "food": True}}}, {"consumables": {}}]
    r = prep_rates(pulls)
    assert r["n"] == 3 and abs(r["ff"] - 2 / 3) < 1e-9 and r["rune"] == 0.5
    assert prep_rates([{"consumables": {}}]) is None
