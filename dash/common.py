"""Helpers shared by every tab renderer."""

import html
import json
import os
import re
from collections import Counter, defaultdict

import plotly.graph_objects as go

from collect_data import normalize, busy_ms_between
from path import CONFIG_DIR, DATA_DIR

AVOIDABLE_FILE = os.path.join(CONFIG_DIR, "avoidable.json")
MPLUS_FILE = os.path.join(DATA_DIR, "mplus_history.json")
TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "tokens.css")
REQUIRED_TOKENS = frozenset({
    "surface-page", "surface-card", "surface-raised", "border", "border-strong", "border-control", "ink", "ink-dim",
    "accent", "on-accent", "good", "warn", "bad",
    "series-1", "series-1-rgb", "series-2", "series-3", "series-4", "series-5", "series-6",
    "font", "font-num",
})


def load_tokens() -> dict[str, str]:
    """Design values from tokens.css: {'accent': <value as written in tokens.css>, ...}. The CSS file is the only source of truth."""
    with open(TOKENS_FILE, encoding="utf-8") as f:
        text = f.read()
    toks = {name: value.strip() for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", text)}
    missing = sorted(REQUIRED_TOKENS - toks.keys())
    if missing:
        raise ValueError(f"tokens.css is missing: {', '.join(missing)}")
    return toks

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"
TOKENS = load_tokens()
CHART_BG = "rgba(0,0,0,0)"
SERIES = [TOKENS[f"series-{i}"] for i in range(1, 7)]
# series are never told apart by hue alone: cycle dash styles and marker symbols too
LINE_DASHES = ["solid", "dash", "dot", "dashdot"]
MARKERS = ["circle", "square", "diamond", "triangle-up", "x", "star"]


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def esc(text) -> str:
    return html.escape(str(text))


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def fmt_num(n: float) -> str:
    if n >= 1e9: return f"{n / 1e9:.2f}B"
    if n >= 1e6: return f"{n / 1e6:.2f}M"
    if n >= 1e3: return f"{n / 1e3:.1f}k"
    return f"{n:.0f}"


def result_label(p: dict) -> str:
    return "KILL" if p["kill"] else f"{p['boss_percentage']:.1f}%"


def hp_band(pct: float, kill: bool = False) -> str:
    """Status band of a pull: 'kill'; boss HP left < 10 -> 'near'; < 40 -> 'mid'; else 'far'.
    Twin of hpBand() in dash/static/dash.js - change both together."""
    if kill:
        return "kill"
    return "near" if pct < 10 else "mid" if pct < 40 else "far"


def median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2] if s else 0.0


def parse_class(pct: float) -> str:
    if pct >= 100: return "p-art"
    if pct >= 99: return "p-leg"
    if pct >= 95: return "p-ora"
    if pct >= 75: return "p-pur"
    if pct >= 50: return "p-blu"
    if pct >= 25: return "p-gre"
    return "p-gra"


def json_for_script(obj) -> str:
    """JSON safe to embed inside a <script> element."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


# --------------------------------------------------------------------------
# Avoidable-damage config
# --------------------------------------------------------------------------

def load_avoidable() -> dict:
    """
    avoidable.json format:
      {
        "Ula'tek": ["Caustic Waves", "Acidic Burst"],   # avoidable, per boss
        "*": ["Falling"],                              # avoidable on every boss
        "_ignore": ["Fel Armor", "Burning Rush"]       # trinket / enchant effects - excluded from damage stats
      }
    Keys starting with "_" other than _ignore are treated as comments.
    Returns {normalized_boss: {normalized_ability}} plus an "_ignore" set.
    """
    if not os.path.exists(AVOIDABLE_FILE):
        return {}
    with open(AVOIDABLE_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    # "*" (every boss) must survive normalisation - normalize("*") would be ""
    cfg = {("*" if boss.strip() == "*" else normalize(boss)): {normalize(a) for a in abilities}
           for boss, abilities in raw.items()
           if isinstance(abilities, list) and not boss.startswith("_")}
    cfg["_ignore"] = {normalize(a) for a in raw.get("_ignore", []) if isinstance(a, str)}
    return cfg


def avoidable_set(config: dict, boss_name: str) -> set:
    return config.get(normalize(boss_name), set()) | config.get("*", set())


def ignore_set(config: dict) -> set:
    return config.get("_ignore", set())


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

TANK_SPECS = {"Protection", "Blood", "Vengeance", "Guardian", "Brewmaster"}
HEALER_SPECS = {"Holy", "Discipline", "Restoration", "Mistweaver", "Preservation"}


def spec_role(spec: str) -> str:
    if spec in TANK_SPECS:
        return "tank"
    if spec in HEALER_SPECS:
        return "healer"
    return "dps"


def pull_specs(p: dict) -> dict:
    """name -> spec for ONE pull, from WCL's damage/healing tables (healing table wins for healers)."""
    specs: dict[str, str] = {}
    for e in (p.get("damage_done") or []):
        if e.get("spec"):
            specs[e["name"]] = e["spec"]
    for e in (p.get("healing_done") or []):
        if e.get("spec") and spec_role(e["spec"]) == "healer":
            specs[e["name"]] = e["spec"]
    return specs


