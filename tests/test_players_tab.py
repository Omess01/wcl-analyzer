"""Players tab (Phase 1): deep links #tabPlayers?player=, click-your-name, Show my card, copy link."""

import json

import pytest

from dash.page import static_file


def _table_helpers(quickjs):
    """Evaluate the table-helpers marker block of dash.js in quickjs (no DOM)."""
    src = static_file("dash.js")
    start = src.index("// --- table helpers (quickjs-testable) ---")
    end = src.index("// --- end table helpers ---")
    ctx = quickjs.Context()
    ctx.eval(src[start:end])
    return ctx


NAMES = ["Nek'zali", "Ixavior", "Gigaspinning-Silvermoon", "Name-Realm", "Two Words", "Zûljîn", "Ærøskøbing",
         "Té'a (alt)", "Plus+Sign", "Pct%20", "a&b=c?d#e"]


@pytest.fixture(scope="module")
def ctx():
    return _table_helpers(pytest.importorskip("quickjs"))


@pytest.mark.parametrize("name", NAMES)
def test_player_hash_round_trip(ctx, name):
    h = ctx.eval(f"playerHash({json.dumps(name)})")
    assert h.startswith("#tabPlayers?player=")
    # one opaque value: no raw separators, apostrophes or spaces that chat clients cut links at
    value = h[len("#tabPlayers?player="):]
    for ch in "'() #&?=+":
        assert ch not in value, (name, h)
    if "+" not in name:   # '+' would read back as a space (form encoding); never in WoW names
        assert ctx.eval(f"parsePlayerHash({json.dumps(h)})") == name


def test_player_hash_known_forms(ctx):
    assert ctx.eval("playerHash(\"Nek'zali\")") == "#tabPlayers?player=Nek%27zali"
    assert ctx.eval("playerHash('Name-Realm')") == "#tabPlayers?player=Name-Realm"
    assert ctx.eval("playerHash('')") == "#tabPlayers"
    assert ctx.eval("playerHash(null)") == "#tabPlayers"


def test_parse_player_hash_variants(ctx):
    p = lambda h: ctx.eval(f"parsePlayerHash({json.dumps(h)})")
    assert p("#tabPlayers?player=Nek'zali") == "Nek'zali"          # unencoded apostrophe (hand-typed link)
    assert p("tabPlayers?player=Nek%27zali") == "Nek'zali"          # without '#'
    assert p("?player=Two+Words") == "Two Words"
    assert p("#tabPlayers?x=1&player=Name-Realm&y=2") == "Name-Realm"
    assert p("#tabPlayers?player=%E2%9C%93bad%") == "%E2%9C%93bad%"  # malformed escape keeps the raw text
    for none in ("", "#tab3", "#tab3:deaths", "#tabPlayers", "#tabPlayers?", "#tabPlayers?player=", "#tabPlayers?player",
                 "#tabPlayers?playerx=A", "#tabPlayers?player=%20"):
        assert ctx.eval(f"parsePlayerHash({json.dumps(none)})") is None, none


def _deep_link_block():
    js = static_file("dash.js")
    return js[js.index("// deep links:"):js.index("dashReady")]


def test_deep_link_parser_splits_query_before_section():
    block = _deep_link_block()
    q, colon = block.index("indexOf('?')"), block.index(".split(':')")
    assert q < colon
    assert "parsePlayerHash(rawHash)" in block and "hasPlayerOption(wantedPlayer)" in block
    # the player is applied before the wanted tab opens (one render of the filtered Players tab)
    assert block.index("applyGlobal()") < block.index("activateTab(wanted, false)")
    # plain #tabN still never scrolls (see test_plain_hash_deep_link_does_not_scroll)
    assert [l for l in block.splitlines() if "scrollIntoView" in l] == ["    if (sec) sec.scrollIntoView({ behavior: 'auto', block: 'start' });"]


