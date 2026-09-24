"""
Collects everything the dashboard needs and groups it as
{ (boss_name, difficulty_name): [pull, pull, ...] }.

Per pull we know: result, boss % and fight %, duration, when it happened,
who participated, every death (who / when / killing blow / what really did
the damage / defensives cast before the first death), damage taken per
player x ability, damage/healing done, interrupts, dispels, consumables at
pull start and - where WCL provides phase data - when each phase was
reached and which phase the pull ended in.

Filters (mirroring WCL's Multiple Report Analysis selection UI):
  - difficulties        Heroic / Mythic / Normal / LFR
  - zone                only reports from a given raid (e.g. "Manaforge")
  - boss                only one boss
  - player              only pulls that player participated in
  - progression_only    only pulls up to and including the first kill

Report-specific queries go through the cache; only new reports hit the API.
Fights are fetched from a small thread pool; per-fight tables are batched
with GraphQL aliases (several fights per HTTP request) but cached per fight,
so a live-logged report only re-downloads the fights that are actually new.
"""

import hashlib
import json
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import cache
from cache import cached_query, get_entry, put_entry, count_api_call
from fetch_reports import fetch_guild_reports
from path import CONFIG_DIR
from wcl_client import run_query, WCLError

HERE = os.path.dirname(os.path.abspath(__file__))

# Change detection for the cache: the (always fresh) report list gives every
# report's endTime. A live-logged report's endTime grows as fights are added,
# so if it differs from the value we saw when we cached the report, the
# report changed. Fights that ended before the previously seen endTime were
# already complete then and are served from cache; only newer fights (and
# the cheap report-level queries) are re-downloaded.
META_FILE = os.path.join(cache.CACHE_DIR, "report_meta.json")


def load_meta() -> dict:
    try:
        with open(META_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_meta(meta: dict) -> None:
    os.makedirs(cache.CACHE_DIR, exist_ok=True)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f)


DIFFICULTY_MAP = {"lfr": 1, "normal": 3, "heroic": 4, "mythic": 5}
DIFFICULTY_NAMES = {v: k.capitalize() for k, v in DIFFICULTY_MAP.items()}


def default_difficulties() -> list[str]:
    """DIFFICULTIES in .env (e.g. 'normal,heroic,mythic'); falls back to heroic + mythic."""
    raw = os.getenv("DIFFICULTIES", "")
    out = [x.strip().lower() for x in re.split(r"[,\s]+", raw) if x.strip()]
    out = [x for x in out if x in DIFFICULTY_MAP]
    return out or ["heroic", "mythic"]


def parallelism() -> int:
    try:
        return max(1, int(os.getenv("WCL_PARALLEL", "4")))
    except ValueError:
        return 4


FIGHTS_QUERY = """
query ReportFights($code: String!) {
    reportData {
        report(code: $code) {
            masterData {
                actors(type: "Player") { id name subType server }
            }
            fights {
                id
                name
                difficulty
                kill
                startTime
                endTime
                bossPercentage
                fightPercentage
                encounterID
                friendlyPlayers
            }
        }
    }
}
"""

# Kept separate so that if WCL's phase schema differs, the rest still works.
PHASES_QUERY = """
query ReportPhases($code: String!) {
    reportData {
        report(code: $code) {
            phases {
                encounterID
                separatesWipes
                phases { id name isIntermission }
            }
            fights {
                id
                phaseTransitions { id startTime }
            }
        }
    }
}
"""

# Ability names, fetched separately so existing cache entries stay valid.
ABILITIES_QUERY = """
query ReportAbilities($code: String!) {
    reportData {
        report(code: $code) {
            masterData {
                abilities { gameID name type }
            }
        }
    }
}
"""

# Enemy names, so death recaps can say who cast what.
NPC_ACTORS_QUERY = """
query ReportNPCs($code: String!) {
    reportData {
        report(code: $code) {
            masterData {
                actors(type: "NPC") { id name }
            }
        }
    }
}
"""

# Raw damage-taken events for one pull (paginated via nextPageTimestamp).
DAMAGE_TAKEN_QUERY = """
query FightDamageTaken($code: String!, $fightID: Int!, $start: Float!, $end: Float!) {
    reportData {
        report(code: $code) {
            events(dataType: DamageTaken, fightIDs: [$fightID], startTime: $start, endTime: $end, limit: 10000) {
                data
                nextPageTimestamp
            }
        }
    }
}
"""

# Parse percentiles. Only exist for kills.
RANKINGS_QUERY = """
query FightRankings($code: String!, $fightID: Int!) {
    reportData {
        report(code: $code) {
            dps: rankings(fightIDs: [$fightID], playerMetric: dps)
            hps: rankings(fightIDs: [$fightID], playerMetric: hps)
        }
    }
}
"""

REPORT_META_QUERY = """
query ReportMeta($code: String!) {
    reportData {
        report(code: $code) {
            code
            title
            startTime
            endTime
            zone { id name }
        }
    }
}
"""

ZONE_ENCOUNTERS_QUERY = """
query ZoneEncounters($id: Int!) {
    worldData {
        zone(id: $id) {
            name
            encounters { id name }
        }
    }
}
"""

# Per-fight "bundle": the WCL tables and events one pull needs, fetched for
# several fights in ONE request via GraphQL aliases, cached per fight.
BUNDLE_TABLES = {"damage": "DamageDone", "healing": "Healing", "deaths": "Deaths",
                 "interrupts": "Interrupts", "dispels": "Dispels"}
BUNDLE_VERSION = "v3"     # v3: Casts table dropped (WCL's Casts table does not list item uses such as potions)
BUNDLE_BATCH = 5          # fights per request (damage tables are bulky)
CASTS_BATCH = 10
CASTS_VERSION = "v2"      # v2: + buffs applied to the dying player (externals)
CONSUMABLES_VERSION = "v1"
PREPOT_BEFORE_MS = 5000   # combat potions cast this long before the pull count as a pre-pot ...
PREPOT_AFTER_MS = 1500    # ... up to this long after the pull started

_phase_warning_shown = False
_rankings_warning_shown = False
_bundle_warning_shown = False
_casts_warning_shown = False
_cons_warning_shown = False
_warn_lock = threading.Lock()
_bundle_extras_ok = True   # False once WCL rejected CombatantInfo / Interrupts / Dispels -> minimal bundle


def _warn_once(flag_name: str, message: str) -> None:
    with _warn_lock:
        if not globals()[flag_name]:
            print(message)
            globals()[flag_name] = True


# Every fight in every processed report - boss pulls AND trash - as absolute
# [start_ms, end_ms, is_boss]. Used to tell a break (idle) from trash clearing.
NIGHT_FIGHTS: dict[str, list[list]] = {}
# Every player who appears anywhere in a night's report(s) - {night: {label: class}} - so the
# Raid tab can show who was there but never in a boss pull (bench / stand-by).
NIGHT_PLAYERS: dict[str, dict[str, str]] = {}


def busy_ms_between(night: str, start_ms: float, end_ms: float) -> float:
    """Milliseconds of any combat (trash or other boss pulls) inside (start_ms, end_ms)."""
    total = 0.0
    for a, e, _ in NIGHT_FIGHTS.get(night, []):
        lo, hi = max(a, start_ms), min(e, end_ms)
        if hi > lo:
            total += hi - lo
    return total