def player_roles(pulls: list[dict]) -> dict:
    """name -> dominant role across these pulls ('tank' | 'healer' | 'dps')."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for p in pulls:
        for name, spec in pull_specs(p).items():
            counts[name][spec_role(spec)] += 1
    return {name: c.most_common(1)[0][0] for name, c in counts.items()}


def player_role_labels(pulls: list[dict]) -> dict:
    """name -> 'healer' or, for flex players, 'healer 29 / dps 20'."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for p in pulls:
        for name, spec in pull_specs(p).items():
            counts[name][spec_role(spec)] += 1
    out = {}
    for name, c in counts.items():
        if len(c) == 1:
            out[name] = next(iter(c))
        else:
            out[name] = " / ".join(f"{r} {n}" for r, n in c.most_common())
    return out


# --------------------------------------------------------------------------
# HTML building blocks
# --------------------------------------------------------------------------

_TR_SPLIT = re.compile(r"(?=<tr[\s>])")
_TR_CLASS = re.compile(r"^<tr([^>]*?)\bclass=(?:'([^']*)'|\"([^\"]*)\"|([^\s>'\"]+))")


def _lowpart(row: str) -> str:
    """Add class 'lowpart' to a row's <tr> (merging with an existing class attribute)."""
    m = _TR_CLASS.match(row)
    if m:
        existing = next(g for g in m.groups()[1:] if g is not None)
        return f"<tr{m.group(1)}class='{existing} lowpart'" + row[m.end():]
    return "<tr class='lowpart'" + row[3:] if row.startswith("<tr") else row


def table(headers: list[tuple[str, str]], rows_html: str | list[str], extra_class: str = "", caption: str = "",
          limit: int | None = None) -> str:
    """
    headers: (label, type) with type 'num' (right-aligned, numeric sort), 'str' (text sort) or 'none' (not sortable).
    Sortable headers hold a <button> so keyboard users get a real control; numeric cells should carry class='right'.
    rows_html: one string of <tr> rows or a list of row strings (joined). caption is a visible title row.
    limit: when set and there are more rows, rows after the first `limit` get class 'lowpart' (hidden) and the
    scroller ends with a 'Show all N' button. A string is split on <tr boundaries for this, so pass a list when
    rows contain nested tables.
    """
    ths = ""
    for h, t in headers:
        cls_attr = " class='right'" if t == "num" else ""
        if t == "none":
            ths += f"<th scope='col' data-type='none'{cls_attr}>{esc(h)}</th>"
        else:
            ths += f"<th scope='col' data-type='{t}'{cls_attr}><button type='button' aria-label='Sort by {esc(h)}'>{esc(h)}</button></th>"
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    more = limit_attr = ""
    if limit is not None:
        rows = [r for r in _TR_SPLIT.split(rows_html) if r] if isinstance(rows_html, str) else list(rows_html)
        if len(rows) > limit:
            rows = rows[:limit] + [_lowpart(r) for r in rows[limit:]]
            more = f"<button type='button' class='show-all' aria-expanded='false'>Show all {len(rows)}</button>"
            limit_attr = f" data-limit='{limit}'"   # wireSort() re-applies the limit after a sort
        rows_html = "".join(rows)
    elif not isinstance(rows_html, str):
        rows_html = "".join(rows_html)
    return (f"<div class='scroller'><table class='sortable {extra_class}'{limit_attr}>{cap}<thead><tr>{ths}</tr></thead>"
            f"<tbody>{rows_html}</tbody></table>{more}</div>")


def kpis(items: list[tuple], extra_class: str = "", raw: bool = False) -> str:
    """KPI tiles. items: (label, value) or (label, value, tile_class). Values escaped unless raw=True."""
    out = f"<dl class='kpis{(' ' + extra_class) if extra_class else ''}'>"
    for item in items:
        label, value = item[0], item[1]
        tile = f" {item[2]}" if len(item) > 2 and item[2] else ""
        val = str(value) if raw else esc(value)
        out += f"<div class='kpi{tile}'><dt>{esc(label)}</dt><dd>{val}</dd></div>"
    return out + "</dl>"


def section_note(text_html: str) -> str:
    return f"<p class='section-note'>{text_html}</p>"