def test_apply_global_and_clear_all_sync_hash():
    js = static_file("dash.js")
    ag = js[js.index("function applyGlobal()"):js.index("function renderIfDirty(")]
    assert "store.set('wcl_dash_player', G.player)" in ag and "syncPlayerHash();" in ag
    assert "activeTab() === 'tabPlayers'" in ag and "history.replaceState(null, '', want)" in ag
    ca = js[js.index("function clearAll()"):js.index("function filteredPulls(")]
    assert "syncPlayerHash(true)" in ca


def test_click_name_show_my_card_and_copy_link_handlers():
    js = static_file("dash.js")
    assert 'closest("tr[data-player] .player, [data-player-pick]")' in js
    assert "gPlayer.value = name; applyGlobal();" in js
    # Show my card: unfiltered Players panel, only when the stored name is still a toolbar option
    rp = js[js.index("function renderPlayersTab("):js.index("// deep links:")]
    unf = rp[:rp.index("stat.classList.add('hidden')")]
    assert "store.get('wcl_dash_player')" in unf and "hasPlayerOption(mine)" in unf
    assert "id='showMyCard' data-player-pick=" in unf and "myCard + whoPullsFirstHtml" in unf
    # copy link: clipboard with a visible-text fallback
    assert "closest('.copy-link')" in js
    assert "navigator.clipboard.writeText(url)" in js and "location.href.split('#')[0] + playerHash(name)" in js
    assert "out.textContent = url" in js
    assert "class='copy-link linklike'" in rp


# ---------------- T6: the player card (pure helpers + renderer, evaluated in quickjs) ----------------

import base64
import gzip
import re
from types import SimpleNamespace


def _card_ctx(quickjs):
    """quickjs context with stubbed TOK, the table helpers, the card components block (incl. the card renderer), fmtN
    and recapHtml (the card's death expand) taken from dash.js."""
    src = static_file("dash.js")
    blk = lambda a, b: src[src.index(a):src.index(b)]
    ctx = quickjs.Context()
    ctx.eval("var TOK = { ink: 'INK', inkDim: 'INKDIM', border: 'BORDER', borderStrong: 'BSTRONG', borderControl: 'BCTRL', accent: 'ACCENT', "
             "good: 'GOOD', warn: 'WARN', bad: 'BAD', series: ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'] };\n"
             + blk("// --- table helpers (quickjs-testable) ---", "// --- end table helpers ---")
             + blk("// --- card components (quickjs-testable) ---", "// --- end card components ---"))
    fmt_n = next(l for l in src.splitlines() if l.strip().startswith("const fmtN = "))
    ctx.eval(fmt_n + "\n" + blk("  function recapHtml(d) {", "  // ---------------- boss tab sections"))
    return ctx


def _inflate(mime, text):
    if mime == "application/json":
        return json.loads(text.replace("<\\/", "</"))
    return json.loads(gzip.decompress(base64.b64decode(text)).decode("utf-8"))


def _fixture_build(bosses, **kw):
    """(boss lists in tab order as renderPlayerCard builds them, Players block, cfg) from a real fixture build."""
    from dash.page import build_html
    args = dict(start="2026-09-09", end="2026-09-09", difficulty=["normal", "heroic", "mythic"], zone=None, boss=None, player=None,
                progression_only=False, callouts="anonymous", nights="all", reports=None, uncompressed=False)
    args.update(kw)
    html = build_html(bosses, SimpleNamespace(**args))
    script = lambda sid: re.search(rf"<script type='([^']+)' id='{sid}'>(.*?)</script>", html, flags=re.S).groups()
    tab_names = json.loads(script("tab_names")[1])
    lists = []
    for tab, label in tab_names.items():
        if not re.search(rf"id='data_{tab}'", html):
            continue
        d = _inflate(*script(f"data_{tab}"))
        lists.append({"key": tab, "label": label, "pulls": d["pulls"], "cols": d["pmcols"], "avoid": bool(d["avoidable"]),
                      "cats": d["cats"], "usecats": d["usecats"]})
    return lists, _inflate(*script("data_tabPlayers")), json.loads(script("cfg")[1])