def normalize(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def main_raid_days() -> set[str]:
    """Weekday abbreviations of main raid nights, e.g. {'Thu', 'Sun'}. Empty = every night is a main night."""
    raw = os.getenv("MAIN_RAID_DAYS", "")
    return {x.strip()[:3].capitalize() for x in raw.split(",") if x.strip()}


def open_night_keywords() -> list[str]:
    raw = os.getenv("OPEN_NIGHT_KEYWORDS", "open")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def open_raid_days() -> set[str]:
    """
    Weekday abbreviations of open raid nights, e.g. {'Mon'}. From OPEN_RAID_DAYS in .env,
    else `_open_days` in nights.json. Empty = every night that is not a main night is open.
    When set, reports on any other weekday are not raid nights and are skipped.
    """
    raw = os.getenv("OPEN_RAID_DAYS", "")
    days = {x.strip()[:3].capitalize() for x in raw.split(",") if x.strip()}
    if not days:
        days = {str(x).strip()[:3].capitalize() for x in (night_overrides().get("_open_days") or []) if str(x).strip()}
    return days


NIGHTS_FILE = os.path.join(CONFIG_DIR, "nights.json")


def night_overrides() -> dict:
    """
    nights.json: explicit night types that beat the automatic rules.
      { "DkyB7JPrcnC69R1L": "main",       # by report code ("main", "open" or "skip")
        "2026-09-14": "main",             # by date (the night's start date, in RAID_TIMEZONE)
        "_open_days": ["Mon"],            # weekdays that count as open nights (else OPEN_RAID_DAYS in .env)
        "_include": ["abc123XYZ"],        # report codes to ALWAYS add (e.g. a log that isn't on the guild page)
        "_ignore": ["b7wmZ4DGdKQ6vNjH"] } # report codes to leave out entirely
    """
    try:
        with open(NIGHTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def classify_night(night_dt, report_title: str, report_code: str = "") -> str | None:
    """
    'main', 'open', or None (not a raid night - skip the report).
    Order: nights.json override by code, then by date ("main" / "open" / "skip"), then
    report-title keywords (OPEN_NIGHT_KEYWORDS -> open), then the weekday rules:
    MAIN_RAID_DAYS -> main; OPEN_RAID_DAYS / nights.json _open_days -> open; any other
    weekday -> None when open days are configured, else open.
    """
    ov = night_overrides()
    for key in (report_code, night_dt.strftime("%Y-%m-%d")):
        val = ov.get(key) if key else None
        if val in ("main", "open"):
            return val
        if val in ("skip", "ignore"):
            return None
    days = main_raid_days()
    open_days = open_raid_days()
    wd = night_dt.strftime("%a")
    if days and wd in days:
        return "main"          # a main raid day is a main night whatever the log is called
    words = set(re.findall(r"[a-z0-9]+", (report_title or "").lower()))
    if any(k in words for k in open_night_keywords()):
        return "open"          # whole-word match: "open" but not "reopening"
    if open_days:
        return "open" if wd in open_days else None
    return "open" if days else "main"


def excluded_bosses() -> set[str]:
    """Normalised boss names to leave out of every statistic: EXCLUDE_BOSSES in .env, else nights.json `_exclude_bosses`."""
    raw = os.getenv("EXCLUDE_BOSSES", "")
    names = [x for x in raw.split(",") if x.strip()]
    if not names:
        names = [str(x) for x in (night_overrides().get("_exclude_bosses") or [])]
    return {normalize(n) for n in names if n.strip()}


def zone_encounter_order(zone_id: int) -> dict:
    """{encounterID: position} in WCL's boss order for the zone; {} if unavailable."""
    if not zone_id:
        return {}
    try:
        data = cached_query(ZONE_ENCOUNTERS_QUERY, {"id": int(zone_id)})
        encs = ((data.get("worldData") or {}).get("zone") or {}).get("encounters") or []
        return {e["id"]: i for i, e in enumerate(encs)}
    except Exception as exc:
        print(f"  (could not fetch boss order for zone {zone_id}: {exc})")
        return {}


def clean_code(code: str) -> str:
    """Accepts a bare report code or a full WCL URL."""
    return code.strip().split("/reports/")[-1].split("#")[0].split("?")[0].strip("/")


def add_report_to_includes(code: str) -> str:
    """Append a report code to nights.json's _include list (creating the file if needed). Returns the clean code."""
    code = clean_code(code)
    ov = night_overrides()
    inc = ov.setdefault("_include", [])
    if code not in inc:
        inc.append(code)
        with open(NIGHTS_FILE, "w", encoding="utf-8") as f:
            json.dump(ov, f, indent=2, ensure_ascii=False)
        print(f"Added {code} to {os.path.basename(NIGHTS_FILE)} _include - it will be part of every build from now on.")
    else:
        print(f"{code} is already in _include.")
    return code


def fetch_reports_by_code(codes: list[str]) -> list[dict]:
    """
    Report metadata for explicit codes (also works for reports not on the guild
    page, e.g. personal logs). NEVER cached: the endTime is what change detection
    compares against, so it has to be fresh.
    """
    out = []
    for code in codes:
        code = clean_code(code)
        if not code:
            continue
        try:
            data = run_query(REPORT_META_QUERY, {"code": code})
            count_api_call()
        except Exception as exc:
            print(f"  Report {code}: could not fetch ({exc})")
            continue
        rep = data["reportData"]["report"]
        if rep:
            out.append(rep)
        else:
            print(f"  Report {code}: not found or not visible to this API client")
    return out


def get_timezone():
    name = os.getenv("RAID_TIMEZONE", "UTC")
    try:
        return ZoneInfo(name)
    except Exception:
        print(f"Warning: unknown timezone '{name}', falling back to UTC.")
        return timezone.utc


# --------------------------------------------------------------------------
# Optional config: consumables + defensives (name patterns, case-insensitive)
# --------------------------------------------------------------------------

CONSUMABLES_FILE = os.path.join(CONFIG_DIR, "consumables.json")
DEFENSIVES_FILE = os.path.join(CONFIG_DIR, "defensives.json")

# flask / food / vantus / rune are matched against the auras active at pull start;
# the *_potion and healthstone categories are matched against CAST names (items
# used during the pull - WCL's Casts table does not list those, so they come from
# filtered cast events). A pattern starting with "-" excludes names containing it.
# prepot = a combat potion cast in the seconds around the pull start.
DEFAULT_CONSUMABLES = {
    "flask": ["flask of", "phial of"],
    "food": ["well fed"],
    "vantus": ["vantus rune"],
    "rune": ["augment rune", "crystallized augment", "draconic augment rune"],
    "combat_potion": ["potion", "-health", "-healing", "-mana"],
    "healing_potion": ["health potion", "healing potion"],
    "mana_potion": ["mana potion"],
    "healthstone": ["healthstone"],
}
CAST_CATEGORIES = ("combat_potion", "healing_potion", "mana_potion", "healthstone")
AURA_CATEGORIES = ("flask", "food", "vantus", "rune")


def name_matches(name: str, patterns: list[str]) -> bool:
    """Case-insensitive substring match; patterns starting with '-' are exclusions."""
    n = (name or "").lower()
    inc = [p for p in patterns if not p.startswith("-")]
    exc = [p[1:] for p in patterns if p.startswith("-")]
    return any(p in n for p in inc) and not any(p in n for p in exc)

DEFAULT_DEFENSIVES = [
    # generic
    "Healthstone", "Healing Potion",
    # Death Knight
    "Anti-Magic Shell", "Icebound Fortitude", "Anti-Magic Zone", "Vampiric Blood", "Rune Tap", "Lichborne",
    # Demon Hunter
    "Blur", "Netherwalk", "Darkness", "Demon Spikes", "Fiery Brand",
    # Druid
    "Barkskin", "Survival Instincts", "Frenzied Regeneration", "Ironbark", "Renewal",
    # Evoker
    "Obsidian Scales", "Renewing Blaze", "Zephyr", "Time Dilation",
    # Hunter
    "Aspect of the Turtle", "Survival of the Fittest", "Exhilaration", "Fortitude of the Bear",
    # Mage
    "Ice Block", "Greater Invisibility", "Alter Time", "Mirror Image", "Mass Barrier", "Prismatic Barrier",
    "Blazing Barrier", "Ice Barrier", "Ice Cold",
    # Monk
    "Fortifying Brew", "Diffuse Magic", "Dampen Harm", "Touch of Karma", "Celestial Brew", "Life Cocoon", "Zen Meditation",
    # Paladin
    "Divine Shield", "Divine Protection", "Ardent Defender", "Guardian of Ancient Kings", "Blessing of Protection",
    "Blessing of Sacrifice", "Blessing of Spellwarding", "Lay on Hands", "Shield of Vengeance",
    # Priest
    "Desperate Prayer", "Dispersion", "Pain Suppression", "Power Word: Barrier", "Fade", "Guardian Spirit",
    "Vampiric Embrace", "Void Shift",
    # Rogue
    "Cloak of Shadows", "Evasion", "Feint", "Crimson Vial", "Vanish",
    # Shaman
    "Astral Shift", "Ancestral Guidance", "Spirit Link Totem", "Earth Elemental", "Stone Bulwark Totem",
    "Ancestral Protection Totem",
    # Warlock
    "Unending Resolve", "Dark Pact", "Mortal Coil",
    # Warrior
    "Shield Wall", "Last Stand", "Die by the Sword", "Rallying Cry", "Spell Reflection", "Ignore Pain",
    "Enraged Regeneration", "Defensive Stance", "Bitter Immunity", "Demoralizing Shout", "Shield Block",
]


def _load_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def consumable_patterns() -> dict[str, list[str]]:
    """{category: [lower-case substrings]} - consumables.json overrides the defaults (unknown categories are treated as auras)."""
    raw = _load_json(CONSUMABLES_FILE)
    src = raw if isinstance(raw, dict) else DEFAULT_CONSUMABLES
    out = {k: [str(p).lower() for p in v] for k, v in src.items() if isinstance(v, list) and not k.startswith("_")}
    if "prepot" in out and "combat_potion" not in out:   # old-style file: prepot patterns were potion cast names
        out["combat_potion"] = out.pop("prepot")
    return out


def defensive_patterns() -> list[str]:
    raw = _load_json(DEFENSIVES_FILE)
    if isinstance(raw, dict):
        raw = raw.get("defensives")
    src = raw if isinstance(raw, list) else DEFAULT_DEFENSIVES
    return [str(p).lower() for p in src]


def is_defensive(name: str, patterns: list[str]) -> bool:
    n = (name or "").lower()
    return any(p in n for p in patterns)


# --------------------------------------------------------------------------
# Report-level data
# --------------------------------------------------------------------------

_refresh_current = False   # True while processing a report that changed since it was cached


def cq(query: str, variables: dict, refresh: bool | None = None) -> dict:
    """cached_query that re-downloads when the current report (or this fight) changed."""
    return cached_query(query, variables, refresh=_refresh_current if refresh is None else refresh)


def get_report(report_code: str) -> tuple[dict, list[dict]]:
    """Returns (actors_by_id, fights). Actors: {id: {name, class, server}}."""
    data = cq(FIGHTS_QUERY, {"code": report_code})
    report = data["reportData"]["report"]
    if not report:
        return {}, []
    actors = {
        a["id"]: {"name": a["name"], "class": a.get("subType") or "Unknown", "server": a.get("server") or ""}
        for a in (report.get("masterData") or {}).get("actors", []) or []
    }
    return actors, report.get("fights") or []


def get_phases(report_code: str) -> tuple[dict, dict]:
    """
    Returns (phase_names, transitions):
      phase_names: {encounterID: {phaseID: "Phase name"}}
      transitions: {fightID: [{"id": phaseID, "startTime": ms}, ...]}
    Falls back to empty dicts if WCL doesn't return phase data.
    """
    try:
        data = cq(PHASES_QUERY, {"code": report_code})
    except Exception as exc:
        _warn_once("_phase_warning_shown", f"  (phase data unavailable, skipping phase breakdown: {exc})")
        return {}, {}

    report = data["reportData"]["report"] or {}
    phase_names = {}
    for enc in report.get("phases") or []:
        phase_names[enc["encounterID"]] = {p["id"]: p["name"] for p in enc.get("phases") or []}
    transitions = {
        f["id"]: sorted(f.get("phaseTransitions") or [], key=lambda t: t["startTime"])
        for f in report.get("fights") or []
    }
    return phase_names, transitions


def phase_at_end(fight: dict, phase_names: dict, transitions: dict) -> str | None:
    names = phase_names.get(fight.get("encounterID"))
    if not names:
        return None
    current = None
    for t in transitions.get(fight["id"], []):
        if t["startTime"] <= fight["endTime"]:
            current = t["id"]
    if current is None:
        # No transitions recorded -> the pull never left the first phase
        first = min(names) if names else None
        return names.get(first) if first is not None else None
    return names.get(current, f"Phase {current}")


def phase_timeline(fight: dict, phase_names: dict, transitions: dict) -> list[list]:
    """[[phase name, seconds into the fight], ...] for every phase the pull reached, in order."""
    names = phase_names.get(fight.get("encounterID"))
    if not names:
        return []
    out = []
    for t in transitions.get(fight["id"], []):
        if t["startTime"] <= fight["endTime"]:
            out.append([names.get(t["id"], f"Phase {t['id']}"), round(max(t["startTime"] - fight["startTime"], 0) / 1000, 1)])
    return out


def get_ability_names(report_code: str) -> dict:
    data = cq(ABILITIES_QUERY, {"code": report_code})
    report = data["reportData"]["report"] or {}
    return {
        a["gameID"]: a["name"] or f"Ability {a['gameID']}"
        for a in (report.get("masterData") or {}).get("abilities", []) or []
    }


def get_npc_names(report_code: str) -> dict:
    data = cq(NPC_ACTORS_QUERY, {"code": report_code})
    report = data["reportData"]["report"] or {}
    return {a["id"]: a["name"] for a in (report.get("masterData") or {}).get("actors", []) or []}


# --------------------------------------------------------------------------
# Player identity: name, or Name-Realm when two different characters share a name
# --------------------------------------------------------------------------

class Labeller:
    """
    Maps WCL actors to display labels. Characters are identified by
    (name, realm); the label is the bare name unless the same name exists
    on more than one realm anywhere in the dataset, in which case both get
    'Name-Realm' so their numbers never merge.
    """

    def __init__(self):
        self.servers_by_name: dict[str, set] = {}

    def learn(self, actors: dict) -> None:
        for a in actors.values():
            self.servers_by_name.setdefault(a["name"], set()).add(normalize(a.get("server") or ""))

    def ambiguous(self, name: str) -> bool:
        return len(self.servers_by_name.get(name, set())) > 1

    def label(self, name: str, server: str = "") -> str:
        if self.ambiguous(name) and server:
            return f"{name}-{re.sub(r'\s+', '', server)}"
        return name

    def actor_label(self, actor: dict) -> str:
        return self.label(actor["name"], actor.get("server") or "")


# --------------------------------------------------------------------------
# Per-fight bundles (batched aliases, cached per fight)
# --------------------------------------------------------------------------

def _bundle_key(code: str, fight_id: int, extras: bool) -> str:
    return f"bundle:{BUNDLE_VERSION}:{'full' if extras else 'min'}:{code}:{fight_id}"


def _bundle_query(fights: list[dict], extras: bool) -> str:
    parts = []
    tables = BUNDLE_TABLES if extras else {k: v for k, v in BUNDLE_TABLES.items() if k in ("damage", "healing", "deaths")}
    for f in fights:
        fid = f["id"]
        for alias, dt in tables.items():
            parts.append(f"{alias}_{fid}: table(dataType: {dt}, fightIDs: [{fid}])")
        if extras:
            parts.append(f"cinfo_{fid}: events(dataType: CombatantInfo, fightIDs: [{fid}], "
                         f"startTime: {int(f['startTime'])}, endTime: {int(f['endTime'])}, limit: 200) {{ data }}")
    return "query FightBundle($code: String!) { reportData { report(code: $code) { " + " ".join(parts) + " } } }"


def _fetch_bundle_batch(code: str, batch: list[dict], refreshed: int) -> dict:
    """One HTTP request for several fights. Falls back to the minimal bundle if WCL rejects the extras."""
    global _bundle_extras_ok
    extras = _bundle_extras_ok
    try:
        data = run_query(_bundle_query(batch, extras), {"code": code})
    except WCLError as exc:
        if not extras:
            raise
        _warn_once("_bundle_warning_shown",
                   f"  (WCL rejected interrupts/dispels/combatant info - continuing without them: {str(exc)[:160]})")
        _bundle_extras_ok = extras = False
        data = run_query(_bundle_query(batch, extras), {"code": code})
    count_api_call(1, refreshed)
    rep = data["reportData"]["report"] or {}
    out = {}
    for f in batch:
        fid = f["id"]
        b = {alias: rep.get(f"{alias}_{fid}") for alias in BUNDLE_TABLES}
        b["cinfo"] = ((rep.get(f"cinfo_{fid}") or {}).get("data") or []) if extras else []
        b["extras"] = extras
        put_entry(_bundle_key(code, fid, extras), b)
        out[fid] = b
    return out


def get_fight_bundles(code: str, fights: list[dict], needs_refresh, pool: ThreadPoolExecutor) -> dict:
    """{fight_id: bundle} for every fight, from cache where possible, batched requests for the rest."""
    out, missing = {}, []
    for f in fights:
        refresh = needs_refresh(f)
        b = get_entry(_bundle_key(code, f["id"], True), refresh=refresh)
        if b is None and not _bundle_extras_ok:
            b = get_entry(_bundle_key(code, f["id"], False), refresh=refresh)
        if b is None:
            missing.append((f, refresh))
        else:
            out[f["id"]] = b
    if not missing:
        return out
    batches = [missing[i:i + BUNDLE_BATCH] for i in range(0, len(missing), BUNDLE_BATCH)]
    for res in pool.map(lambda bt: _fetch_bundle_batch(code, [f for f, _ in bt], sum(1 for _, r in bt if r)), batches):
        out.update(res)
    return out


def _table_entries(table) -> list[dict]:
    table = table or {}
    inner = table.get("data", table)
    return inner.get("entries", []) or []


def deaths_from_table(table, fight: dict, actors: dict, lab: Labeller) -> list[dict]:
    deaths = []
    for entry in _table_entries(table):
        killing_blow = entry.get("killingBlow") or {}
        seconds = (entry.get("timestamp", fight["startTime"]) - fight["startTime"]) / 1000
        actor = actors.get(entry.get("id"))
        deaths.append({
            "player": lab.actor_label(actor) if actor else entry.get("name", "Unknown"),
            "actor_id": entry.get("id"),
            "class": entry.get("type", "Unknown"),
            "seconds_into_fight": round(seconds, 1),
            "ability": killing_blow.get("name") or "Unknown / environment",
        })
    deaths.sort(key=lambda d: d["seconds_into_fight"])
    return deaths


def player_tables_from_bundle(bundle: dict, actors: dict, lab: Labeller, participants: dict) -> tuple[list[dict], list[dict]]:
    """
    (damage_done, healing_done): one entry per player with {name, class, spec,
    total, active_seconds, ilvl}. Pets are folded into their owner by WCL, but
    some summoned guardians show up as their own source - so only names on the
    pull's participant list are kept.
    """
    def convert(entries):
        out = []
        for e in entries:
            if e.get("type") in (None, "Pet", "NPC"):
                continue
            actor = actors.get(e.get("id"))
            name = lab.actor_label(actor) if actor else e.get("name", "Unknown")
            if name not in participants:
                continue  # summoned guardian / vehicle / stray NPC listed as a source
            icon = e.get("icon") or ""
            # icons look like "Priest-Holy"; anything else (file names, pet icons) is not a spec
            spec = icon.split("-", 1)[1] if "-" in icon and icon.split("-", 1)[0] == e.get("type") else ""
            out.append({
                "name": name,
                "class": e.get("type", "Unknown"),
                "spec": spec,
                "total": e.get("total") or 0,
                "active_seconds": (e.get("activeTime") or 0) / 1000,
                "ilvl": e.get("itemLevel") or 0,
            })
        return out

    return convert(_table_entries(bundle.get("damage"))), convert(_table_entries(bundle.get("healing")))


def counts_from_table(table, actors: dict, lab: Labeller, participants: dict) -> dict:
    """
    {player: count} from an Interrupts / Dispels table. WCL nests these as
    entries[] (the interrupted / dispelled ability) -> details[] (the player
    who did it, with `id` and `total`); older shapes nest under `entries`.
    Every level is walked and any entry whose id is a participating player
    contributes its `total`.
    """
    out: dict[str, int] = {}

    def walk(entries):
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            actor = actors.get(e.get("id")) if isinstance(e.get("type"), str) and e.get("type") not in ("Pet", "NPC", "Boss") else None
            name = lab.actor_label(actor) if actor else None
            if name and name in participants and e.get("total") is not None:
                out[name] = out.get(name, 0) + int(e["total"])
            else:
                walk(e.get("details"))
                walk(e.get("entries"))

    walk(_table_entries(table))
    return out


def consumables_from_cinfo(events: list[dict], actors: dict, lab: Labeller, participants: dict,
                           ability_names: dict, patterns: dict) -> dict:
    """{player: {category: bool}} from the combatantinfo events WCL emits at pull start (auras active on the pull)."""
    out: dict[str, dict] = {}
    for ev in events or []:
        actor = actors.get(ev.get("sourceID"))
        if not actor:
            continue
        name = lab.actor_label(actor)
        if name not in participants:
            continue
        names = []
        for aura in ev.get("auras") or []:
            n = aura.get("name") or ability_names.get(aura.get("ability"), "")
            if n:
                names.append(n.lower())
        out[name] = {cat: any(name_matches(n, pats) for n in names) for cat, pats in patterns.items() if cat not in CAST_CATEGORIES}
    return out


# --------------------------------------------------------------------------
# Consumable casts (potions, healthstones): filtered cast events per fight
# --------------------------------------------------------------------------

def consumable_ability_ids(ability_names: dict, patterns: dict) -> dict[int, str]:
    """{ability id: category} for every ability in the report whose name matches a cast category."""
    out = {}
    for gid, name in ability_names.items():
        for cat in CAST_CATEGORIES:
            if cat in patterns and name_matches(name, patterns[cat]):
                out[gid] = cat
                break
    return out


def _cons_key(code: str, fight_id: int, ids: list[int]) -> str:
    return f"cons:{CONSUMABLES_VERSION}:{code}:{fight_id}:{hashlib.sha1(','.join(map(str, sorted(ids))).encode()).hexdigest()[:12]}"


def get_consumable_casts(code: str, fights: list[dict], ids: list[int], needs_refresh, pool: ThreadPoolExecutor) -> dict:
    """
    {fight_id: [cast events]} for the consumable abilities `ids`, from PREPOT_BEFORE_MS
    before each pull to its end. Batched CASTS_BATCH fights per request via aliases,
    filtered server-side with `ability.id in (...)`; cached per fight.
    """
    out, missing = {}, []
    if not ids:
        return {f["id"]: [] for f in fights}
    for f in fights:
        e = get_entry(_cons_key(code, f["id"], ids), refresh=needs_refresh(f))
        if e is None:
            missing.append((f, needs_refresh(f)))
        else:
            out[f["id"]] = e.get("data") or []
    if not missing:
        return out
    expr = "ability.id in (" + ",".join(str(i) for i in sorted(ids)) + ")"

    def fetch(batch):
        parts = [f"cons_{f['id']}: events(dataType: Casts, fightIDs: [{f['id']}], startTime: {int(f['startTime']) - PREPOT_BEFORE_MS}, "
                 f"endTime: {int(f['endTime'])}, filterExpression: \"{expr}\", limit: 2000) {{ data }}" for f, _ in batch]
        q = "query ConsumableCasts($code: String!) { reportData { report(code: $code) { " + " ".join(parts) + " } } }"
        try:
            data = run_query(q, {"code": code})
        except WCLError as exc:
            _warn_once("_cons_warning_shown", f"  (potion / healthstone casts unavailable: {str(exc)[:160]})")
            return {}
        count_api_call(1, sum(1 for _, r in batch if r))
        rep = data["reportData"]["report"] or {}
        res = {}
        for f, _ in batch:
            evs = (rep.get(f"cons_{f['id']}") or {}).get("data") or []
            put_entry(_cons_key(code, f["id"], ids), {"data": evs})
            res[f["id"]] = evs
        return res

    batches = [missing[i:i + CASTS_BATCH] for i in range(0, len(missing), CASTS_BATCH)]
    for res in pool.map(fetch, batches):
        out.update(res)
    return out


def consumable_use(events: list[dict], actors: dict, lab: Labeller, participants: dict, id_cats: dict, fight_start: float) -> tuple[set, dict]:
    """
    (prepotted players, {player: {category: casts during the pull}}) from filtered
    cast events. A combat potion cast before fight start + PREPOT_AFTER_MS is a
    pre-pot and is NOT counted as an in-fight use.
    """
    prepot = set()
    use: dict[str, dict] = {}
    for ev in events or []:
        if ev.get("type") != "cast":
            continue
        cat = id_cats.get(ev.get("abilityGameID"))
        if not cat:
            continue
        actor = actors.get(ev.get("sourceID"))
        name = lab.actor_label(actor) if actor else None
        if not name or name not in participants:
            continue
        if ev["timestamp"] <= fight_start + PREPOT_AFTER_MS:
            if cat == "combat_potion":
                prepot.add(name)
            continue
        d = use.setdefault(name, {})
        d[cat] = d.get(cat, 0) + 1
    return prepot, use


# --------------------------------------------------------------------------
# Casts before the first death (defensive usage)
# --------------------------------------------------------------------------

def _casts_key(code: str, fight_id: int, window: float) -> str:
    return f"casts1:{CASTS_VERSION}:{code}:{fight_id}:{window:g}"


def get_first_death_casts(code: str, items: list[tuple[dict, dict, bool]], window: float, pool: ThreadPoolExecutor) -> dict:
    """
    items: [(fight, first_death, refresh)]. Returns {fight_id: {"casts": [...], "buffs": [...]}}:
    the dying player's own casts and the buffs applied to them (externals) in the
    `window` seconds before the first death of each pull. One batched request per
    CASTS_BATCH pulls; cached per fight.
    """
    out, missing = {}, []
    for fight, death, refresh in items:
        if death.get("actor_id") is None:
            continue
        e = get_entry(_casts_key(code, fight["id"], window), refresh=refresh)
        if e is None:
            missing.append((fight, death, refresh))
        else:
            out[fight["id"]] = {"casts": e.get("data") or [], "buffs": e.get("buffs") or []}
    if not missing:
        return out

    def fetch(batch):
        parts = []
        for fight, death, _ in batch:
            end = fight["startTime"] + death["seconds_into_fight"] * 1000 + 300
            start = max(fight["startTime"], end - window * 1000 - 300)
            parts.append(f"casts_{fight['id']}: events(dataType: Casts, fightIDs: [{fight['id']}], sourceID: {death['actor_id']}, "
                         f"startTime: {int(start)}, endTime: {int(end)}, limit: 300) {{ data }}")
            parts.append(f"buffs_{fight['id']}: events(dataType: Buffs, fightIDs: [{fight['id']}], targetID: {death['actor_id']}, "
                         f"startTime: {int(start)}, endTime: {int(end)}, limit: 300) {{ data }}")
        q = "query FirstDeathCasts($code: String!) { reportData { report(code: $code) { " + " ".join(parts) + " } } }"
        try:
            data = run_query(q, {"code": code})
        except WCLError as exc:
            _warn_once("_casts_warning_shown", f"  (casts before first death unavailable: {str(exc)[:160]})")
            return {}
        count_api_call(1, sum(1 for _, _, r in batch if r))
        rep = data["reportData"]["report"] or {}
        res = {}
        for fight, _, _ in batch:
            evs = (rep.get(f"casts_{fight['id']}") or {}).get("data") or []
            buffs = (rep.get(f"buffs_{fight['id']}") or {}).get("data") or []
            put_entry(_casts_key(code, fight["id"], window), {"data": evs, "buffs": buffs})
            res[fight["id"]] = {"casts": evs, "buffs": buffs}
        return res

    batches = [missing[i:i + CASTS_BATCH] for i in range(0, len(missing), CASTS_BATCH)]
    for res in pool.map(fetch, batches):
        out.update(res)
    return out


def attach_casts(death: dict, casts: list[dict], buffs: list[dict], fight: dict, actors: dict, lab: Labeller,
                 ability_names: dict, patterns: list[str]) -> None:
    """
    Adds `casts` (every cast by the dying player in the window, newest last),
    `defensives` (the ones that look like defensives) and `externals` (buffs
    applied to them by someone else in the window that look like defensives,
    with the caster).
    """
    t = death["seconds_into_fight"]
    rows = []
    for ev in casts:
        if ev.get("type") not in ("cast", "begincast"):
            continue
        name = ability_names.get(ev.get("abilityGameID"), f"Ability {ev.get('abilityGameID')}")
        before = round(t - (ev["timestamp"] - fight["startTime"]) / 1000, 1)
        rows.append([max(before, 0), name])
    rows.sort(key=lambda r: -r[0])
    death["casts"] = rows[-25:]
    death["defensives"] = [r for r in rows if is_defensive(r[1], patterns)]
    ext = []
    seen = set()
    for ev in buffs:
        if ev.get("type") not in ("applybuff", "refreshbuff", "applybuffstack"):
            continue
        if ev.get("sourceID") == ev.get("targetID"):
            continue
        name = ability_names.get(ev.get("abilityGameID"), f"Ability {ev.get('abilityGameID')}")
        if not is_defensive(name, patterns):
            continue
        src = actors.get(ev.get("sourceID"))
        caster = lab.actor_label(src) if src else "?"
        key = (name, caster)
        if key in seen:
            continue
        seen.add(key)
        before = round(t - (ev["timestamp"] - fight["startTime"]) / 1000, 1)
        ext.append([max(before, 0), name, caster])
    ext.sort(key=lambda r: -r[0])
    death["externals"] = ext
    death["has_cast_data"] = True


# --------------------------------------------------------------------------
# Damage taken (raw events) and aggregation
# --------------------------------------------------------------------------

def get_damage_events(report_code: str, fight: dict, actors: dict, ability_names: dict, npc_names: dict,
                      lab: Labeller, refresh: bool = False) -> list[dict]:
    """
    Every damage event taken by a player in this pull, as
    {player, class, ability, source, amount, absorbed, overkill, seconds}.
    'amount' includes absorbed damage. Sorted by time.
    """
    events = []
    start = fight["startTime"]
    while start is not None:
        data = cq(
            DAMAGE_TAKEN_QUERY,
            {"code": report_code, "fightID": fight["id"], "start": start, "end": fight["endTime"]},
            refresh=refresh,
        )
        page = data["reportData"]["report"]["events"] or {}
        for ev in page.get("data") or []:
            if ev.get("type") != "damage":
                continue
            actor = actors.get(ev.get("targetID"))
            if not actor:
                continue  # pets, NPCs, etc.
            absorbed = ev.get("absorbed") or 0
            source_id = ev.get("sourceID")
            src_actor = actors.get(source_id)
            events.append({
                # self-inflicted (Burning Rush, Stagger, trinkets...) - kept for
                # death recaps, but excluded from damage-taken statistics
                "self": source_id == ev.get("targetID"),
                # WCL flags periodic DoT ticks explicitly - a "hit" (tick=False)
                # means the ability actually landed on you; ticks are the DoT
                # it then applies. A wall of ticks from ONE hit should not be
                # reported as if you got hit repeatedly.
                "is_tick": bool(ev.get("tick")),
                "player": lab.actor_label(actor),
                "class": actor["class"],
                "ability": ability_names.get(ev.get("abilityGameID"), f"Ability {ev.get('abilityGameID')}"),
                "source": npc_names.get(source_id) or (lab.actor_label(src_actor) if src_actor else None) or "Unknown",
                "amount": (ev.get("amount") or 0) + absorbed,
                "absorbed": absorbed,
                "overkill": ev.get("overkill") or 0,
                # what the hit WOULD have done before armor/versatility/defensives
                "unmitigated": ev.get("unmitigatedAmount") or ((ev.get("amount") or 0) + absorbed),
                # miss / dodge / parry / immune: the swing connected with nothing
                "avoided": (ev.get("amount") or 0) == 0 and absorbed == 0
                           and not (ev.get("unmitigatedAmount") or 0),
                "seconds": round((ev["timestamp"] - fight["startTime"]) / 1000, 2),
            })
        start = page.get("nextPageTimestamp")
    events.sort(key=lambda e: e["seconds"])
    return events


INSTANCE_GAP_SECONDS = 2.5      # events closer than this = same occurrence of the ability
TICK_CLUSTER_GAP_SECONDS = INSTANCE_GAP_SECONDS


def aggregate_damage(events: list[dict]) -> list[dict]:
    """
    [{player, class, ability, hits, ticks, amount, times, sources}] - what the
    Damage taken tab uses.

    'hits' counts INSTANCES of the ability landing on you - matching WCL's own
    "Hits" column - not raw damage events. Consecutive events of the same
    ability on the same player closer together than INSTANCE_GAP_SECONDS are
    one occurrence. This handles three shapes of ability the same way:
      - a single direct hit                         -> 1 instance
      - a hit that applies a DoT ticking 8 times    -> 1 instance
      - a pulsing aura ("stand in the goo") that     -> 1 instance per
        WCL records as a direct hit every second       time you stood in it

    'ticks' is the raw periodic-damage event count, kept for transparency but
    not used for the per-pull hit-rate metrics. 'times' holds one timestamp
    per instance, so timing histograms show real occurrences, not every tick.
    """
    raw: dict[tuple[str, str], dict] = {}
    for e in events:
        if e.get("self"):
            continue
        entry = raw.setdefault((e["player"], e["ability"]), {
            "player": e["player"], "class": e["class"], "ability": e["ability"],
            "amount": 0, "hit_amount": 0, "tick_amount": 0, "unmitigated": 0, "avoided": 0,
            "sources": {}, "hit_events": [], "tick_events": [],
        })
        entry["amount"] += e["amount"]
        entry["unmitigated"] += e.get("unmitigated", e["amount"])
        if e.get("avoided"):
            entry["avoided"] += 1
        if e.get("is_tick"):
            entry["tick_amount"] += e["amount"]
        else:
            entry["hit_amount"] += e["amount"]
        entry["sources"][e["source"]] = entry["sources"].get(e["source"], 0) + 1
        (entry["tick_events"] if e["is_tick"] else entry["hit_events"]).append(e)

    results = []
    for entry in raw.values():
        hit_events = entry.pop("hit_events")
        tick_events = entry.pop("tick_events")
        everything = sorted(hit_events + tick_events, key=lambda ev: ev["seconds"])

        times = []
        uptime = 0.0
        cluster_start = prev_t = None
        for ev in everything:
            t = ev["seconds"]
            if prev_t is None or t - prev_t > INSTANCE_GAP_SECONDS:
                if prev_t is not None:
                    uptime += prev_t - cluster_start
                times.append(t)
                cluster_start = t
            prev_t = t
        if prev_t is not None:
            uptime += prev_t - cluster_start

        entry["hits"] = len(times)
        entry["ticks"] = len(tick_events)
        entry["events"] = len(hit_events) + len(tick_events)
        entry["times"] = times
        # Uptime: how long this ability was "on" the player, approximated from the
        # span of each cluster of events (first hit to last tick).
        entry["uptime_seconds"] = round(uptime, 1)
        results.append(entry)
    return results


def get_parses(report_code: str, fight: dict, lab: Labeller, refresh: bool = False) -> dict:
    """
    {player: {"dps": rankPercent, "hps": rankPercent}} for a KILL. Wipes have
    no rankings on WCL, so this returns {} for them without calling the API.
    """
    if not fight.get("kill"):
        return {}
    try:
        data = cq(RANKINGS_QUERY, {"code": report_code, "fightID": fight["id"]}, refresh=refresh)
    except Exception as exc:
        _warn_once("_rankings_warning_shown", f"  (rankings unavailable, parses will be blank: {exc})")
        return {}
    report = data["reportData"]["report"] or {}
    parses: dict[str, dict] = {}
    for metric in ("dps", "hps"):
        payload = report.get(metric) or {}
        for fight_rank in payload.get("data", []) or []:
            for role in (fight_rank.get("roles") or {}).values():
                for ch in (role or {}).get("characters", []) or []:
                    if ch.get("rankPercent") is None:
                        continue
                    server = ((ch.get("server") or {}).get("name")) or ""
                    parses.setdefault(lab.label(ch["name"], server), {})[metric] = ch["rankPercent"]
    return parses


def death_window_seconds() -> float:
    try:
        return float(os.getenv("DEATH_WINDOW_SECONDS", "6"))
    except ValueError:
        return 6.0


def attach_recaps(deaths: list[dict], events: list[dict], window: float) -> None:
    """
    For each death, attach the damage events that player took in the last
    `window` seconds before dying, plus a few derived facts:
      recap            - the events themselves (chronological)
      window_damage    - total damage in the window
      top_contributor  - ability that did the most damage in the window
      biggest_hit      - single largest event in the window
      one_shot         - biggest hit was >= 60% of the window damage
    """
    by_player: dict[str, list[dict]] = {}
    for e in events:
        by_player.setdefault(e["player"], []).append(e)
    for d in deaths:
        t = d["seconds_into_fight"]
        recap = [e for e in by_player.get(d["player"], []) if t - window <= e["seconds"] <= t + 0.3]
        total = sum(e["amount"] for e in recap)
        by_ability: dict[str, int] = {}
        for e in recap:
            by_ability[e["ability"]] = by_ability.get(e["ability"], 0) + e["amount"]
        biggest = max(recap, key=lambda e: e["amount"], default=None)
        d["recap"] = recap
        d["window_damage"] = total
        d["top_contributor"] = max(by_ability, key=by_ability.get) if by_ability else d["ability"]
        d["biggest_hit"] = biggest
        d["one_shot"] = bool(biggest and total and biggest["amount"] / total >= 0.6)
        d["hits_in_window"] = len(recap)


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def _select_reports(start_date: str, end_date: str, reports: list[str] | None) -> list[dict]:
    if reports:
        out = fetch_reports_by_code(reports)
        print(f"Using {len(out)} explicitly listed report(s).")
        return out
    out = fetch_guild_reports(start_date, end_date)
    ov = night_overrides()
    ignored_codes = set(ov.get("_ignore", []) or [])
    if ignored_codes:
        before = len(out)
        out = [r for r in out if r["code"] not in ignored_codes]
        if before != len(out):
            print(f"  Ignoring {before - len(out)} report(s) listed under _ignore in nights.json")
    have = {r["code"] for r in out}
    includes = ov.get("_include", []) or []
    extra = [c for c in includes if clean_code(c) not in have and "PASTE" not in c.upper()]
    if any("PASTE" in c.upper() for c in includes):
        print("  nights.json: ignoring the PASTE_REPORT_CODE_HERE placeholder - remove it from _include")
    if extra:
        added = fetch_reports_by_code(extra)
        # keep them inside the requested date range so a stale include doesn't drag in an old tier
        start_ms = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000
        end_ms = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000 + 86400000
        in_range = [r for r in added if start_ms <= r["startTime"] < end_ms]
        if len(in_range) != len(added):
            print(f"  {len(added) - len(in_range)} _include report(s) fall outside {start_date}..{end_date} - skipped")
        out.extend(in_range)
        if in_range:
            print(f"  Added {len(in_range)} report(s) from nights.json _include")
    print(f"Found {len(out)} report(s) in range.")
    return out


def collect(
    start_date: str,
    end_date: str,
    difficulties=("heroic", "mythic"),
    boss: str | None = None,
    zone: str | None = None,
    player: str | None = None,
    progression_only: bool = False,
    nights: str = "all",
    reports: list[str] | None = None,
) -> dict:
    global _refresh_current
    wanted = {DIFFICULTY_MAP[d.lower()] for d in difficulties}
    tz = get_timezone()
    boss_key = normalize(boss) if boss else None
    zone_key = zone.lower() if zone else None
    player_key = player.lower() if player else None
    window = death_window_seconds()
    cons_patterns = consumable_patterns()
    def_patterns = defensive_patterns()

    explicit = bool(reports)
    reports = _select_reports(start_date, end_date, reports)
    reports.sort(key=lambda r: r["startTime"])
    meta = load_meta()
    cache.stats.update({"api_calls": 0, "cache_hits": 0, "refreshed": 0})

    bosses: dict[tuple[str, str], list[dict]] = {}
    NIGHT_FIGHTS.clear()
    NIGHT_PLAYERS.clear()
    lab = Labeller()
    excluded = excluded_bosses()
    if excluded:
        print(f"  Excluding boss(es) from every statistic: {', '.join(sorted(excluded))}")

    # ---- pass 1: which reports are in scope, did they change, and who plays in them
    plan = []
    for report in reports:
        code = report["code"]
        zone_name = (report.get("zone") or {}).get("name") or ""
        if zone_key and zone_key not in zone_name.lower():
            continue
        night_dt = datetime.fromtimestamp(report["startTime"] / 1000, tz=tz)
        night_type = classify_night(night_dt, report.get("title", ""), code)
        if night_type is None and explicit:
            # the user named this report on the command line: keep it, just decide main vs open by weekday
            night_type = "main" if night_dt.strftime("%a") in main_raid_days() else "open"
        if night_type is None:
            print(f"  Skipping {code} ({night_dt.strftime('%a %Y-%m-%d')}) - {report.get('title', '')!r}: not a raid day "
                  f"(main: {', '.join(sorted(main_raid_days())) or 'any'}; open: {', '.join(sorted(open_raid_days()))}). "
                  f"Map its code to 'main' or 'open' in nights.json to keep it.")
            continue
        if nights != "all" and night_type != nights:
            print(f"  Skipping {code} ({night_dt.strftime('%a %Y-%m-%d')}) - {night_type} night, --nights {nights}")
            continue
        seen_end = meta.get(code)
        changed = seen_end is not None and seen_end != report["endTime"]
        _refresh_current = changed
        actors, fights = get_report(code)
        lab.learn(actors)
        plan.append((report, zone_name, night_dt, night_type, seen_end, changed, actors, fights))
    _refresh_current = False

    pool = ThreadPoolExecutor(max_workers=parallelism())
    try:
        for report, zone_name, night_dt, night_type, seen_end, changed, actors, fights in plan:
            code = report["code"]
            _refresh_current = changed
            night_label = night_dt.strftime("%a %Y-%m-%d") + (" open" if night_type == "open" else "")
            status = ("[new report]" if seen_end is None else
                      "[changed since last run - re-downloading new fights]" if changed else "[unchanged - cached]")
            print(f"  Processing {code} ({night_label}) - {report['title']}  [{night_type} night] {status}")

            # a fight is new if it ended after the endTime we saw last time
            def needs_refresh(f, _seen=seen_end, _changed=changed, _start=report["startTime"]):
                return bool(_changed and _seen is not None and _start + f["endTime"] > _seen)

            phase_names, transitions = get_phases(code)
            NIGHT_FIGHTS.setdefault(night_label, []).extend(
                [report["startTime"] + f["startTime"], report["startTime"] + f["endTime"], bool(f.get("encounterID"))]
                for f in fights if f.get("endTime") and f.get("startTime") is not None)
            ability_names = get_ability_names(code)
            npc_names = get_npc_names(code)
            # everyone who was in ANY fight that night (trash included) - the report's actor list is far wider
            # (it also holds every player seen in cities or the open world while logging)
            in_fights = {pid for f in fights for pid in (f.get("friendlyPlayers") or [])}
            NIGHT_PLAYERS.setdefault(night_label, {}).update(
                {lab.actor_label(actors[pid]): actors[pid]["class"] for pid in in_fights if pid in actors})

            seen_diffs: Counter = Counter()
            selected = []   # (fight, participants)
            for fight in fights:
                if not fight.get("encounterID"):
                    continue
                if normalize(fight["name"]) in excluded:
                    continue
                seen_diffs[DIFFICULTY_NAMES.get(fight.get("difficulty"), str(fight.get("difficulty")))] += 1
                if fight.get("difficulty") not in wanted:
                    continue
                if boss_key and normalize(fight["name"]) != boss_key:
                    continue
                participants = {}
                for pid in fight.get("friendlyPlayers") or []:
                    actor = actors.get(pid)
                    if actor:
                        participants[lab.actor_label(actor)] = actor["class"]
                lowered = {n.lower() for n in participants} | {n.lower().split("-")[0] for n in participants}
                if player_key and player_key not in lowered:
                    continue
                selected.append((fight, participants))

            if not selected:
                present = ", ".join(f"{n} {dn}" for dn, n in seen_diffs.most_common()) or "no boss fights at all"
                print(f"    -> 0 pulls used from this report. Boss fights in it: {present}. "
                      f"Included difficulties: {', '.join(DIFFICULTY_NAMES[w] for w in sorted(wanted))}"
                      + (" - add --difficulty normal heroic mythic (or DIFFICULTIES in .env) to include Normal."
                         if seen_diffs.get("Normal") else ""))
                meta[code] = report["endTime"]
                save_meta(meta)
                continue

            # ---- batched per-fight tables, then events + rankings from the pool
            bundles = get_fight_bundles(code, [f for f, _ in selected], needs_refresh, pool)

            def fetch_fight(item):
                fight, participants = item
                refresh = needs_refresh(fight)
                events = get_damage_events(code, fight, actors, ability_names, npc_names, lab, refresh=refresh)
                parses = get_parses(code, fight, lab, refresh=refresh)
                return fight["id"], events, parses

            per_fight = {fid: (events, parses) for fid, events, parses in pool.map(fetch_fight, selected)}

            # ---- deaths first (needed to know whose casts to fetch)
            deaths_by_fight = {}
            for fight, participants in selected:
                deaths = deaths_from_table(bundles[fight["id"]].get("deaths"), fight, actors, lab)
                attach_recaps(deaths, per_fight[fight["id"]][0], window)
                deaths_by_fight[fight["id"]] = deaths
            cast_items = [(fight, deaths_by_fight[fight["id"]][0], needs_refresh(fight))
                          for fight, _ in selected if deaths_by_fight[fight["id"]]]
            casts = get_first_death_casts(code, cast_items, window, pool)
            id_cats = consumable_ability_ids(ability_names, cons_patterns)
            cons_casts = get_consumable_casts(code, [f for f, _ in selected], list(id_cats), needs_refresh, pool)

            new_lines = []
            for fight, participants in selected:
                fid = fight["id"]
                events, parses = per_fight[fid]
                deaths = deaths_by_fight[fid]
                if deaths and fid in casts:
                    attach_casts(deaths[0], casts[fid]["casts"], casts[fid]["buffs"], fight, actors, lab, ability_names, def_patterns)
                bundle = bundles[fid]
                damage_done, healing_done = player_tables_from_bundle(bundle, actors, lab, participants)
                consumables = consumables_from_cinfo(bundle.get("cinfo"), actors, lab, participants, ability_names, cons_patterns)
                prepotted, potions = consumable_use(cons_casts.get(fid), actors, lab, participants, id_cats, fight["startTime"])
                if fid in cons_casts:
                    for name in participants:
                        consumables.setdefault(name, {})["prepot"] = name in prepotted
                key = (fight["name"], DIFFICULTY_NAMES[fight["difficulty"]])
                absolute_start_ms = report["startTime"] + fight["startTime"]
                pull_dt = datetime.fromtimestamp(absolute_start_ms / 1000, tz=tz)
                boss_pct = 0.0 if fight.get("kill") else (fight.get("bossPercentage") or 0.0)
                fight_pct = 0.0 if fight.get("kill") else (fight.get("fightPercentage") if fight.get("fightPercentage") is not None else boss_pct)

                pull = {
                    "report_code": code,
                    "report_title": report["title"],
                    "zone": zone_name,
                    "night": night_label,
                    "night_type": night_type,
                    "fight_id": fid,
                    "encounter_id": fight.get("encounterID"),
                    "zone_id": (report.get("zone") or {}).get("id"),
                    "kill": bool(fight.get("kill")),
                    # boss HP left (what WCL's fight list shows) and fight progress left
                    # (WCL's fightPercentage: accounts for phases / council bosses)
                    "boss_percentage": boss_pct,
                    "fight_percentage": fight_pct,
                    "duration_seconds": round((fight["endTime"] - fight["startTime"]) / 1000, 1),
                    "absolute_start_ms": absolute_start_ms,
                    "pull_time": pull_dt.strftime("%H:%M"),
                    "participants": participants,  # label -> class
                    "phase": phase_at_end(fight, phase_names, transitions),
                    "phase_timeline": phase_timeline(fight, phase_names, transitions),
                    "deaths": deaths,
                    "damage_taken": aggregate_damage(events),
                    "damage_done": damage_done,
                    "healing_done": healing_done,
                    "parses": parses,
                    "interrupts": counts_from_table(bundle.get("interrupts"), actors, lab, participants),
                    "dispels": counts_from_table(bundle.get("dispels"), actors, lab, participants),
                    "consumables": consumables,          # {player: {flask, food, vantus, rune, prepot}}
                    "consumable_use": potions,           # {player: {combat_potion, healing_potion, mana_potion, healthstone}} during the pull
                    "has_extras": bool(bundle.get("extras")),
                }
                bosses.setdefault(key, []).append(pull)
                if changed or seen_end is None:
                    new_lines.append(f"    {fight['name']} fight {fid}: {len(deaths)} deaths, {len(events)} damage events")
            for line in new_lines:
                print(line)
            meta[code] = report["endTime"]
            save_meta(meta)
    finally:
        pool.shutdown(wait=True)
        _refresh_current = False

    print(cache.summary())
    if cache.stats["api_calls"] == 0:
        print("Nothing new on WCL since last run - everything came from cache.")

    for key, pulls in bosses.items():
        pulls.sort(key=lambda p: p["absolute_start_ms"])
        if progression_only:
            for i, p in enumerate(pulls):
                if p["kill"]:
                    del pulls[i + 1:]
                    break

    return bosses