def empty_state(what: str, why: str, action: str = "") -> str:
    """Shared empty state (mirrors emptyHtml() in dash.js): 'No {what}', the reason, an optional next step."""
    act = f"<span class='action'>{esc(action)}</span>" if action else ""
    return f"<div class='empty' role='status'><strong>No {esc(what)}</strong><span>{esc(why)}</span>{act}</div>"


def gotab(tab_id: str, text: str, cls: str = "linklike") -> str:
    return f"<button type='button' class='gotab {cls}' data-tab='{esc(tab_id)}'>{text}</button>"


ROLE_LABEL = {"dps": "DPS", "healer": "Healer", "tank": "Tank"}


def class_label(cls: str) -> str:
    """WCL class ids are CamelCase ('DemonHunter'); shown as words ('Demon Hunter'). Mirrors clsLabel in dash.js."""
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", str(cls))


def player_cell(name: str, cls: str, role: str = "", spec: str = "") -> str:
    """Table cell body for a player: class-coloured name, role tag, spec line (each part optional)."""
    out = f"<span class='player {esc(str(cls).replace(' ', ''))}'>{esc(name)}</span>"
    if role:
        out += f"<span class='role'>{esc(ROLE_LABEL.get(role, role.capitalize()))}</span>"
    if spec:
        out += f"<br><span class='spec'>{esc(spec)}{(' ' + esc(class_label(cls))) if cls and not spec.endswith(str(cls)) else ''}</span>"
    return out


def should_skip_chart(fig: go.Figure) -> bool:
    """Same rule as dash.js shouldSkipChart: nothing to compare when every trace is a bar and fewer than 2
    categories have a non-zero value, or when every other trace has fewer than 4 points."""
    traces = list(fig.data)
    if not traces:
        return True
    if all(t.type == "bar" for t in traces):
        cats = set()
        for t in traces:
            ys = list(t.y) if t.y is not None else None
            cats.update(x for i, x in enumerate(t.x if t.x is not None else ()) if ys is None or (i < len(ys) and ys[i]))
        return len(cats) < 2
    return all(len(t.x if t.x is not None else (t.y if t.y is not None else ())) < 4 for t in traces if t.type != "bar")


def fig_html(fig: go.Figure, height: int = 380, div_id: str | None = None, fallback: str | None = None) -> str:
    """Plotly figure in the same card <figure> as the SVG chart; the Plotly title moves into the <h3>.
    With a fallback sentence, a figure with nothing to compare (should_skip_chart) becomes that sentence."""
    if fallback and should_skip_chart(fig):
        return section_note(esc(fallback))
    title = str(fig.layout.title.text) if fig.layout.title and fig.layout.title.text else ""
    # update_layout merges: axis titles, ranges and autorange set by the caller survive; template 'none' drops
    # Plotly's light default template (#E5ECF6 bar outlines, white axis lines, ~10 KB per chart)
    fig.update_layout(title=None, template="none", paper_bgcolor=CHART_BG, plot_bgcolor=CHART_BG, height=height, colorway=SERIES,
                      font=dict(color=TOKENS["ink"], family=TOKENS["font"]),
                      hovermode="closest",   # template 'none' also drops the default template's automargin / hovermode
                      xaxis=dict(gridcolor=TOKENS["border"], zerolinecolor=TOKENS["border"], automargin=True),
                      yaxis=dict(gridcolor=TOKENS["border"], zerolinecolor=TOKENS["border"], automargin=True),
                      legend=dict(font=dict(color=TOKENS["ink-dim"])))
    if not getattr(fig.layout.margin, "t", None):
        fig.update_layout(margin=dict(l=40, r=20, t=20, b=40))
    kwargs = dict(full_html=False, include_plotlyjs=False,
                  config={"displayModeBar": False, "responsive": True, "displaylogo": False})
    if div_id:
        kwargs["div_id"] = div_id
    try:
        body = fig.to_html(**kwargs)
    except TypeError:  # very old plotly without div_id
        kwargs.pop("div_id", None)
        body = fig.to_html(**kwargs)
    head = f"<div class='chart-head'><h3>{esc(title)}</h3></div>" if title else ""
    return f"<figure class='chart'>{head}<div class='plot' style='--h:{int(height)}px'>{body}</div></figure>"


# --------------------------------------------------------------------------
# Pull-level helpers
# --------------------------------------------------------------------------

def break_minutes() -> float:
    try:
        return float(os.getenv("BREAK_MINUTES", "4.5"))
    except ValueError:
        return 4.5