def _card(ctx, name, G=None, named=False):
    return ctx.eval(f"playerCardHtml({json.dumps(name)}, LISTS, PLY, {json.dumps(G or {'night': '', 'ntype': ''})}, "
                    f"{{ named: {json.dumps(named)}, recap: recapHtml, roleOf: roleOfX, support: sp => CFGX.support.includes(sp), "
                    f"copy: \"<button type='button' class='copy-link linklike' data-player='X'>Copy link</button>\" }})")


def _load(ctx, lists, players, cfg):
    ctx.eval(f"var LISTS = {json.dumps(lists)}; var PLY = {json.dumps(players)}; var CFGX = {json.dumps(cfg)};"
             "var roleOfX = sp => CFGX.tanks.includes(sp) ? 'tank' : CFGX.healers.includes(sp) ? 'healer' : 'dps';")


def test_card_renders_for_every_player(bosses):
    """Exit criterion: the card renders for every roster label from the real fixture payloads."""
    ctx = _card_ctx(pytest.importorskip("quickjs"))
    lists, players, cfg = _fixture_build(bosses)
    _load(ctx, lists, players, cfg)
    assert players["named"] is False and len(players["roster"]) >= 15
    for name, info in players["roster"].items():
        html = _card(ctx, name)
        assert html and "<div class='card player-card'>" in html, name
        assert f"<h2 class='panel-title'>{name}" in html.replace("&#39;", "'"), name
        assert "<h4" not in html and "undefined" not in html and "NaN" not in html and "null" not in html, name
        for block in ("One thing to work on", "key numbers</h3>", "<h3>Per boss</h3>", "<h3>Consistency</h3>", "<h3>Deaths (",
                      "<h3>Preparation</h3>", "<h3>Gear</h3>", "class='copy-link linklike'"):
            assert block in html, (name, block)
        # Contract B wording: the fixture's Ula'tek wipe has wc = 92.5 and every player was in it
        assert "Deaths and hits after the wipe started are not counted (a wipe starts at the first death of a run of 3+ deaths " \
               "within 10 s that runs to the end of the pull)" in html, name
        assert "First nights &mdash; no trend yet" in html, name           # one fixture night: no deltas, no sparklines
        assert "<svg class='spark'" not in html
        assert "under-reported" in html, name
        role = info["role"]
        if name in ("Ixavior", "Airohdh"):
            assert role == "tank" and "<div class='uptime'><span class='uptime-bar'" in html and "Co-tank (DTPS)" in html, name
        if name in ("Gigaspinning", "Maxiumus"):
            assert role == "healer" and "Your median overheal" in html and "<div class='bullet'>" in html and "Median active HPS" in html, name
            assert "Damage done:" in html, name
        if role == "dps":
            assert "Your median active DPS" in html and "Same spec" not in html, name   # public build: no same-spec line
    # the dying tank's recap shows the AM flag (6th recap element)
    assert "AM up" in _card(ctx, "Ixavior") or "AM down" in _card(ctx, "Ixavior")
    # gotab links on the per-boss rows, one per boss with pulls
    assert _card(ctx, "Totemdave").count("class='gotab linklike'") == len(lists)


def test_card_named_build_adds_same_spec_and_no_cap(bosses):
    ctx = _card_ctx(pytest.importorskip("quickjs"))
    lists, players, cfg = _fixture_build(bosses, callouts="named")
    _load(ctx, lists, players, cfg)
    assert players["named"] is True
    html = _card(ctx, "Totemdave", named=True)
    assert "Same spec (Elemental):" in html and "in your role" in html     # rank (10th sev element) only when named
    assert "Same spec" not in _card(ctx, "Totemdave", named=False)


