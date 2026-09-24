"""tokens.css is the only place design values live; Python and JS read it."""

import pytest

from dash.common import load_tokens, REQUIRED_TOKENS


def test_load_tokens_has_required_keys():
    toks = load_tokens()
    for key in REQUIRED_TOKENS:
        assert key in toks, key
    assert toks["accent"] == "#c9a227"
    assert toks["series-1-rgb"] == "57,135,229"
    assert toks["font"].startswith("ui-sans-serif")


def test_load_tokens_reports_missing(tmp_path, monkeypatch):
    import dash.common as common
    bad = tmp_path / "tokens.css"
    bad.write_text(":root { --accent: #c9a227; }", encoding="utf-8")
    monkeypatch.setattr(common, "TOKENS_FILE", str(bad))
    with pytest.raises(ValueError) as exc:
        load_tokens()
    assert "ink-dim" in str(exc.value)


# --- contrast (WCAG 2.x relative luminance) ---------------------------------

def _lum(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_tokens_contrast():
    t = load_tokens()
    for surface in ("surface-card", "surface-raised"):
        for text in ("ink", "ink-dim", "accent", "good", "warn", "bad"):
            assert _ratio(t[text], t[surface]) >= 4.5, f"{text} on {surface}: {_ratio(t[text], t[surface]):.2f}"
    # interactive control boundaries (chips, pull boxes, tab buttons) need 3:1 against the card
    assert _ratio(t["border-control"], t["surface-card"]) >= 3.0
    # series colours are mark colours: 3:1 on the card is enough, they are never used as text on raised
    for i in range(1, 7):
        assert _ratio(t[f"series-{i}"], t["surface-card"]) >= 3.0, f"series-{i}"
