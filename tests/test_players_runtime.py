"""Runtime smoke test of the Players tab: the whole inline dash.js of an offline `--uncompressed` fixture build runs
under quickjs against a small DOM stub (tests/domstub.js). Not a faithful browser - it catches ReferenceError /
TypeError in the dashboard's own code and checks the Players-tab render paths (unfiltered view, toolbar pick, deep link,
Show my card, click-your-name) end to end. Any exception reported to #jsError fails the test."""

import json
import os
import re
from types import SimpleNamespace

import pytest

from dash.page import build_html

HERE = os.path.dirname(os.path.abspath(__file__))

REPORT = r"""
(function () {
  const g = id => document.getElementById(id);
  const txt = el => el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
  const det = g('detail_tabPlayers'), stat = g('static_tabPlayers'), err = g('jsError'), panel = document.querySelector('.tab-panel.active');
  return JSON.stringify({
    jsError: txt(err), jsErrorHidden: err.hidden, activeTab: panel ? panel.id : null, hash: location.hash,
    gPlayer: g('gPlayer').value, dashReady: document.body.dataset.dashReady || null,
    staticHidden: stat.classList.contains('hidden'), staticH2: stat.querySelectorAll('h2').map(txt),
    rosterRows: stat.querySelectorAll('tr[data-player]').length, rosterNames: stat.querySelectorAll('.player').length,
    detailCls: det.className, h2: det.querySelectorAll('h2').map(txt), h3: det.querySelectorAll('h3').map(txt),
    hasCard: !!det.querySelector('.player-card'), cardTitle: txt(det.querySelector('.player-card .panel-title')),
    showMyCard: txt(det.querySelector('#showMyCard')), copyLink: !!det.querySelector('.copy-link'), close: !!det.querySelector('.close'),
    empties: det.querySelectorAll('.empty').map(txt),
  });
})()
"""

CARD_H3 = ["key numbers", "Per boss", "Consistency", "Deaths", "Preparation", "Gear"]


@pytest.fixture
def page(bosses):
    """(html, inline dash.js, toolbar player labels) of an uncompressed anonymous fixture build."""
    args = dict(start="2026-09-09", end="2026-09-09", difficulty=["normal", "heroic", "mythic"], zone=None, boss=None,
                player=None, progression_only=False, callouts="anonymous", nights="all", reports=None, uncompressed=True)
    html = build_html(bosses, SimpleNamespace(**args))
    scripts = [m.group(2) for m in re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S) if "dashShowError" in m.group(2)]
    assert len(scripts) == 1
    select = re.search(r"<select id='gPlayer'>.*?</select>", html, re.S).group(0)
    labels = re.findall(r"<option value='([^']+)'", select)
    assert len(labels) >= 10
    return html, scripts[0], labels


class Page:
    """One quickjs context: stub + parsed HTML + dash.js executed (promise jobs and timers drained)."""

    def __init__(self, quickjs, html, dashjs, pre_js=""):
        self.quickjs = quickjs
        ctx = self.ctx = quickjs.Context()
        ctx.set_memory_limit(1 << 30)
        ctx.set_max_stack_size(1 << 24)
        with open(os.path.join(HERE, "domstub.js"), encoding="utf-8") as f:
            ctx.eval(f.read())
        ctx.set("__HTML", html)
        if pre_js:
            ctx.eval(pre_js)
        ctx.eval("__buildDocument()")
        self.run(dashjs)

    def run(self, js):
        out = self.ctx.eval(js)
        for _ in range(10000):
            ran = False
            while self.ctx.execute_pending_job():
                ran = True
            if self.ctx.eval("__drainTimers(50)"):
                ran = True
            if not ran:
                break
        return out

    def report(self):
        return json.loads(self.ctx.eval(REPORT))

    def click(self, selector):
        out = self.run(f"(function(){{ const el = document.querySelector({json.dumps(selector)}); if (!el) return null;"
                       f" el.dispatchEvent(new MouseEvent('click', {{bubbles: true}})); return 'clicked'; }})()")
        assert out == "clicked", f"no element for {selector}"

    def select(self, sel_id, value):
        out = self.run(f"(function(){{ const s = document.getElementById({json.dumps(sel_id)}); s.value = {json.dumps(value)};"
                       f" s.dispatchEvent(new Event('change', {{bubbles: true}})); return s.value; }})()")
        assert out == value, f"{sel_id} did not accept {value!r} (got {out!r})"


def _clean(rep):
    assert rep["jsError"] == "", rep["jsError"]
    assert rep["jsErrorHidden"] is True


def _card_ok(rep, name):
    _clean(rep)
    assert rep["hasCard"] and rep["cardTitle"].startswith(name), rep
    assert rep["copyLink"] and rep["close"]
    assert rep["staticHidden"] is True
    assert rep["detailCls"] == "pull-detail open filtered"
    for word in CARD_H3:
        assert any(word in h for h in rep["h3"]), (word, rep["h3"])
    assert rep["h2"][1:] == ["Who pulls first", "All pulls"]
    assert not rep["empties"], rep["empties"]
    assert rep["hash"] == f"#tabPlayers?player={name}"