def test_card_follows_night_filter_and_empty_state(bosses):
    ctx = _card_ctx(pytest.importorskip("quickjs"))
    lists, players, cfg = _fixture_build(bosses)
    _load(ctx, lists, players, cfg)
    night = players["nights"][0][0]
    on = _card(ctx, "Totemdave", {"night": night, "ntype": ""})
    assert "4 pulls" in on and night in on
    main = _card(ctx, "Totemdave", {"night": "", "ntype": "main"})       # the fixture night is an open night
    assert "has no pulls in this selection" in main and "<h2 class='panel-title'>Totemdave" in main
    assert "class='copy-link linklike'" in main
    # without the Players block the card still renders from the per-pull vectors
    nodata = ctx.eval("playerCardHtml('Totemdave', LISTS, null, {night: '', ntype: ''}, {roleOf: roleOfX})")
    assert "<h3>Per boss</h3>" in nodata and "the Players data is missing" in nodata


def test_pick_night():
    ctx = _card_ctx(pytest.importorskip("quickjs"))
    ctx.eval("var NS = [['Thu 1', 'main', 1], ['Mon 2 open', 'open', 2], ['Sun 3', 'main', 3], ['Mon 4 open', 'open', 4]];")
    pick = lambda g, have="undefined": ctx.eval(f"pickNight(NS, {json.dumps(g)}, {have})")
    assert pick({}) == "Mon 4 open"
    assert pick({"ntype": "main"}) == "Sun 3"
    assert pick({"ntype": "open"}) == "Mon 4 open"
    assert pick({"night": "Thu 1"}) == "Thu 1"
    assert pick({"night": "Fri 9"}) is None
    assert pick({}, "['Thu 1', 'Mon 2 open']") == "Mon 2 open"
    assert pick({"ntype": "main"}, "new Set(['Thu 1'])") == "Thu 1"
    assert pick({"night": "Sun 3"}, "['Thu 1']") is None
    assert ctx.eval("pickNight([], {})") is None


def test_cap_items_public_and_named():
    ctx = _card_ctx(pytest.importorskip("quickjs"))
    w = lambda m, s: [m, 1, 0, "role", "watch", s, m, 3, 4]
    items = [w("dth", 5), w("fd", 4), w("avm", 3), w("prep", 2), w("act", 1), ["am", 70, 60, "cotank", "good", 0.5, "am", 2, 4],
             ["ilvl", 300, 310, "role", "note", 0, "ilvl", 0, 4]]
    ctx.eval(f"var IT = {json.dumps(items)};")
    pub = ctx.eval("JSON.stringify(capItems(IT, false))")
    pub = json.loads(pub)
    assert [i[0] for i in pub if i[4] == "watch"] == ["dth", "fd", "avm"]      # <= 3 Watch, most important first
    assert sum(1 for i in pub if i[4] == "good") >= 1 and any(i[4] == "note" for i in pub)
    assert len(json.loads(ctx.eval("JSON.stringify(capItems(IT, true))"))) == len(items)   # named: no cap
    assert json.loads(ctx.eval("JSON.stringify(capItems(null, false))")) == []
    assert ctx.eval("oneThing(IT)[0]") == "dth"
    assert ctx.eval("oneThing(IT.slice(5))") is None


def test_fill_advice_substitutes_every_placeholder():
    ctx = _card_ctx(pytest.importorskip("quickjs"))
    from analysis.severity import ADVICE
    item = ["nodef", 66.67, 50, "band", "watch", 1.2, "nodef", 2, 3]
    for key, tpl in ADVICE.items():
        out = ctx.eval(f"fillAdvice({json.dumps(tpl)}, {json.dumps(item)})")
        assert not re.search(r"\{(value|baseline|n|pulls)\}", out), key
    out = ctx.eval(f"fillAdvice({json.dumps(ADVICE['nodef'])}, {json.dumps(item)})")
    assert out.startswith("No defensive before 2 of 3 first deaths (66.7% vs 50%)")
    assert "n/a" in ctx.eval("fillAdvice('{value} vs {baseline}', ['oh', 25.5, null, null, 'note', 0, 'oh', 0, 4])")
    assert ctx.eval("fillAdvice('', ['ilvl', 312, 315, 'role', 'note', 0, 'ilvl', 0, 4])") == "Item level: 312 (reference 315)."


