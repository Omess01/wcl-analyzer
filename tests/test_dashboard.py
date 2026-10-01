"""The HTML build: payload round-trip, structure, and JS syntax."""

import base64
import gzip
import json
import os
import html as html_mod
import re
from types import SimpleNamespace

import pytest

from dash.page import build_html, static_file
from dash.payload import pull_payload


def _args(**kw):
    base = dict(start="2026-09-09", end="2026-09-09", difficulty=["normal", "heroic", "mythic"], zone=None, boss=None,
                player=None, progression_only=False, callouts="anonymous", nights="all", reports=None, uncompressed=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _payloads(html: str) -> dict:
    out = {}
    for m in re.finditer(r"<script type='(application/[a-z+0-9]+)' id='data_(tab\d+)'>(.*?)</script>", html, flags=re.S):
        mime, tab, text = m.groups()
        if mime == "application/json":
            out[tab] = json.loads(text.replace("<\\/", "</"))
        else:
            out[tab] = json.loads(gzip.decompress(base64.b64decode(text)).decode("utf-8"))
    return out


def test_payload_roundtrip_compressed_and_plain(bosses):
    (name, diff), pulls = next(iter(bosses.items()))
    mime, text = pull_payload(pulls, name, diff, {}, compress=True)
    assert mime == "application/gzip+base64" and "</" not in text
    data = json.loads(gzip.decompress(base64.b64decode(text)))
    mime2, text2 = pull_payload(pulls, name, diff, {}, compress=False)
    assert mime2 == "application/json" and "</script" not in text2
    assert json.loads(text2.replace("<\\/", "</")) == data
    assert data["boss"] == name and len(data["pulls"]) == len(pulls)
    p = data["pulls"][0]
    for key in ("i", "n", "t", "k", "p", "fp", "d", "a", "ph", "pt", "parts", "specs", "deaths", "dt", "dd", "hd", "ir", "ds", "use", "cons", "hx"):
        assert key in p, key
    assert isinstance(data["src"], dict) and isinstance(data["cats"], list) and isinstance(data["usecats"], list)
    first = next((q["deaths"][0] for q in data["pulls"] if q["deaths"]), None)
    if first is not None:
        assert "ext" in first and "def" in first and "cs" in first
    # per-phase hit counts ride along when the pull has phases
    phased = [q for q in data["pulls"] if q["pt"]]
    if phased:
        row = next(r for r in phased[0]["dt"] if len(r) >= 6)
        assert sum(row[5]) == row[2]


def test_build_html_structure(bosses, tmp_path):
    html = build_html(bosses, _args())
    assert html.startswith("<!DOCTYPE html>") and "<html lang='en'>" in html
    assert "--surface-card:" in html and "--ring:" in html   # tokens.css is inlined
    payloads = _payloads(html)
    assert len(payloads) == len(bosses)
    for tab in payloads:
        assert f"<section id='{tab}'" in html
        assert f"class='pull-grid' data-tab='{tab}'" in html
        assert f"id='detail_{tab}'" in html
    # every boss tab button is an ARIA tab and points at an existing panel
    for m in re.finditer(r"<button type='button' role='tab' id='btn_(\w+)'.*?aria-controls='(\w+)'", html):
        assert m.group(1) == m.group(2) and f"<section id='{m.group(2)}'" in html
    # pull boxes are real buttons, not divs
    assert "<button type='button' class='pull-box" in html and "<div class='pull-box" not in html
    # boss tabs carry their difficulty for the segment control; the mobile tab select exists
    assert "data-diff='Normal'" in html and "id='tabSelect'" in html
    # every boss tab button carries its boss name for the grouped mobile tab select
    boss_buttons = re.findall(r"<button type='button' role='tab'[^>]*class='tab-btn boss[^>]*>", html)
    assert len(boss_buttons) == len(bosses)
    assert all("data-name='" in b for b in boss_buttons)
    # no leftover static Python-rendered boss sections
    assert "id='static_tab0'" not in html
    # size: one report must be well under a megabyte with the Plotly CDN script
    assert len(html.encode("utf-8")) < 1_500_000
    (tmp_path / "out.html").write_text(html, encoding="utf-8")


def test_uncompressed_flag(bosses):
    html = build_html(bosses, _args(uncompressed=True))
    assert "type='application/json' id='data_tab0'" in html
    assert _payloads(html)["tab0"]["pulls"]


def test_static_assets_present():
    css, js = static_file("dash.css"), static_file("dash.js")
    assert "prefers-reduced-motion" in css and ":focus-visible" in css
    assert "DecompressionStream" in js and "role='tab'" not in js  # tabs come from Python markup
    assert "</script" not in js
    # no Plotly modebar, in the browser renderer and in the Python-rendered charts
    assert "displayModeBar: false" in js


def test_home_plotly_config_hides_modebar(bosses):
    home = _home(build_html(bosses, _args()))
    assert "<figure class='chart'>" in home and '"displayModeBar": false' in home.replace('":false', '": false')


def test_js_syntax():
    quickjs = pytest.importorskip("quickjs")
    src = static_file("dash.js")
    ctx = quickjs.Context()
    ctx.eval("(function(){\n" + src + "\n})")   # parse only


def test_tokens_inlined_and_old_variables_gone():
    css = static_file("dash.css")
    for old in ("--bg", "--panel", "--panel2", "--text", "--muted", "--blue", "--focus"):
        assert f"var({old})" not in css and f"{old}:" not in css, old
    assert "--surface-card:" in static_file("tokens.css")


def test_css_uses_type_scale():
    css = static_file("dash.css")
    assert not re.search(r"font-size:\s*\d+px", css), "raw px font sizes; use var(--fs-*)"


def _pure_chart_helpers(quickjs):
    """Evaluate the pure chart helpers from dash.js in quickjs (no DOM). They must sit between the two marker comments."""
    src = static_file("dash.js")
    start = src.index("// --- pure chart helpers (quickjs-testable) ---")
    end = src.index("// --- end pure chart helpers ---")
    ctx = quickjs.Context()
    ctx.eval("var TOK = { ink: '#eef1f6', inkDim: '#9aa6bd', border: '#2a3344', borderStrong: '#3a4658', borderControl: '#5a6a86', accent: '#c9a227', "
             "good: '#22c55e', warn: '#fab219', bad: '#f0716f', series: ['#1', '#2', '#3', '#4', '#5', '#6'] };")
    ctx.eval(src[start:end])
    return ctx


def test_chart_layout_keeps_room_for_plotly_titles():
    """A layout with an in-canvas title needs the old 50px top margin; untitled charts get the tight 20px."""
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    base = "{ margin: { l: 40, r: 20, t: 20, b: 40 }, font: { color: '#fff' } }"
    assert ctx.eval(f"chartLayout({base}, {{ title: 'Wipes by phase' }}, 320).margin.t") == 50
    assert ctx.eval(f"chartLayout({base}, {{ title: {{ text: 'x', y: 0.98 }} }}, 320).margin.t") == 50
    assert ctx.eval(f"chartLayout({base}, {{ xaxis: {{ title: 'Pull' }} }}, 320).margin.t") == 20
    # an explicit margin from the caller always wins
    assert ctx.eval(f"chartLayout({base}, {{ title: 'x', margin: {{ l: 45, r: 20, t: 95, b: 45 }} }}, 320).margin.t") == 95
    assert ctx.eval(f"chartLayout({base}, {{ title: 'x' }}, 320).height") == 320
    # the base object is not mutated
    assert ctx.eval(f"(function(){{ var b = {base}; chartLayout(b, {{ title: 'x' }}, 1); return b.margin.t; }})()") == 20
    # Task 9: axes grow the margin for long tick labels, also when the caller passes its own axis object
    assert ctx.eval(f"chartLayout({base}, {{ yaxis: {{ autorange: 'reversed' }} }}, 320).yaxis.automargin") is True
    assert ctx.eval(f"chartLayout({base}, {{}}, 320).xaxis.automargin") is True
    assert ctx.eval(f"chartLayout({base}, {{ xaxis: {{ automargin: false }} }}, 320).xaxis.automargin") is False


def test_focus_ring_survives_forced_colors_and_table_headers():
    css = static_file("dash.css")
    rule = re.search(r"^:focus-visible \{([^}]*)\}", css, flags=re.M).group(1)
    assert "outline:none" not in rule, "forced-colors mode drops box-shadow; keep a transparent outline instead of none"
    assert "outline:2px solid transparent" in rule and "var(--ring)" in rule
    # the sort buttons live inside the .scroller (overflow:auto) where an outer shadow is clipped
    assert re.search(r"th button:focus-visible \{[^}]*inset[^}]*\}", css)


def test_page_chrome(bosses):
    html = build_html(bosses, _args())
    assert "<header class='page'><div class='wrap'>" in html
    assert "<footer class='page'><div class='wrap'>" in html
    assert "<main id='main' class='wrap' tabindex='-1'>" in html
    # the old-browser note is the first thing inside main
    assert re.search(r"<main id='main' class='wrap' tabindex='-1'>\s*<div id='oldBrowser'", html)
    # tab labels carry difficulty + pull count in the example's .sub span, and keep the JS badge
    assert re.search(r"role='tab'[^>]*class='tab-btn boss'[^>]*>[^<]+<span class='sub'>(Normal|Heroic|Mythic) &middot; \d+ pulls?</span> <span class='badge'>", html)
    assert "Raid<span class='sub'>" in html or ">Raid</button>" in html
    # the sticky element is the tab nav, not the toolbar
    assert re.search(r"<nav class='wrap tabnav( has-diffbar)?' aria-label='Dashboard sections'>", html)
    # footer build info
    n_reports = len({p["report_code"] for pulls in bosses.values() for p in pulls})
    m = re.search(r"<footer class='page'>.*?</footer>", html, flags=re.S)
    assert m, "footer missing"
    foot = m.group(0)
    assert re.search(r"Generated <time datetime='\d{4}-\d{2}-\d{2}T\d{2}:\d{2}'>\d{4}-\d{2}-\d{2} \d{2}:\d{2}</time>", foot)
    assert f"{n_reports} report{'s' if n_reports != 1 else ''}" in foot
    kb = int(re.search(r"(\d+) KB", foot).group(1))
    assert abs(kb - len(html.encode("utf-8")) // 1024) <= 1
    assert "Plotly 2.35.2" in foot
    assert "Percentages are boss HP left; lower is better." in foot
    # no hex colour literals in the page skeleton module
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", open(os.path.join(os.path.dirname(__file__), "..", "dash", "page.py"), encoding="utf-8").read())


def test_loading_state(bosses):
    html = build_html(bosses, _args())
    boss_panels = re.findall(r"<section id='tab\d+' [^>]*>", html)
    assert boss_panels and all("aria-busy='true'" in s for s in boss_panels)
    for tab in _payloads(html):
        assert re.search(rf"id='detail_{tab}'[^>]*><div class='skeleton' aria-hidden='true'>", html)
    assert re.search(r"<div class='tabs' role='tablist'[^>]*\binert\b", html)
    js = static_file("dash.js")
    assert "removeAttribute('inert')" in js
    assert "removeAttribute('aria-busy')" in js and ".skeleton" in js
    # a failed inflation must not leave the tab strip inert
    err = js[js.index("function dashShowError"):js.index("window.addEventListener('error'")]
    assert "inert" in err


def test_plain_hash_deep_link_does_not_scroll():
    js = static_file("dash.js")
    block = js[js.index("// deep links:"):js.index("dashReady")]
    # the only scroll in the deep-link block is guarded by the section lookup (#tabN:section)
    lines = [l for l in block.splitlines() if "scrollIntoView" in l]
    assert len(lines) == 1 and "if (sec)" in lines[0]
    # a deep link never persists the difficulty choice
    assert "setDiff('all', false)" in block or "setDiff('all', { persist: false })" in block


def test_tab_select_grouped_and_diff_default_all():
    js = static_file("dash.js")
    assert "createElement('optgroup')" in js and "dataset.name" in js
    init = js[js.index("if (diffBtns.length)"):]
    init = init[:init.index("diffBtns.forEach")]
    assert ": 'all'" in init


def test_table_markup_matches_example():
    from dash.common import table
    out = table([("Player", "str"), ("Pulls", "num"), ("Notes", "none")], "<tr><td>a</td><td class='right'>1</td><td>x</td></tr>", "att", "Caption here")
    assert out.startswith("<div class='scroller'><table class='sortable att'><caption>Caption here</caption>")
    assert "<th scope='col' data-type='str'><button type='button' aria-label='Sort by Player'>Player</button></th>" in out
    assert "<th scope='col' data-type='num' class='right'><button type='button' aria-label='Sort by Pulls'>Pulls</button></th>" in out
    assert "<th scope='col' data-type='none'>Notes</th>" in out
    assert "tabindex" not in out and "sr-only" not in out


def test_js_table_helper_mirrors_python():
    js = static_file("dash.js")
    assert "class='scroller'" in js and "aria-label='Sort by ${escH(full)}'" in js and "full = h[2] || h[0]" in js   # optional 3rd head element
    assert "sorted-asc" not in js and "sorted-desc" not in js
    # bar() builds the class with a template (`bar${heal ? ' heal' : ''}`); the rendered markup is checked in test_js_table_limit_markup
    assert "<div class='bar'><span" not in js and "<span class='bar${heal ? ' heal' : ''}' aria-hidden='true'><i" in js


def test_py_table_limit_markup():
    from dash.common import table
    heads = [("Player", "str"), ("Pulls", "num")]
    rows = [f"<tr><td>p{i}</td><td class='right'>{i}</td></tr>" for i in range(12)]
    out = table(heads, rows, "", "Cap", limit=10)
    assert out.count("class='lowpart'") == 2
    assert out.startswith("<div class='scroller'><table class='sortable ' data-limit='10'><caption>Cap</caption>")
    assert out.endswith("</table><button type='button' class='show-all' aria-expanded='false'>Show all 12</button></div>")
    # a row that already has a class keeps it and gains lowpart
    out = table(heads, rows[:10] + ["<tr class='me'><td>x</td><td>1</td></tr>", "<tr><td>y</td><td>2</td></tr>"], limit=10)
    assert "<tr class='me lowpart'>" in out and out.count("lowpart") == 2
    # the string form is split on <tr boundaries
    assert table(heads, "".join(rows), limit=10).count("class='lowpart'") == 2
    few = table(heads, rows[:8], limit=10)
    assert "show-all" not in few and "lowpart" not in few
    assert "show-all" not in table(heads, "".join(rows))


def _table_helpers(quickjs):
    """Evaluate the table helpers from dash.js in quickjs (no DOM). They must sit between the two marker comments."""
    src = static_file("dash.js")
    start = src.index("// --- table helpers (quickjs-testable) ---")
    end = src.index("// --- end table helpers ---")
    ctx = quickjs.Context()
    ctx.eval(src[start:end])
    return ctx


def test_js_table_limit_markup():
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    heads = "[['Player', 'str'], ['Pulls', 'num'], ['Notes', 'none']]"
    rows = lambda n: f"Array.from({{length: {n}}}, (_, i) => `<tr><td>p${{i}}</td><td>${{i}}</td><td>x</td></tr>`)"
    out = ctx.eval(f"tbl({heads}, {rows(12)}, 'att', 'Cap', 10)")
    assert out.startswith("<div class='scroller'><table class='sortable att' data-limit='10'><caption>Cap</caption>")
    assert "<th scope='col' data-type='num' class='right'><button type='button' aria-label='Sort by Pulls'>Pulls</button></th>" in out
    assert "<th scope='col' data-type='none'>Notes</th>" in out
    assert out.count("class='lowpart'") == 2
    assert out.endswith("</table><button type='button' class='show-all' aria-expanded='false'>Show all 12</button></div>")
    few = ctx.eval(f"tbl({heads}, {rows(8)}, 'att', 'Cap', 10)")
    assert "show-all" not in few and "lowpart" not in few
    assert "<tr class='me lowpart'>" in ctx.eval(f"tbl({heads}, [...{rows(10)}, `<tr class='me'><td>x</td></tr>`], '', '', 10)")
    assert ctx.eval("bar(50)") == "<span class='bar' aria-hidden='true'><i style='width:50.0%'></i></span>"
    assert ctx.eval("bar(150, true)") == "<span class='bar heal' aria-hidden='true'><i style='width:100.0%'></i></span>"


def test_player_cell():
    from dash.common import player_cell
    assert player_cell("Omess", "DemonHunter", "dps", "Havoc") == \
        "<span class='player DemonHunter'>Omess</span><span class='role'>DPS</span><br><span class='spec'>Havoc Demon Hunter</span>"
    assert player_cell("Omess", "DemonHunter") == "<span class='player DemonHunter'>Omess</span>"
    assert player_cell("A<b>", "Mage", "healer") == "<span class='player Mage'>A&lt;b&gt;</span><span class='role'>Healer</span>"
    js = static_file("dash.js")
    assert "const playerCell = (name, cl, role, spec)" in js


def test_class_label_splits_camel_case():
    """Task 9: spec lines read 'Havoc Demon Hunter', not 'Havoc DemonHunter' (Python and JS twins)."""
    from dash.common import class_label
    assert class_label("DemonHunter") == "Demon Hunter" and class_label("DeathKnight") == "Death Knight"
    assert class_label("Mage") == "Mage"
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    assert ctx.eval("clsLabel('DemonHunter')") == "Demon Hunter" and ctx.eval("clsLabel('Mage')") == "Mage"
    assert "escH(clsLabel(cl))" in static_file("dash.js")


def test_attendance_count_on_one_line():
    """Task 9: '.sub' is display:block globally; the '/N' of an attendance cell stays on the count's line."""
    assert "table.attendance td.att > .sub:first-of-type { display:inline; }" in static_file("dash.css")


def _home(html: str) -> str:
    return html.split("<section id='tabHome'")[1].split("</section>")[0]


def test_home_markup_matches_example(bosses):
    html = build_html(bosses, _args())
    home = _home(html)
    # the fixture is a full clear, so the Bosses killed tile carries the 'good' tile class
    assert "<dl class='kpis'>" in home and "<div class='kpi good'><dt>Bosses killed</dt><dd>" in home
    assert "<div class='progress-grid'>" in home
    assert re.search(r"<button type='button' class='boss (killed|progress) gotab' data-tab='tab0'>", home)
    assert "<span class='name'>" in home and "<span class='head'>" in home
    assert "<article class='insight " in home and "<span class='badge'>" in home
    assert "class='ins-badge" not in home and "class='card'" not in home
    assert "<p class='section-note'>" in home
    assert "class='cards'" not in html   # every KPI strip is a <dl class='kpis'> now
    assert "<div class='card'>" not in static_file("dash.js")
    # heading order: h1 -> h2 night type -> h3 sections; insight titles are h4 with the badge first
    assert "<h1>" in home and "<h2 class='home-type'>" in home
    for sec in ("Progress", "Progression by first kills", "Worth a look", "Last raid night"):
        assert f"<h3>{sec}</h3>" in home, sec
    assert re.search(r"<article class='insight (good|warn|info)'><h4><span class='badge'>(Good|Watch|Note)</span>", home)
    assert "<h2>Progress</h2>" not in home
    # KPI units and no inline delta colours
    assert "<span class='unit'>" in home
    assert "style='color:" not in home.split("<h3>Last raid night</h3>")[1]


def test_home_insight_jump_link(bosses):
    import copy
    prog = copy.deepcopy(bosses)
    key = max(prog, key=lambda k: len(prog[k]))          # pretend the most-pulled boss is still in progress
    for p in prog[key]:
        p["kill"] = False
    home = _home(build_html(prog, _args()))
    from dash.page import boss_order_key
    tab = f"tab{[k for k, _ in sorted(prog.items(), key=boss_order_key(prog))].index(key)}"
    assert re.search(r"<article class='insight info'><h4><span class='badge'>Note</span>Progression: ", home)
    m = re.search(r"<button type='button' class='gotab jump' data-tab='(tab\d+)'>Open ([^<]+) &rarr;</button></article>", home)
    assert m and html_mod.unescape(m.group(2)) == key[0]
    assert m.group(1) == tab
    assert re.search(rf"<button type='button' class='boss progress gotab' data-tab='{m.group(1)}'>", home)
    assert "<div class='kpi'><dt>Bosses killed</dt>" in home   # not a full clear any more -> no 'good' tile


def test_home_anonymous_names_nobody(bosses):
    home = _home(build_html(bosses, _args(callouts="anonymous")))
    text = re.sub(r"<[^>]+>", " ", home)
    names = {n for ps in bosses.values() for p in ps for n in p["participants"]}
    leaked = [n for n in names if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text)]
    assert not leaked, leaked


def test_home_open_nights_collapsed(bosses):
    import copy
    types = {p["night_type"] for ps in bosses.values() for p in ps}
    assert types == {"open"}   # the fixture report is a Wednesday -> open night only

    home = _home(build_html(bosses, _args()))
    assert "<details class='night-type' open>" in home    # no main nights -> open nights expanded
    summary = home.split("<details class='night-type' open>")[1].split("</summary>")[0]
    assert "Open nights" in summary and "killed" in summary and "pulls" in summary and "players" in summary

    as_main = copy.deepcopy(bosses)
    for ps in as_main.values():
        for p in ps:
            p["night_type"] = "main"
            p["night"] = p["night"].removesuffix(" open")
    home = _home(build_html(as_main, _args()))
    assert "night-type" not in home                       # no open nights -> no details block
    assert "<h2 class='home-type'>Main raid nights</h2>" in home

    mixed = copy.deepcopy(bosses)
    first = next(iter(mixed.values()))
    for p in first[: max(1, len(first) // 2)]:
        p["night_type"] = "main"
        p["night"] = p["night"].removesuffix(" open")
    home = _home(build_html(mixed, _args()))
    assert "<details class='night-type'>" in home and "<details class='night-type' open>" not in home


def test_details_toggle_resizes_charts():
    js = static_file("dash.js")
    m = re.search(r"document\.addEventListener\('toggle', e => \{(.*?)\}, true\);", js, flags=re.S)
    assert m, "no capture-phase toggle listener for <details>"
    assert "HTMLDetailsElement" in m.group(1) and ".js-plotly-plot" in m.group(1)
    assert "dispatchEvent(new Event('resize'))" in m.group(1)


def test_insight_titles_escape_boss_names(bosses):
    import copy
    prog = copy.deepcopy(bosses)
    key = max(prog, key=lambda k: len(prog[k]))
    for p in prog[key]:
        p["kill"] = False
    prog[("<b>X</b>", key[1])] = prog.pop(key)
    for p in prog[("<b>X</b>", key[1])]:
        p["boss"] = f"<b>X</b> ({key[1]})"
    home = _home(build_html(prog, _args()))
    assert "Progression: &lt;b&gt;X&lt;/b&gt;</h4>" in home and "<b>X</b>" not in home


def test_progression_scale_single_pull():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("progScale(1, 920, 320).sx(0)") == pytest.approx((52 + 906) / 2)
    assert ctx.eval("progScale(10, 920, 320).sx(0)") == pytest.approx(52)
    assert ctx.eval("progScale(10, 920, 320).sx(9)") == pytest.approx(906)
    assert ctx.eval("progScale(10, 920, 320).sy(100)") == pytest.approx(16)
    assert ctx.eval("progScale(10, 920, 320).sy(0)") == pytest.approx(320 - 46)
    assert ctx.eval("progScale(10, 920, 320).sy(-5)") == pytest.approx(320 - 46)   # clamped


def test_narrow_legend_below_plot():
    """Task 9: one phone layout for JS and Python-rendered charts: horizontal legend under the plot, +40 px bottom margin."""
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    out = json.loads(ctx.eval("JSON.stringify(narrowLegend({ legend: { x: 0, y: 1.08, orientation: 'h' }, margin: { l: 45, b: 45 } }))"))
    assert out == {"legend": {"x": 0, "y": -0.25, "orientation": "h", "yanchor": "top"}, "margin": {"l": 45, "b": 85}}
    assert json.loads(ctx.eval("JSON.stringify(narrowLegend({}))"))["margin"] == {"b": 80}
    js = static_file("dash.js")
    assert "Object.assign(lay, narrowLegend(lay))" in js and "Plotly.relayout(el, narrowLegend(el.layout))" in js


def test_progression_width_follows_host():
    """Task 9: the SVG viewBox width is the host's CSS width (300..920), so axis text is not shrunk on phones."""
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("progWidth(330)") == 330
    assert ctx.eval("progWidth(1360)") == 920
    assert ctx.eval("progWidth(120)") == 300
    assert ctx.eval("progWidth(0)") == 920          # hidden host
    assert "progWidth(host.clientWidth)" in static_file("dash.js")


def test_progression_series_styles_cycle():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("seriesStyle(0).color") == "#1" and ctx.eval("seriesStyle(0).dash") == ""
    assert ctx.eval("seriesStyle(1).dash") == "7 4"
    # 6 colours x 7 dash patterns: night 7 reuses night 1's colour with another dash, the pair repeats only after 42
    assert ctx.eval("seriesStyle(6).color === seriesStyle(0).color && seriesStyle(6).dash !== seriesStyle(0).dash") is True
    assert ctx.eval("seriesStyle(6).dash") == "6 2 1 2"
    assert ctx.eval("seriesStyle(7).color") == "#2" and ctx.eval("seriesStyle(7).dash") == ""
    assert ctx.eval("seriesStyle(42).color === seriesStyle(0).color && seriesStyle(42).dash === seriesStyle(0).dash") is True


def test_progression_best_line_skipped_on_kill():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("bestWipe([{i:1,k:false,p:40},{i:2,k:false,p:25.5}]).i") == 2
    assert ctx.eval("bestWipe([{i:1,k:false,p:40},{i:2,k:true,p:0}])") is None
    assert ctx.eval("bestWipe([])") is None


def test_progression_hp_bands():
    """Point fill bands shared with the pull grid (Task 11): kill, < 10 %, 10-40 %, >= 40 %."""
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("hpBand(0, true)") == "kill"
    assert ctx.eval("hpBand(9.9, false)") == "near"
    assert ctx.eval("hpBand(10, false)") == "mid"
    assert ctx.eval("hpBand(39.9, false)") == "mid"
    assert ctx.eval("hpBand(40, false)") == "far"
    assert ctx.eval("hpBand(100, false)") == "far"
    assert ctx.eval("BAND_COLOR.kill") == "#c9a227" and ctx.eval("BAND_COLOR.near") == "#22c55e"
    assert ctx.eval("BAND_COLOR.mid") == "#fab219" and ctx.eval("BAND_COLOR.far") == "#f0716f"


def test_progression_point_labels():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("pointLabel({i:12,k:false,p:43.21,ph:'Stage Two'})") == "Pull 12 · 43.2 % · Stage Two"
    assert ctx.eval("pointLabel({i:3,k:false,p:80,ph:''})") == "Pull 3 · 80.0 %"
    assert ctx.eval("pointLabel({i:7,k:true,p:0,ph:'Stage Three'})") == "Pull 7 · kill"


def test_progression_chart_replaces_plotly_hp_chart():
    js = static_file("dash.js")
    assert "Boss HP remaining at end of each pull (lower = closer to kill)" not in js
    assert "function drawProgression(" in js and "progressionChartHtml(" in js
    draw = js[js.index("function drawProgression("):js.index("function pullsTableHtml(")]
    # every point is a keyboard-reachable button that selects the pull like a click
    assert "role: 'button'" in draw and "tabindex: '0'" in draw and "'aria-label': pointLabel(p)" in draw
    assert "'focus'" in draw and "'blur'" in draw and "'keydown'" in draw
    assert "hpBand(p.p, p.k)" in draw


def test_chart_title_extracted_from_object():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("chartTitle({ title: { text: 'Wipes by phase', y: 0.98 } })") == "Wipes by phase"
    assert ctx.eval("chartTitle({ title: 'Plain' })") == "Plain"
    assert ctx.eval("chartTitle({})") == ""


def test_chart_skip_rule():
    """Charts with nothing to compare become a sentence: < 2 bar categories, or < 4 points in every line."""
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("shouldSkipChart([])") is True
    assert ctx.eval("shouldSkipChart([{ type: 'bar', x: ['Stage One'], y: [5] }])") is True
    assert ctx.eval("shouldSkipChart([{ type: 'bar', x: ['Stage One', 'Stage Two'], y: [5, 2] }])") is False
    # categories are counted across traces
    assert ctx.eval("shouldSkipChart([{ type: 'bar', x: ['a'], y: [1] }, { type: 'bar', x: ['b'], y: [1] }])") is False
    assert ctx.eval("shouldSkipChart([{ type: 'scatter', x: [1, 2, 3], y: [4, 5, 6] }])") is True
    assert ctx.eval("shouldSkipChart([{ type: 'scatter', x: [1, 2, 3, 4], y: [4, 5, 6, 7] }])") is False
    # one long line is enough; y is counted when there is no x
    assert ctx.eval("shouldSkipChart([{ type: 'scatter', x: [1], y: [1] }, { type: 'scatter', x: [1, 2, 3, 4], y: [1, 2, 3, 4] }])") is False
    assert ctx.eval("shouldSkipChart([{ type: 'box', y: [1, 2, 3, 4] }])") is False
    # the wrapper only applies it when the caller passed a fallback sentence
    js = static_file("dash.js")
    body = js[js.index("function chart(traces, layout, height, title, fallback)"):js.index("function drawCharts(")]
    assert "fallback && shouldSkipChart(traces)" in body and "<p class='section-note'>${escH(fallback)}</p>" in body


def test_no_raw_colours_outside_tokens():
    js = static_file("dash.js")
    assert not re.findall(r"#[0-9a-fA-F]{6}\b", js), "hex colours belong in tokens.css"
    for name in ("home.py", "raid.py", "players.py", "mplus_tab.py", "payload.py", "page.py"):
        with open(os.path.join(os.path.dirname(__file__), "..", "dash", name), encoding="utf-8") as f:
            src = f.read()
        assert not re.findall(r"#[0-9a-fA-F]{6}\b", src), name
        assert "rgba(122,162,227" not in src, name


def test_fig_html_wraps_in_figure():
    import plotly.graph_objects as go
    from dash.common import fig_html
    fig = go.Figure(go.Bar(x=[1], y=[2]))
    fig.update_layout(title="Minutes per night")
    out = fig_html(fig, height=200)
    assert out.startswith("<figure class='chart'><div class='chart-head'><h3>Minutes per night</h3></div>")
    assert '"title":{"text":"Minutes per night"' not in out   # moved into the h3
    assert "plotly_dark" not in out and '"gridcolor":"#2a3344"' in out


def test_fig_html_keeps_axis_settings():
    import plotly.graph_objects as go
    from dash.common import fig_html
    fig = go.Figure(go.Heatmap(z=[[1, 2]], colorscale="Blues"))
    fig.update_layout(title="Keys", yaxis=dict(autorange="reversed", title="Player"), xaxis=dict(range=[0, 3], dtick=1))
    fig_html(fig)
    assert fig.layout.yaxis.autorange == "reversed" and fig.layout.yaxis.title.text == "Player"
    assert tuple(fig.layout.xaxis.range) == (0, 3) and fig.layout.xaxis.dtick == 1
    assert fig.layout.xaxis.gridcolor == "#2a3344" and fig.data[0].colorscale[0][1] != fig.layout.xaxis.gridcolor


def test_fig_html_fallback_for_too_few_points():
    import plotly.graph_objects as go
    from dash.common import fig_html
    few = go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 2, 3]))
    assert fig_html(few, fallback="Too few farm kills yet for a trend.") == "<p class='section-note'>Too few farm kills yet for a trend.</p>"
    enough = go.Figure(go.Scatter(x=[1, 2, 3, 4], y=[1, 2, 3, 4]))
    assert fig_html(enough, fallback="Too few farm kills yet for a trend.").startswith("<figure class='chart'>")
    one_bar = go.Figure(go.Bar(x=["a"], y=[1]))
    assert fig_html(one_bar, fallback="x").startswith("<p class='section-note'>")
    assert fig_html(one_bar).startswith("<figure class='chart'>")   # no fallback, no skip


