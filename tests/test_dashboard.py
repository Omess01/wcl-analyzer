"""The HTML build: payload round-trip, structure, and JS syntax."""

import base64
import gzip
import json
import os
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


@pytest.mark.xfail(strict=False, reason="dash.css is rewritten onto the type scale in Task 8")
def test_css_uses_type_scale():
    css = static_file("dash.css")
    assert not re.search(r"font-size:\s*\d+px", css), "raw px font sizes; use var(--fs-*)"
