"""Helpers shared by every tab renderer."""

import html
import json
import os
from collections import Counter, defaultdict

import plotly.graph_objects as go

from collect_data import normalize, busy_ms_between

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AVOIDABLE_FILE = os.path.join(HERE, "avoidable.json")
MPLUS_FILE = os.path.join(HERE, "mplus_history.json")

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"
CHART_TEMPLATE = "plotly_dark"
CHART_BG = "rgba(0,0,0,0)"
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


def pct_color(pct: float) -> str:
    """Red at 100% HP left -> yellow -> green near 0%."""
    t = max(0.0, min(1.0, pct / 100.0))
    r = int(60 + 160 * t)
    g = int(180 - 120 * t)
    return f"rgb({r},{g},70)"


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

def table(headers: list[tuple[str, str]], rows_html: str, extra_class: str = "", caption: str = "") -> str:
    """headers: list of (label, type) where type is 'num' or 'str' for sorting. Wrapped for horizontal scrolling."""
    ths = "".join(f"<th scope='col' data-type='{t}' tabindex='0' aria-sort='none'>{esc(h)}</th>" for h, t in headers)
    cap = f"<caption class='sr-only'>{esc(caption)}</caption>" if caption else ""
    return (
        f"<div class='tw'><table class='sortable {extra_class}'>{cap}<thead><tr>{ths}</tr></thead>"
        f"<tbody>{rows_html}</tbody></table></div>"
    )


def cards(items: list[tuple[str, object]]) -> str:
    out = "<div class='cards'>"
    for label, value in items:
        out += f"<div class='card'><div class='card-value'>{esc(value)}</div><div class='card-label'>{esc(label)}</div></div>"
    return out + "</div>"


def gotab(tab_id: str, text: str, cls: str = "linklike") -> str:
    return f"<button type='button' class='gotab {cls}' data-tab='{esc(tab_id)}'>{text}</button>"


def fig_html(fig: go.Figure, height: int = 380, div_id: str | None = None) -> str:
    fig.update_layout(template=CHART_TEMPLATE, paper_bgcolor=CHART_BG, plot_bgcolor=CHART_BG, height=height)
    if not getattr(fig.layout.margin, "t", None):
        fig.update_layout(margin=dict(l=40, r=20, t=50, b=40))
    kwargs = dict(full_html=False, include_plotlyjs=False, config={"responsive": True, "displaylogo": False})
    if div_id:
        kwargs["div_id"] = div_id
    try:
        return fig.to_html(**kwargs)
    except TypeError:  # very old plotly without div_id
        kwargs.pop("div_id", None)
        return fig.to_html(**kwargs)


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