def test_css_has_no_legacy_component_rules_and_grid_uses_tokens():
    css = static_file("dash.css")
    for legacy in (".ps-box", ".ins-badge", ".card-value", ".tw ", "sorted-asc", "#13161c", "#171a21", "#2a2a1e", "#17281f", "#2a2410", "#173a25", "#3a1a1a", "#3d3512"):
        assert legacy not in css, legacy
    assert ".pull-box { display:block" in css and "var(--surface-card)" in css
    # controls carry the >= 3:1 control border, not the decorative one
    for sel in (".chip {", ".pull-box {", ".secnav a {", ".pull-detail .close {"):
        rule = css[css.index("\n" + sel) + 1:]
        rule = rule[:rule.index("}")]
        assert "border:1px solid var(--border-control)" in rule and "var(--border)" not in rule, sel
    # every disclosure keeps a visible marker (the flex summary drops the native one)
    assert "details > summary { list-style:none;" in css
    assert "details > summary::before { content:'\\25B8'" in css and "details[open] > summary::before { content:'\\25BE'" in css
    js = static_file("dash.js")
    assert "<p class='section-note'>" in js


def test_css_hex_only_in_class_and_parse_colours():
    css = static_file("dash.css")
    allowed = set(re.findall(r"\.p-[a-z]+\{color:(#[0-9a-fA-F]{6})", css))
    allowed |= set(re.findall(r"\.(?:DeathKnight|DemonHunter|Druid|Evoker|Hunter|Mage|Monk|Paladin|Priest|Rogue|Shaman|Warlock|Warrior)\{color:(#[0-9a-fA-F]{6})\}", css))
    stray = [h for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", css) if h not in allowed]
    assert not stray, stray


def test_boss_tab_headings_normalised():
    js = static_file("dash.js")
    assert "<h4" not in js and "<h5" not in js
    assert "<h2 class='panel-title'" in js
    assert "<nav class='secnav' aria-label='Sections'>" in js


def test_heading_levels_never_skip(bosses):
    html = build_html(bosses, _args())
    panels = re.findall(r"<section id='\w+' class='tab-panel.*?</section>", html, flags=re.S)
    assert panels
    for panel in panels:
        prev = None
        for m in re.finditer(r"<h([1-6])", panel):
            lvl = int(m.group(1))
            if prev is not None:
                assert lvl <= prev + 1, (panel[:80], prev, lvl, panel[max(0, m.start() - 120):m.start() + 60])
            prev = lvl


def test_empty_state_helper():
    from dash.common import empty_state
    assert empty_state("pulls", "nothing in <range>") == \
        "<div class='empty' role='status'><strong>No pulls</strong><span>nothing in &lt;range&gt;</span></div>"
    assert empty_state("kills", "why", "do <x>").endswith("<span class='action'>do &lt;x&gt;</span></div>")
    js = static_file("dash.js")
    assert "const emptyHtml = (what, why, action)" in js
    def body_of(fn):
        body = js[js.index(fn):]
        return body[:body.index("\n  }\n")]
    prep, util = body_of("function secPrep("), body_of("function secUtility(")
    for fn, body in (("secPrep", prep), ("secUtility", util)):
        assert "emptyHtml(" in body and "return '';" not in body, fn
    # each reason matches its condition: no categories configured / no buffs found / no extras bundle
    assert "if (!cats.length) return head + emptyHtml('consumable categories', 'none are configured (config/consumables.json)', '')" in prep
    assert "emptyHtml('consumable buffs', 'none were found in these pulls', '')" in prep
    assert "if (!S.some(p => p.hx)) return head + emptyHtml('interrupts or dispels', 'WCL returned no Interrupts/Dispels tables for these pulls', '')" in util
    assert "CombatantInfo events" not in util
    assert "<p class='muted'>No " not in js
    for name in ("home.py", "raid.py", "players.py", "mplus_tab.py"):
        with open(os.path.join(os.path.dirname(__file__), "..", "dash", name), encoding="utf-8") as f:
            assert "<p class='muted'>No " not in f.read(), name
    css = static_file("dash.css")
    assert ".empty { border:1px dashed var(--border)" in css


def test_js_empty_state_markup():
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    assert ctx.eval("emptyHtml('deaths', 'a <clean> pull', '')") == \
        "<div class='empty' role='status'><strong>No deaths</strong><span>a &lt;clean&gt; pull</span></div>"
    assert "<span class='action'>x</span>" in ctx.eval("emptyHtml('a', 'b', 'x')")


def test_title_only_explanations_are_visible():
    js = static_file("dash.js")
    assert "<td class='pat-${pat}' title='${escH(tip)}'>${pat}<span class='sub'>${escH(tip)}</span></td>" in js
    with open(os.path.join(os.path.dirname(__file__), "..", "dash", "mplus_tab.py"), encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"<td class='\{cls\}' data-sort='\{s\['qualifying'\]\}' title='\{esc\(tip\)\}' aria-label=", src)


def test_static_wiring_before_payload_inflation():
    js = static_file("dash.js")
    assert js.index("wireSort(document)") < js.index("await Promise.all")


def test_pull_grid_legend_is_section_note(bosses):
    html = build_html(bosses, _args())
    assert "<p class='section-note grid-legend'>" in html and "<span class='hint muted'>click a pull" in html
    assert "chip-hint" not in html


# ---------------- Task 11: status without colour ----------------
def _grid_pull(idx, pct, kill=False):
    return {"night": "Thu 2026-09-10", "kill": kill, "boss_percentage": pct, "fight_percentage": pct, "phase": "",
            "deaths": [], "duration_seconds": 120 + idx, "pull_time": f"20:{idx:02d}", "report_title": "r", "fight_id": idx,
            "absolute_start_ms": 1_000_000 + idx * 300_000, "report_code": "abc"}


def test_pull_grid_hp_bands_and_swatch_legend(monkeypatch):
    import dash.payload as payload
    monkeypatch.setattr(payload, "detect_breaks", lambda pulls: [])
    pulls = [_grid_pull(1, 80.0), _grid_pull(2, 25.0), _grid_pull(3, 4.2), _grid_pull(4, 0.0, kill=True)]
    out = payload.pull_grid(pulls, "tab9")
    for band in ("far", "mid", "near", "kill"):
        assert f"class='pull-box {band}'" in out
    legend = re.search(r"<p class='section-note grid-legend'>(.*?)</p>", out, flags=re.S).group(1)
    assert re.findall(r"<i class='swatch (\w+)' aria-hidden='true'></i> ([^<&]+?) (?:&middot;|<)", legend) == [
        ("kill", "Kill"), ("near", "Under 10 %"), ("mid", "10-40 %"), ("far", "40 % and more")]
    assert "#pull &middot; date and start time &middot; duration &middot; deaths" in legend
    assert "red = far" not in out and "style='border-left-color" not in out and "style='color:" not in out
    assert "class='compactGrid'" in out


def test_band_css_uses_one_mapping():
    css = static_file("dash.css")
    for band, tok in (("kill", "accent"), ("near", "good"), ("mid", "warn"), ("far", "bad")):
        assert f".pull-box.{band} {{ border-left-color:var(--{tok}); }}" in css
        assert f".pull-box.{band} .pb-pct {{ color:var(--{tok}); }}" in css
        assert f".swatch.{band} {{ background:var(--{tok}); }}" in css


def test_prep_cells_carry_glyph_and_word():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("prepCell(3, 8)") == \
        "<td class='prep-part' data-sort='0.375'><span aria-hidden='true'>&#9680;</span> 3/8<span class='sr-only'>partial</span></td>"
    assert ctx.eval("prepCell(8, 8)") == \
        "<td class='prep-ok' data-sort='1'><span aria-hidden='true'>&#10003;</span> 8/8<span class='sr-only'>ok</span></td>"
    assert ctx.eval("prepCell(0, 8)") == \
        "<td class='prep-fail' data-sort='0'><span aria-hidden='true'>&#10005;</span> 0/8<span class='sr-only'>missing</span></td>"
    assert "cell(e.have[i], e.pulls)" not in static_file("dash.js") and "prepCell(e.have[i], e.pulls)" in static_file("dash.js")


def test_avoidable_review_is_visible_tag():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("avoidCell(true, true)") == "<td class='avoid'>&#10003; <span class='tag warn'>review</span></td>"
    assert ctx.eval("avoidCell(true, false)") == "<td class='avoid'>&#10003;</td>"
    assert ctx.eval("avoidCell(false, false)") == "<td class='avoid'></td>"
    js = static_file("dash.js")
    assert "&#9888;'" not in js and "phaseIdx < 0) html += `<p class='note'>" not in js
    assert "if (review.length) html += `<p class='note'>" in js


# ---------------- Task 10: density defaults ----------------
def _js_body(js: str, fn: str) -> str:
    body = js[js.index(fn):]
    return body[:body.index("\n  }\n")]


def test_table_limit_markup():
    """tbl() with 42 rows and limit 10: 10 visible rows, 32 behind 'Show all 42', the limit carried on the table for re-sorting."""
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    out = ctx.eval("tbl([['Player', 'str'], ['DPS', 'num']], Array.from({length: 42}, (_, i) => `<tr data-player='p${i}'><td>p${i}</td><td>${i}</td></tr>`), 'output', '42 DPS', 10)")
    rows = re.findall(r"<tr[^>]*>", out.split("<tbody>")[1])
    assert len(rows) == 42
    assert sum("lowpart" not in r for r in rows) == 10 and sum("lowpart" in r for r in rows) == 32
    assert all("lowpart" not in r for r in rows[:10])
    assert out.count("class='show-all'") == 1 and ">Show all 42</button>" in out
    assert "<table class='sortable output' data-limit='10'>" in out
    # no limit, or not enough rows -> no data-limit
    assert "data-limit" not in ctx.eval("tbl([['a', 'str']], ['<tr><td>x</td></tr>'], '', '', 10)")
    assert "data-limit" not in ctx.eval("tbl([['a', 'str']], ['<tr><td>x</td></tr>'], '', '')")


def test_limit_reapplied_after_sort_and_rows_not_dimmed():
    js = static_file("dash.js")
    sort = _js_body(js, "function wireSort(")
    limit = _js_body(js, "function applyLimit(")
    assert "table.dataset.limit" in limit and "classList.toggle('lowpart'" in limit
    css = static_file("dash.css")
    rule = re.search(r"table\.show-low tr\.lowpart[^{]*\{([^}]*)\}", css)
    assert rule and "display:table-row" in rule.group(1) and "opacity" not in rule.group(1)
    # the player picked in the toolbar stays visible even past the limit
    assert "tr.lowpart.me" in css
    # "Hide tanks" re-runs the limit, counting only the rows it leaves visible
    assert "function applyLimit(table)" in js and "tr.classList.contains('role-tank')" in _js_body(js, "function applyLimit(")
    assert "applyLimit(table);" in sort
    toggles = _js_body(js, "function wireToggles(")
    assert "t.classList.toggle('hide-tanks', cb.checked); applyLimit(t);" in toggles


def test_output_caption_singular():
    js = static_file("dash.js")
    out = _js_body(js, "function secOutput(")
    assert "${rows.length === 1 ? ONE[role] : label}" in out and "healer: 'Healer'" in out


def test_density_limits_at_call_sites():
    js = static_file("dash.js")
    out = _js_body(js, "function secOutput(")
    call = out.split("'output', `${rows.length} ${rows.length === 1 ? ONE[role] : label}")
    assert len(call) == 2 and ", 10)" in call[1][:80], "one tbl() per role group, limit 10"
    for fn in ("function secOutput(", "function renderPlayersTab("):
        body = _js_body(js, fn) if fn != "function renderPlayersTab(" else js[js.index(fn):js.index("// deep links")]
        assert "lowLabel" not in body and "showLow" not in body and "lowgroup" not in body and "lowpart" not in body, fn
    assert "const lowLabel" not in js
    deaths = _js_body(js, "function secDeaths(")
    assert ", 15)" in deaths.split("<h3>Players</h3>")[1].split("<h3>First death, every pull</h3>")[0]
    taken = _js_body(js, "function secDamageTaken(")
    players_part = taken.split("<h3>Abilities</h3>")[0]
    assert ", 15)" in players_part.split("<h3>Players</h3>")[1]
    assert ", 12)" in taken.split("<h3>Abilities</h3>")[1]
    # Preparation and Interrupts & dispels: 15 players, like the other player tables
    for fn in ("function secPrep(", "function secUtility("):
        body = _js_body(js, fn)
        assert re.search(r"most missing first`, 15\)|counts per pull`, 15\)", body), fn
    # the Python-rendered participation checkbox (Players, Raid) still works
    assert "function wireToggles(" in js and "input.showLow" in js
    assert ".lowgroup.show-low tr.lowpart" in static_file("dash.css")


def test_secondary_tables_collapsed():
    js = static_file("dash.js")
    prog = _js_body(js, "function secProgress(")
    for head in ("<h3>Breaks</h3>", "<h3>Per raid night</h3>"):
        after = prog.split(head)[1]
        assert "<details class='table-view'><summary>Show as table</summary>" in after[:600], head
    phases = prog.split("<h3>Phases</h3>")[1]
    assert phases.count("<details class='table-view'><summary>Show as table</summary>") >= 1
    assert prog.count("<details class='table-view'><summary>Show as table</summary>") == 3
    assert "<details class='table-view' open" not in prog
    css = static_file("dash.css")
    summ = re.search(r"details\.table-view > summary \{([^}]*)\}", css).group(1)
    assert "color:var(--ink-dim)" in summ


def test_captions_do_not_repeat_headings():
    js = static_file("dash.js")
    prog = _js_body(js, "function secProgress(")
    assert "'', 'Breaks')" not in prog and "'', 'Per raid night')" not in prog
    raid = open(os.path.join(os.path.dirname(__file__), "..", "dash", "raid.py"), encoding="utf-8").read()
    assert 'caption="Night report"' not in raid
    for old in ("'First death of every pull'", "'Interrupts and dispels per player'", "'Consumables per player'", "`${P}'s deaths`", "`${G.player} per boss`"):
        assert old not in js, old
    # generic: no tbl() caption just restates the nearest <h2>/<h3> above it (template expressions and tags ignored)
    stop = {"of", "the", "a", "in", "and", "amp", "per", "player", "players", "every", "s"}
    words = lambda t: set(re.findall(r"[a-z0-9]+", re.sub(r"<[^>]+>|&\w+;|\$\{[^}]*\}", " ", t.lower())))
    checked = 0
    for m in re.finditer(r", (?:'[\w ]*'|`[^`]*`), ('[^']+'|`[^`]+`)(?:, \d+)?\)", js):
        if js.rfind("tbl(", 0, m.start()) < js.rfind("emptyHtml(", 0, m.start()):
            continue
        heads = list(re.finditer(r"<h([23])[^>]*>(.*?)</h\1>", js[:m.start()]))
        if not heads:
            continue
        hw, cw = words(heads[-1].group(2)), words(m.group(1)[1:-1])
        checked += 1
        assert not (hw and hw <= cw and cw - hw <= stop), (m.group(1), heads[-1].group(2))
    assert checked >= 12


def test_no_ineffective_sticky_thead():
    css = static_file("dash.css")
    rule = re.search(r"^thead th \{([^}]*)\}", css, flags=re.M).group(1)
    assert "sticky" not in rule and "var(--surface-raised)" in rule
    show = re.search(r"^\.show-all \{([^}]*)\}", css, flags=re.M).group(1)
    assert "min-height:32px" in show and "width:100%" in show and "var(--accent)" in show


def test_boxplot_cap():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    entries = "Array.from({length: 20}, (_, i) => ['p' + i, { per: [i, i + 1, i + 2] }])"
    top = ctx.eval(f"JSON.stringify(topByMedian({entries}, 15).map(e => e[0]))")
    assert json.loads(top) == [f"p{i}" for i in range(19, 4, -1)]
    assert ctx.eval(f"topByMedian({entries}, 15).length") == 15
    # the input is not reordered
    assert ctx.eval(f"(function(){{ var e = {entries}; topByMedian(e, 3); return e[0][0]; }})()") == "p0"
    assert ctx.eval("boxLayout(15).orientation") == "h"
    assert ctx.eval("boxLayout(15).height") == 24 * 15 + 80
    assert ctx.eval("boxLayout(3).height") == 320
    js = static_file("dash.js")
    out = _js_body(js, "function secOutput(")
    assert "type: 'box', x: e.per" in out and "orientation: BL.orientation" in out
    assert "15 of ${elig.length} players shown (highest median); the table above has everyone." in out


def test_line_chart_top6():
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    entries = "Array.from({length: 10}, (_, i) => ['p' + i, { per: [10 - i] }])"
    assert json.loads(ctx.eval(f"JSON.stringify(topByMedian({entries}, 6).map(e => e[0]))")) == [f"p{i}" for i in range(6)]
    assert ctx.eval(f"topByMedian({entries}.slice(0, 4), 6).length") == 4
    js = static_file("dash.js")
    out = _js_body(js, "function secOutput(")
    assert "topByMedian(elig, 6)" in out and "elig.slice(0, 10)" not in out
    assert "legend: { orientation: 'h', y: -0.2, yanchor: 'top' }" in out
    assert "top ${traces.length} DPS" in out


def _media_block(css: str, query: str) -> str:
    """The body of the first `@media <query> { ... }` block (brace-matched)."""
    start = css.index(query)
    i = css.index("{", start) + 1
    depth = 1
    j = i
    while depth:
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        j += 1
    return css[i:j - 1]


def test_toolbar_is_disclosure(bosses):
    html = build_html(bosses, _args())
    assert "<details class='filters' open><summary>Filters <span class='count' aria-live='polite'></span></summary><div class='controls'>" in html
    m = re.search(r"<div class='toolbar' role='region' aria-label='Global filters'><div class='wrap'>(.*?)</div></div>\s*<script type='application/json' id='tab_names'>", html, flags=re.S)
    assert m, "toolbar region missing or tab_names moved"
    bar = m.group(1)
    det = re.search(r"<details class='filters' open>.*?</details>", bar, flags=re.S).group(0)
    for ctl in ("id='gType'", "id='gNight'", "id='gPlayer'", "id='gClear'", "id='gWide'"):
        assert ctl in det, ctl
    assert "class='hint'" not in bar and "filters apply to every boss tab" not in html
    css = static_file("dash.css")
    mobile = _media_block(css, "@media (max-width:700px)")
    assert "details.filters" in mobile
    assert re.search(r"header\.page \.meta \{[^}]*display:none", mobile)
    assert re.search(r"\.kpis \{[^}]*grid-template-columns:1fr 1fr", mobile)
    # desktop: the summary is hidden, the controls lay out in a row
    desktop = css.replace(mobile, "")
    assert re.search(r"details\.filters > summary \{[^}]*display:none", desktop)
    assert re.search(r"\.controls \{[^}]*display:flex", desktop)
    assert not re.search(r"font-size:\s*\d+px", mobile) and not re.search(r"#[0-9a-fA-F]{3,8}\b", mobile)


def test_filter_count_and_mobile_collapse_js():
    js = static_file("dash.js")
    assert "active)" in js and ".count" in js
    assert re.search(r"matchMedia\('\(max-width:700px\)'\)\.matches\)\s*\w+\.open = false", js)


# ---------------- final review fixes ----------------
def test_tab_strip_wraps_and_nav_height_measured():
    """Final review 1: the desktop strip wraps (every boss tab visible) and --tabnav-h follows the measured nav."""
    css = static_file("dash.css")
    desktop = css.replace(_media_block(css, "@media (max-width:700px)"), "")
    rule = re.search(r"^\.tabs \{([^}]*)\}", desktop, flags=re.M).group(1)
    assert "flex-wrap:wrap" in rule and "overflow-x" not in rule and "scrollbar-width" not in rule
    assert "white-space:nowrap" in re.search(r"^\.tab-btn \{([^}]*)\}", css, flags=re.M).group(1)
    js = static_file("dash.js")
    assert "style.setProperty('--tabnav-h', nav.offsetHeight + 'px')" in js
    assert "new ResizeObserver(" in js and "window.addEventListener('resize', setNavH)" in js
    act = _js_body(js, "function activateTab(")
    assert "tabs.scrollWidth > tabs.clientWidth" in act and "scrollIntoView({ block: 'nearest', inline: 'nearest' })" in act
    # CSS fallbacks stay for the first paint
    assert "main { --tabnav-h:53px; }" in css


def test_payload_failure_isolated_per_tab():
    """Final review 2: one undecodable payload empties that tab only; the tab strip is wired before any await."""
    js = static_file("dash.js")
    start = js.index("await Promise.all(bossTabs.map(async tab => {")
    body = js[start:js.index("}));", start)]
    assert "try {" in body and "catch (err)" in body
    assert "emptyHtml('data for this boss', `the payload could not be decoded: ${" in body
    assert "classList.add('empty')" in body
    await_at = js.index("await Promise.all")
    for wiring in ("tabButtons.forEach(btn => btn.addEventListener('click', () => activateTab(",
                   "$('.tabs').addEventListener('keydown'",
                   "tabSelect.addEventListener('change'",
                   "diffBtns.forEach(b => b.addEventListener('click'"):
        assert js.index(wiring) < await_at, wiring
    assert "a failed load never leaves the strip unusable" not in open(
        os.path.join(os.path.dirname(__file__), "..", "docs", "CHANGES_2026-09-24.md"), encoding="utf-8").read()


def test_player_rows_carry_data_player():
    """Final review 3: every player row carries data-player, so tr.me (highlight + past the limit) matches."""
    js = static_file("dash.js")
    deaths = _js_body(js, "function secDeaths(")
    taken = _js_body(js, "function secDamageTaken(")
    parts = {
        "deaths players": deaths.split("<h3>Players</h3>")[1].split("<h3>First death, every pull</h3>")[0],
        "damage taken players": taken.split("<h3>Players</h3>")[1].split("<h3>Abilities</h3>")[0],
        "preparation": _js_body(js, "function secPrep("),
        "interrupts": _js_body(js, "function secUtility("),
        "players tab": js[js.index("function renderPlayersTab("):js.index("// deep links")].split("} else {")[1],
        "output": _js_body(js, "function secOutput("),
    }
    for name, src in parts.items():
        assert "<tr data-player='${escH(" in src or "<tr class='role-${role}' data-player='${escH(" in src, name
    render = _js_body(js, "function renderSelection(")
    me = [l for l in render.splitlines() if "classList.add('me')" in l][0]
    assert "tr.dataset.player === P" in me and ".player" in me and "td.textContent.trim() === P" not in me


def test_skip_rule_histogram_box_and_zero_bars():
    """Final review 4: histograms and box plots with < 4 values, and bars with < 2 non-zero categories, become sentences."""
    quickjs = pytest.importorskip("quickjs")
    ctx = _pure_chart_helpers(quickjs)
    assert ctx.eval("shouldSkipChart([{ type: 'histogram', x: [12, 40, 41] }])") is True
    assert ctx.eval("shouldSkipChart([{ type: 'histogram', x: [12, 40, 41, 90] }])") is False
    assert ctx.eval("shouldSkipChart([{ type: 'box', x: [1, 2] }, { type: 'box', x: [3, 4, 5] }])") is True
    assert ctx.eval("shouldSkipChart([{ type: 'box', x: [1, 2] }, { type: 'box', x: [3, 4, 5, 6] }])") is False
    # a phase chart whose first deaths all fell in one phase: one non-zero category
    assert ctx.eval("shouldSkipChart([{ type: 'bar', x: ['P1', 'P2', 'P3'], y: [2, 0, 0] }])") is True
    assert ctx.eval("shouldSkipChart([{ type: 'bar', x: ['P1', 'P2', 'P3'], y: [2, 1, 0] }])") is False


def test_deaths_and_box_charts_pass_fallbacks():
    js = static_file("dash.js")
    deaths = _js_body(js, "function secDeaths(")
    for title in ("First death - what did the damage", "First death - who", "First death - in which phase"):
        call = deaths[deaths.index(title):]
        call = call[:call.index("</div>")]
        assert "Fallback" in call or "fallback" in call.lower(), title
    assert deaths.count("firstsNote") >= 3 and "Only ${fds} in the selection; the table below lists them." in deaths
    assert "const fds = `${firsts.length} first death${firsts.length === 1 ? '' : 's'}`" in deaths
    taken = _js_body(js, "function secDamageTaken(")
    hist = taken[taken.index("When do avoidable hits land?"):]
    assert "avoidable hit" in hist[:hist.index(";\n")].split("300,")[1]
    out = _js_body(js, "function secOutput(")
    box = out[out.index("type: 'box'"):]
    assert "Fewer than four pulls per DPS player in the selection" in box[:box.index(";\n")]


def test_fig_html_has_no_plotly_default_template():
    import plotly.graph_objects as go
    from dash.common import fig_html
    out = fig_html(go.Figure(go.Bar(x=[1, 2], y=[2, 3])), height=200)
    # Plotly serialises template 'none' as a bare scatter stub; the default template carries per-type styles + #E5ECF6
    assert "#E5ECF6" not in out and '"barpolar"' not in out and '"template":{"data":{"scatter":[{"type":"scatter"}]}}' in out


def test_sorter_moves_only_direct_rows():
    """Final review 9: nested recap tables inside a cell are not pulled into the outer tbody by a sort."""
    sort = _js_body(static_file("dash.js"), "function wireSort(")
    assert "Array.from(tbody.rows).sort(" in sort and "tbody.querySelectorAll('tr')" not in sort


def test_fig_html_axes_keep_automargin():
    """Final fixes 2: template 'none' dropped the default template's axis automargin; fig_html sets it itself."""
    import plotly.graph_objects as go
    from dash.common import fig_html
    fig = go.Figure(go.Heatmap(z=[[1, 2]], y=["A-very-long-player-name"], x=["w1", "w2"]))
    out = fig_html(fig, height=200)
    lay = re.search(r'"xaxis":\{[^}]*\}', out).group(0), re.search(r'"yaxis":\{[^}]*\}', out).group(0)
    assert all('"automargin":true' in a for a in lay), lay
    assert '"hovermode":"closest"' in out


def test_py_skip_rule_counts_non_zero_bar_categories():
    """Python twin of shouldSkipChart: bars count only categories with a non-zero value."""
    import plotly.graph_objects as go
    from dash.common import should_skip_chart
    assert should_skip_chart(go.Figure(go.Bar(x=["P1", "P2", "P3"], y=[2, 0, 0]))) is True
    assert should_skip_chart(go.Figure(go.Bar(x=["P1", "P2", "P3"], y=[2, 1, 0]))) is False
    assert should_skip_chart(go.Figure([go.Bar(x=["a"], y=[1]), go.Bar(x=["b"], y=[1])])) is False
    assert should_skip_chart(go.Figure(go.Bar(x=["a"], y=[3]))) is True


# ---------------- Who pulled (plan 2026-09-29, Task B) ----------------

def _synthetic_pull(fid: int, pulled_by, night="Thu 2026-09-10", player="Omess", cls="DemonHunter") -> dict:
    """The smallest pull dict pull_grid() / pull_payload() accept (the offline fixture has no pulled_by yet)."""
    return {"report_code": "abc", "report_title": "Raid <night>", "night": night, "night_type": "main", "fight_id": fid,
            "kill": False, "boss_percentage": 55.0, "fight_percentage": 55.0, "duration_seconds": 120, "absolute_start_ms": 1000 * fid,
            "pull_time": "20:00", "participants": {player: cls, "Healbot": "Priest"}, "phase": "", "phase_timeline": [],
            "deaths": [], "damage_taken": [], "damage_done": [], "healing_done": [], "pulled_by": pulled_by}


def test_payload_emits_puller():
    pulls = [_synthetic_pull(1, {"player": "Omess", "class": "DemonHunter", "ability": "Throw Glaive", "offset_ms": 120,
                                 "kind": "damage", "via_pet": False}),
             _synthetic_pull(2, {"player": "Healbot", "class": "Priest", "ability": "Shadow Word: Pain", "offset_ms": -300,
                                 "kind": "cast", "via_pet": False}),
             _synthetic_pull(3, None)]
    del pulls[2]["pulled_by"]          # a pull from an older collector: key missing = unknown
    pulls.append(_synthetic_pull(4, None))
    _, text = pull_payload(pulls, "Boss", "Heroic", {}, compress=False)
    out = [p["pb"] for p in json.loads(text.replace("<\\/", "</"))["pulls"]]
    assert out == [["Omess", "Throw Glaive", 120, "d"], ["Healbot", "Shadow Word: Pain", -300, "c"], None, None]


def test_pull_grid_tooltip_names_puller():
    from dash.payload import pull_grid
    pulls = [_synthetic_pull(1, {"player": "O'Mess<x>", "class": "DemonHunter", "ability": "Throw Glaive", "offset_ms": 0,
                                 "kind": "damage", "via_pet": False}, player="O'Mess<x>"),
             _synthetic_pull(2, None)]
    grid = pull_grid(pulls, "tab1")
    titles = re.findall(r"title='(Pull #[^']*)'", grid)
    assert titles[0] == "Pull #1 - Raid &lt;night&gt; - fight 1 - pulled by O&#x27;Mess&lt;x&gt; - click to inspect"
    assert "pulled by" not in titles[1]
    assert "pulled by O&#x27;Mess&lt;x&gt;. Click to inspect" in grid


def _pb(name, ability="Throw Glaive", off=0, kind="d", cls="DemonHunter"):
    return {"pb": [name, ability, off, kind], "parts": {name: cls}}


def test_js_puller_rows():
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    pulls = [_pb("Zed"), _pb("Omess", "Throw Glaive"), _pb("Omess", "Fel Rush"), _pb("Omess", "Fel Rush"),
             _pb("Amy", "Frostbolt", cls="Mage"), {"pb": None, "parts": {}}, {"parts": {}}]
    r = json.loads(ctx.eval(f"JSON.stringify(pullerRows({json.dumps(pulls)}))"))
    assert r["total"] == 7 and r["unknown"] == 2 and r["unknownShare"] == 28.6
    # pulls desc, then name ascending (Amy before Zed at 1 pull each)
    assert [(x["name"], x["pulls"], x["share"]) for x in r["rows"]] == [("Omess", 3, 42.9), ("Amy", 1, 14.3), ("Zed", 1, 14.3)]
    assert r["rows"][0]["opener"] == "Fel Rush" and r["rows"][0]["openerCount"] == 2 and r["rows"][0]["cl"] == "DemonHunter"
    assert r["rows"][1]["cl"] == "Mage"
    empty = json.loads(ctx.eval("JSON.stringify(pullerRows([]))"))
    assert empty == {"rows": [], "unknown": 0, "unknownShare": 0, "total": 0}
    # opener ties are broken by name so the table is stable
    tie = json.loads(ctx.eval(f"JSON.stringify(pullerRows({json.dumps([_pb('A', 'b'), _pb('A', 'a')])}))"))
    assert tie["rows"][0]["opener"] == "a" and tie["rows"][0]["share"] == 100


def test_js_puller_matrix():
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    lists = [{"key": "tab0", "label": "Boss A (Heroic)", "pulls": [_pb("Omess"), _pb("Amy", cls="Mage"), {"pb": None, "parts": {}}]},
             {"key": "tab1", "label": "Boss B (Heroic)", "pulls": []},          # filtered to nothing: no column
             {"key": "tab2", "label": "Boss C (Mythic)", "pulls": [_pb("Amy", cls="Mage"), _pb("Amy", cls="Mage"), _pb("Omess")]}]
    m = json.loads(ctx.eval(f"JSON.stringify(pullerMatrix({json.dumps(lists)}))"))
    assert [c["key"] for c in m["cols"]] == ["tab0", "tab2"] and m["cols"][1]["label"] == "Boss C (Mythic)"
    assert [(r["name"], r["total"], r["counts"]) for r in m["rows"]] == [("Amy", 3, {"tab0": 1, "tab2": 2}), ("Omess", 2, {"tab0": 1, "tab2": 1})]
    assert m["rows"][0]["cl"] == "Mage"
    assert m["unknown"] == {"counts": {"tab0": 1}, "total": 1} and m["total"] == 6
    none = json.loads(ctx.eval("JSON.stringify(pullerMatrix([{key: 't', label: 'x', pulls: [{pb: null, parts: {}}]}]))"))
    assert none["rows"] == [] and none["unknown"]["total"] == 1 and none["total"] == 1
    assert m["participants"] == 2 and m["pullers"] == 2 and none["participants"] == 0 and none["pullers"] == 0
    # every participant gets a row, also without a pull: total 0, after the pullers, alphabetical among the zeros;
    # class = most frequent in their pulls (tie -> first seen); parts of unknown-puller pulls count too
    def pp(pb, parts):
        return {"pb": [pb, "Throw Glaive", 0, "d"] if pb else None, "parts": parts}
    lists2 = [{"key": "tab0", "label": "Boss A (Heroic)", "pulls": [
                  pp("Amy", {"Amy": "Mage", "Zoe": "Priest", "Bob": "Warrior", "Cat": "Druid"}),
                  pp("Amy", {"Amy": "Mage", "Zoe": "Paladin", "Bob": "Rogue"}),
                  pp(None, {"Amy": "Mage", "Zoe": "Paladin", "Dan": "Hunter"})]},
              {"key": "tab1", "label": "Boss B (Heroic)", "pulls": [pp("Cat", {"Cat": "Druid", "Bob": "Rogue", "Omess": "DemonHunter"})]}]
    m2 = json.loads(ctx.eval(f"JSON.stringify(pullerMatrix({json.dumps(lists2)}))"))
    assert [(r["name"], r["total"]) for r in m2["rows"]] == [("Amy", 2), ("Cat", 1), ("Bob", 0), ("Dan", 0), ("Omess", 0), ("Zoe", 0)]
    cl = {r["name"]: r["cl"] for r in m2["rows"]}
    assert cl == {"Amy": "Mage", "Cat": "Druid", "Bob": "Rogue", "Dan": "Hunter", "Omess": "DemonHunter", "Zoe": "Paladin"}
    tie = json.loads(ctx.eval("JSON.stringify(pullerMatrix([{key: 't', label: 'x', pulls: [{pb: null, parts: {X: 'Mage'}}, {pb: null, parts: {X: 'Priest'}}]}]))"))
    assert tie["rows"][0]["cl"] == "Mage"                                          # tie -> first seen
    zero = next(r for r in m2["rows"] if r["name"] == "Omess")
    assert zero["counts"] == {} and zero["total"] == 0
    assert m2["participants"] == 6 and m2["pullers"] == 2 and m2["total"] == 4 and m2["unknown"]["total"] == 1
    # column order: Player, Total (second, visible without scrolling), then the boss columns in tab order
    heads = json.loads(ctx.eval(f"JSON.stringify(pullerMatrixHeads({json.dumps(m['cols'])}))"))
    # short heads (first word + difficulty letter; no clash because the difficulties differ), full title as third element
    assert heads == [["Player", "str"], ["Total", "num"], ["Boss H", "num", "Boss A (Heroic)"], ["Boss M", "num", "Boss C (Mythic)"]]
    assert heads[1][0] == "Total"
    # tbl(): a third head element becomes the th title + the sort button's aria-label; two-element heads are unchanged
    html = ctx.eval(f"tbl({json.dumps(heads)}, [], 'pull-matrix', 'c')")
    assert "<th scope='col' data-type='num' class='right' title='Boss A (Heroic)'><button type='button' aria-label='Sort by Boss A (Heroic)'>Boss H</button></th>" in html
    assert "<th scope='col' data-type='num' class='right'><button type='button' aria-label='Sort by Total'>Total</button></th>" in html


REAL_TITLES = {"Nek'zali the Soulcoiler": "Nek'zali", "Entombed Sentinels": "Entombed", "Vashnik the Malignant": "Vashnik",
               "The Lost Explorers": "Lost", "Sszorak": "Sszorak", "The Twin Fangs": "Twin", "The Coiled Altar": "Coiled", "Ula'tek": "Ula'tek"}


def test_js_short_boss_head():
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    short = lambda t, w=1: ctx.eval(f"shortBossHead({json.dumps(t)}, {w})")
    cases = {"The Coiled Altar (Heroic)": "Coiled H", "The Twin Fangs (Normal)": "Twin N", "Ula'tek (Heroic)": "Ula'tek H",
             "Entombed Sentinels (Heroic)": "Entombed H", "The Lost Explorers (Normal)": "Lost N", "Vashnik the Malignant (Heroic)": "Vashnik H",
             "Sszorak (Normal)": "Sszorak N", "Nek'zali the Soulcoiler (Normal)": "Nek'zali N", "Nek'zali the Soulcoiler (Mythic)": "Nek'zali M",
             "Some Boss (LFR)": "Some L", "Supercalifragilistic (Heroic)": "Supercali. H", "No Difficulty": "No"}
    assert {t: short(t) for t in cases} == cases
    # two words skip filler words and abbreviate long second words
    assert short("The Twin Fangs (Normal)", 2) == "Twin Fangs N" and short("Nek'zali the Soulcoiler (Heroic)", 2) == "Nek'zali S. H"
    # the 16 real columns: no collisions, so every head is one word + difficulty letter
    titles = [f"{n} ({d})" for d in ("Normal", "Heroic") for n in REAL_TITLES]
    heads = json.loads(ctx.eval(f"JSON.stringify(shortBossHeads({json.dumps(titles)}))"))
    assert heads == [f"{REAL_TITLES[n]} {d[0]}" for d in ("Normal", "Heroic") for n in REAL_TITLES]
    assert len(set(heads)) == 16 and max(map(len, heads)) <= 12
    # collisions: same first word -> two words (only for the clashing titles), abbreviated when long
    col = json.loads(ctx.eval("JSON.stringify(shortBossHeads(['Entombed Sentinels (Heroic)', 'Entombed Kings (Heroic)', 'Entombed Sentinels (Normal)', 'Sszorak (Heroic)']))"))
    assert col == ["Entombed S. H", "Entombed Kings H", "Entombed N", "Sszorak H"]
    # abbreviations still clash -> unabbreviated second words; identical names -> full titles
    col2 = json.loads(ctx.eval("JSON.stringify(shortBossHeads(['Entombed Sentinels (Heroic)', 'Entombed Spirits (Heroic)']))"))
    assert col2 == ["Entombed Sentinels H", "Entombed Spirits H"]
    same = json.loads(ctx.eval("JSON.stringify(shortBossHeads(['Twin Fangs (Heroic)', 'The Twin Fangs (Heroic)']))"))
    assert same == ["Twin Fangs (Heroic)", "The Twin Fangs (Heroic)"]


def test_js_all_pull_rows():
    quickjs = pytest.importorskip("quickjs")
    ctx = _table_helpers(quickjs)
    lists = [{"key": "tab0", "label": "Boss A (Heroic)", "pulls": [{"i": 1, "a": 3000}, {"i": 2, "a": 5000}]},
             {"key": "tab1", "label": "Boss B (Heroic)", "pulls": []},
             {"key": "tab2", "label": "Boss C (Mythic)", "pulls": [{"i": 2, "a": 1000}, {"i": 1, "a": 1000}, {"i": 3, "a": 3000}]}]
    rows = json.loads(ctx.eval(f"JSON.stringify(allPullRows({json.dumps(lists)}))"))
    # chronological across bosses; same start: tab order (tab0 before tab2), then pull number
    assert [(r["tab"], r["p"]["i"]) for r in rows] == [("tab2", 1), ("tab2", 2), ("tab0", 1), ("tab2", 3), ("tab0", 2)]
    assert rows[0]["label"] == "Boss C (Mythic)" and set(rows[0]) == {"tab", "label", "p"}
    assert json.loads(ctx.eval("JSON.stringify(allPullRows([]))")) == []
    assert json.loads(ctx.eval("JSON.stringify(allPullRows([{key: 't', label: 'x', pulls: []}]))")) == []


def test_who_pulled_wired_into_boss_and_players_tab():
    js = static_file("dash.js")
    assert "<h3>Who pulled</h3>${whoPulledHtml(S)}" in js                       # boss tab Summary, from the selected pulls
    assert "['Pulled by', 'str']" in js and "${pulledByCell(p)}" in js            # pull table column
    assert js.count("whoPullsFirstHtml(") == 4                                    # definition + unfiltered + player + night views
    assert "whoPullsFirstHtml(p => nightOk(p) && G.player in p.parts)" in js and "whoPullsFirstHtml(nightOk)" in js
    assert "tbl(pullerMatrixHeads(m.cols), rows, 'pull-matrix'," in js            # Total second, sticky Player column
    assert "</td>${cell(e.total)}${m.cols.map(" in js                             # row cells follow the header order; 0 -> muted dash, data-sort 0
    assert "const cell = n => `<td data-sort='${n || 0}'>${n ? n : \"<span class='muted'>-</span>\"}</td>`;" in js
    assert "`${m.pullers} of ${m.participants} player${m.participants === 1 ? '' : 's'} started ${m.total - m.unknown.total} of ${m.total} boss pull" in js
    assert "if (!m.pullers) return html + emptyHtml('puller data'," in js          # empty state still keyed on pullers
    # "All pulls" table under the matrix, same keep predicate in all three views, shared row cells with the pull table
    assert js.count("allPullsHtml(") == 4
    assert "whoPullsFirstHtml(() => true) + allPullsHtml(() => true)" in js
    assert "allPullsHtml(p => nightOk(p) && G.player in p.parts)" in js and "allPullsHtml(nightOk)" in js
    assert "<h2 id='sec_tabPlayers_allpulls'>All pulls</h2>" in js
    assert "tbl([['Boss', 'str'], ['Night', 'str'], ['Pull', 'num']].concat(PULL_CELL_HEADS)," in js
    assert "tbl([['Pull', 'num'], ['Night', 'str']].concat(PULL_CELL_HEADS)," in js
    assert js.count("${pullCells(p)}</tr>") == 2 and js.count("${pulledByCell(p)}") == 1
    assert "class='gotab linklike' data-tab='${tab}'>${escH(label)}</button>" in js
    css = static_file("dash.css")
    assert "table.pull-matrix th:first-child, table.pull-matrix td:first-child { position:sticky; left:0;" in css
    assert "table.pull-matrix th, table.pull-matrix td { padding-left:var(--sp-1); padding-right:var(--sp-2); }" in css   # 16 columns fit 1440 px
    assert "tbl(pullerMatrixHeads(m.cols)" in js and "N / H / M = Normal / Heroic / Mythic" in js