def test_per_boss_rows_and_consistency_series():
    ctx = _card_ctx(pytest.importorskip("quickjs"))
    cols = ["act", "dps", "hps", "dth", "fd", "alv", "avh"]
    pull = lambda i, dps, k=False, d=120, dth=0, fd=0: {"i": i, "n": "Thu 1", "a": i, "k": k, "d": d, "parts": {"A": "Mage"},
                                                        "pm": {"A": [90, dps, None, dth, fd, 60, 2]}}
    lists = [{"key": "tab0", "label": "Boss (Heroic)", "cols": cols, "avoid": True,
              "pulls": [pull(1, 100, dth=1, fd=1), pull(2, 110), pull(3, 120), pull(4, 130, True), pull(5, 999, d=30)]},
             {"key": "tab1", "label": "Other (Heroic)", "cols": cols, "avoid": False, "pulls": [pull(1, 50)]}]
    ctx.eval(f"var L = {json.dumps(lists)}, C = {json.dumps(cols)};")
    rows = json.loads(ctx.eval("JSON.stringify(perBossRows(L, 'A', C))"))
    assert [r["key"] for r in rows] == ["tab0", "tab1"]
    r0 = rows[0]
    assert (r0["pulls"], r0["kills"], r0["deaths"], r0["fd"]) == (5, 1, 1, 1)
    assert r0["dps"] == 115 and r0["bestDps"] == 130          # the 30 s pull is left out of the medians
    assert r0["avm"] == 2.0 and rows[1]["avm"] is None         # avoidable per minute alive only with an avoidable list
    series = json.loads(ctx.eval("JSON.stringify(consistencySeries(L, 'A', C, 'dps', L, 'active DPS'))"))
    assert len(series) == 1 and series[0]["boss"] == "Boss (Heroic)" and len(series[0]["pulls"]) == 4
    assert series[0]["pulls"][3] == {"v": 130, "k": True, "i": 4} and series[0]["band"] is not None
    assert json.loads(ctx.eval("JSON.stringify(consistencySeries(L, 'A', C, 'dps', [], 'x'))"))[0]["band"] is None


def test_card_source_placement_and_privacy_hooks():
    js = static_file("dash.js")
    card, rp = js.index("function renderPlayerCard("), js.index("function renderPlayersTab(")
    assert card < rp
    block = js[js.index("// --- card components (quickjs-testable) ---"):js.index("// --- end card components ---")]
    for fn in ("function pickNight(", "function capItems(", "function oneThing(", "function perBossRows(", "function consistencySeries(",
               "function fillAdvice(", "function playerCardHtml("):
        assert fn in block, fn
    assert "document" not in block and "window" not in block and "<h4" not in block
    # the card gets the public/named switch from cfg, and the Players block has its own try/catch
    assert "named: !!CFG.named" in js[card:rp]
    load = js[js.index("const PLAYERS = { data: null, error: '' };"):js.index("const loadTab = tab =>")]
    assert "getElementById('data_tabPlayers')" in load and "try {" in load and "catch (err)" in load
    # the filtered Players branch renders the card instead of the per-boss table; the matrix and All pulls stay below
    body = js[rp:js.index("// deep links")]
    filt = body[body.index("if (G.player) {"):body.index("} else {")]
    assert filt.index("renderPlayerCard(G.player") < filt.index("whoPullsFirstHtml(") < filt.index("allPullsHtml(")
    assert "'Started the wipe'" not in filt