def test_load_and_unfiltered_players_tab(page):
    quickjs = pytest.importorskip("quickjs")
    html, dashjs, labels = page
    p = Page(quickjs, html, dashjs)
    rep = p.report()
    _clean(rep)
    assert rep["dashReady"] == "1" and rep["activeTab"] == "tabHome"
    # the static Python view: Team strip + Roster, every roster row clickable (data-player) with a .player name
    assert rep["staticH2"] == ["Team", "Roster"] and rep["staticHidden"] is False
    assert rep["rosterRows"] == rep["rosterNames"] == len(labels)
    p.click("#btn_tabPlayers")
    rep = p.report()
    _clean(rep)
    assert rep["activeTab"] == "tabPlayers" and rep["hash"] == "#tabPlayers"
    assert rep["detailCls"] == "pull-detail open" and rep["staticHidden"] is False
    assert rep["h2"] == ["Who pulls first", "All pulls"] and not rep["hasCard"]
    assert rep["showMyCard"] is None      # nothing stored yet


def test_toolbar_pick_renders_card_and_close_restores(page):
    quickjs = pytest.importorskip("quickjs")
    html, dashjs, labels = page
    p = Page(quickjs, html, dashjs)
    p.click("#btn_tabPlayers")
    p.select("gPlayer", labels[0])
    _card_ok(p.report(), labels[0])
    # a second pick re-renders for the other player
    p.select("gPlayer", labels[1])
    _card_ok(p.report(), labels[1])
    # the "show everything" button clears the filters: static view back, Show my card offered for the remembered name
    p.click("#detail_tabPlayers .close")
    rep = p.report()
    _clean(rep)
    assert not rep["hasCard"] and rep["staticHidden"] is False and rep["gPlayer"] == "" and rep["hash"] == "#tabPlayers"
    assert rep["showMyCard"] == f"Show my card ({labels[1]})"
    # Escape also clears; picking on Home first then opening Players renders the card once opened
    p.select("gPlayer", labels[2])
    p.click("#btn_tabHome")
    p.run("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    rep = p.report()
    _clean(rep)
    assert rep["gPlayer"] == ""


def test_deep_link_pre_selects_player(page):
    quickjs = pytest.importorskip("quickjs")
    html, dashjs, labels = page
    name = labels[3]
    p = Page(quickjs, html, dashjs, pre_js=f"location.hash = '#tabPlayers?player=' + encodeURIComponent({json.dumps(name)});")
    rep = p.report()
    assert rep["activeTab"] == "tabPlayers" and rep["gPlayer"] == name
    _card_ok(rep, name)


def test_show_my_card_and_click_your_name(page):
    quickjs = pytest.importorskip("quickjs")
    html, dashjs, labels = page
    mine = labels[4]
    p = Page(quickjs, html, dashjs, pre_js=f"localStorage.setItem('wcl_dash_player', {json.dumps(mine)});")
    p.click("#btn_tabPlayers")
    rep = p.report()
    _clean(rep)
    assert rep["showMyCard"] == f"Show my card ({mine})"
    p.click("#showMyCard")
    _card_ok(p.report(), mine)
    p.click("#detail_tabPlayers .close")
    # click-your-name in the JS "Who pulls first" matrix
    first = p.run("document.querySelector('#detail_tabPlayers tr[data-player]').dataset.player")
    p.click("#detail_tabPlayers tr[data-player] .player")
    _card_ok(p.report(), first)
    p.click("#detail_tabPlayers .close")
    # click-your-name in the static Roster table (regression: its rows carried no data-player, so clicks did nothing)
    roster = p.run("document.querySelector('#static_tabPlayers tr[data-player]').dataset.player")
    assert roster in labels
    p.click("#static_tabPlayers tr[data-player] .player")
    _card_ok(p.report(), roster)


def test_night_and_type_filters_with_player(page):
    quickjs = pytest.importorskip("quickjs")
    html, dashjs, labels = page
    p = Page(quickjs, html, dashjs)
    p.click("#btn_tabPlayers")
    night = p.run("document.getElementById('gNight').options[1].value")
    p.select("gNight", night)
    rep = p.report()
    _clean(rep)
    assert not rep["hasCard"] and rep["close"] and rep["h2"][0].startswith(night)
    p.select("gPlayer", labels[0])
    rep = p.report()
    _card_ok(rep, labels[0])
    assert rep["cardTitle"].endswith(night)
    # the fixture night is an open night: 'main' leaves the player with no pulls -> card empty state, no exception
    if p.run("!!document.getElementById('gType')"):
        p.select("gType", "main")
        rep = p.report()
        _clean(rep)
        assert rep["hasCard"] and rep["empties"] and "no pulls in this selection" in rep["empties"][0]


def test_every_player_card_renders(page):
    quickjs = pytest.importorskip("quickjs")
    html, dashjs, labels = page
    p = Page(quickjs, html, dashjs)
    p.click("#btn_tabPlayers")
    for name in labels:
        p.select("gPlayer", name)
        _card_ok(p.report(), name)