def detect_breaks(pulls: list[dict]) -> list[dict]:
    """
    Gaps between consecutive pulls on the same night longer than BREAK_MINUTES
    of IDLE time (trash / other bosses fought inside the gap don't count).
    Returns [{after: 1-based pull# before the break, gap_min, busy_min, night, resume_time, before, after_pulls}].
    """
    thr = break_minutes()
    out = []
    for i in range(1, len(pulls)):
        prev, nxt = pulls[i - 1], pulls[i]
        if prev["night"] != nxt["night"]:
            continue
        prev_end = prev["absolute_start_ms"] + prev["duration_seconds"] * 1000
        gap = (nxt["absolute_start_ms"] - prev_end) / 60000
        busy = busy_ms_between(prev["night"], prev_end, nxt["absolute_start_ms"]) / 60000
        idle = gap - busy
        if idle >= thr:
            same_night = [p for p in pulls if p["night"] == prev["night"]]
            k = same_night.index(prev)
            out.append({
                "after": i, "gap_min": idle, "busy_min": busy, "night": prev["night"], "resume_time": nxt["pull_time"],
                "before": same_night[max(0, k - 4):k + 1], "after_pulls": same_night[k + 1:k + 6],
            })
    return out


def all_pulls(bosses: dict) -> list[dict]:
    out = []
    for (name, diff), pulls in bosses.items():
        for p in pulls:
            q = dict(p)
            q["boss"] = f"{name} ({diff})"
            out.append(q)
    out.sort(key=lambda p: p["absolute_start_ms"])
    return out


def filter_bosses_by_type(bosses: dict, night_type: str | None) -> dict:
    if not night_type:
        return bosses
    out = {}
    for key, pulls in bosses.items():
        kept = [p for p in pulls if p.get("night_type", "main") == night_type]
        if kept:
            out[key] = kept
    return out


def regulars(pulls: list[dict]) -> set:
    counts = Counter(name for p in pulls for name in p["participants"])
    top = max(counts.values(), default=0)
    return {n for n, c in counts.items() if c >= 0.5 * top}


def player_stats(pulls: list[dict], avoidable: set | None = None) -> dict:
    """name -> {class, pulls, first_deaths, causes(Counter of first-death contributors), avoid_hits}"""
    avoidable = avoidable or set()
    stats: dict[str, dict] = {}

    def get(name, cls):
        return stats.setdefault(name, {"class": cls, "pulls": 0, "first_deaths": 0, "avoid_hits": 0, "causes": Counter()})

    for p in pulls:
        for name, cls in p["participants"].items():
            get(name, cls)["pulls"] += 1
        if p["deaths"]:
            d = p["deaths"][0]
            s = get(d["player"], d["class"])
            s["first_deaths"] += 1
            s["causes"][d.get("top_contributor", d["ability"])] += 1
        if avoidable:
            for dmg in p["damage_taken"]:
                if normalize(dmg["ability"]) in avoidable:
                    get(dmg["player"], dmg["class"])["avoid_hits"] += dmg["hits"]
    return stats


def night_stats(night: str, ps: list[dict]) -> dict:
    """Per-night efficiency numbers shared by Home and the Raid tab: combat, trash, idle, span, pulls/hour, prep share."""
    from collect_data import NIGHT_FIGHTS
    ps = sorted(ps, key=lambda p: p["absolute_start_ms"])
    combat = sum(p["duration_seconds"] for p in ps)
    start = ps[0]["absolute_start_ms"]
    end = ps[-1]["absolute_start_ms"] + ps[-1]["duration_seconds"] * 1000
    span = (end - start) / 1000
    trash = sum((e - a) / 1000 for a, e, is_boss in NIGHT_FIGHTS.get(night, []) if not is_boss and a >= start and e <= end)
    idle = max(span - combat - trash, 0)
    flags = [c for p in ps for c in (p.get("consumables") or {}).values() if "flask" in c and "food" in c]
    prep = (sum(1 for c in flags if c["flask"] and c["food"]) / len(flags)) if flags else None
    return {"combat": combat, "trash": trash, "idle": idle, "span": span, "idle_share": idle / span if span else 0.0,
            "pph": len(ps) / (span / 3600) if span else 0.0, "prep": prep}


def boss_status(pulls: list[dict]) -> dict:
    kills = [p for p in pulls if p["kill"]]
    wipes = [p for p in pulls if not p["kill"]]
    prog = pulls
    for i, p in enumerate(pulls):
        if p["kill"]:
            prog = pulls[:i + 1]
            break
    return {
        "killed": bool(kills), "kills": len(kills), "pulls": len(pulls), "prog_pulls": len(prog),
        "first_kill": kills[0]["night"] if kills else None,
        "best": 0.0 if kills else (min(p["boss_percentage"] for p in wipes) if wipes else 100.0),
        "last_night": pulls[-1]["night"] if pulls else None,
    }
