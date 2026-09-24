# WCL Multi-Report Analyzer

Aggregates several raid nights of Warcraft Logs reports and builds a single
HTML dashboard (Home, one tab per boss, Raid, Players, Mythic+) with
progression, death, damage-taken, preparation and utility analysis - like
WCL's paid "Multiple Report Analysis", but yours, and with more in it.

## Setup (once)

1. Copy `.env.example` to `.env` and fill in:
   - `WCL_CLIENT_ID` / `WCL_CLIENT_SECRET` (from https://www.warcraftlogs.com/api/clients/)
   - `GUILD_NAME`, `GUILD_SERVER_SLUG`, `GUILD_SERVER_REGION` - exactly as in
     your guild's WCL URL, e.g. `warcraftlogs.com/guild/us/area-52/My%20Guild`
     -> region `US`, slug `area-52`, name `My Guild`.
   - `RAID_TIMEZONE` - so raid nights are labelled in your local time.
   - `DIFFICULTIES=normal,heroic,mythic` - default difficulties (else heroic + mythic).

2. Create and activate a virtual environment, then install deps:
   ```
   python -m venv venv
   source venv/bin/activate.fish     # fish shell (use venv/bin/activate for bash/zsh)
   pip install -r requirements.txt
   ```

## Every time you want a dashboard

```
source venv/bin/activate.fish
python build_dashboard.py 2026-09-01 2026-09-21
```

| Option | Effect |
|---|---|
| `--difficulty heroic mythic` | Which difficulties to include (default: `DIFFICULTIES` in .env, else heroic + mythic) |
| `--zone Manaforge` | Only reports from that raid |
| `--boss "Ula'tek"` | Only one boss |
| `--progression-only` | Only pulls up to and including the first kill of each boss |
| `--player Somedude` | Only pulls that player was in (recruit / trial evaluation) |
| `--nights main` / `open` | Only main raid nights (`MAIN_RAID_DAYS` in .env, e.g. `Thu,Sun`) or only the other, "open" nights |
| `--callouts anonymous|named|off` | Whether Home callouts name individuals (default anonymous) |
| `--add-report CODE ...` | Add report codes/URLs to `nights.json` `_include` so they are part of every build from now on, then build |
| `--reports CODE ...` | One-off: build from only these report codes/URLs, ignoring the guild page |
| `--refresh` | Ignore the cache and re-download everything |
| `--mplus` / `--no-mplus` | Force / skip the Raider.IO refresh |
| `--uncompressed` | Embed the per-boss data as plain JSON (bigger file, easier to debug) |
| `-o file.html` | Output path |

The file is self-contained apart from Plotly, which loads from its CDN, so it
needs internet to draw charts. Per-boss data is gzip-compressed inside the
file and inflated by the browser (any browser from 2023 on: Chrome 80+,
Firefox 113+, Safari 16.4+). A month of raiding is about 1.7 MB - small
enough to drop straight into Discord.

Deep links work: `dashboard.html#tab3` opens a boss tab, `#tab3:deaths` also
scrolls to its Deaths section.

## Does it fetch fresh data?

Every run asks WCL for the current list of reports in your date range - that
is never cached, so a new raid night is always found. Data tied to a specific
report is cached in `.cache/` because finished reports never change:

- Each report's `endTime` from the fresh list is compared with the value seen
  when it was cached. If it changed (a live log that grew), only the fights
  that ended after the old `endTime` are re-downloaded; finished fights stay
  cached. The console shows `[new report]`, `[unchanged - cached]` or
  `[changed - re-downloading new fights]` per report.
- Per-fight tables (damage, healing, deaths, interrupts, dispels, pull-start
  buffs) are fetched five fights per request and cached per fight; damage
  events and rankings are fetched from a small thread pool (`WCL_PARALLEL`,
  default 4). Requests time out after 60 s and retry with backoff on rate
  limits and network errors.
- The run ends with e.g. `WCL API calls this run: 41 (of which 3 re-downloaded
  recent reports) - cache hits: 1204`. A first build of a month takes a couple
  of minutes; a rebuild with nothing new takes seconds.

## Home tab

Bosses killed / total, nights, pulls, combat time; a **progress strip** (one
box per boss - click to open the tab); **progression by first kills** - a
step chart of how many bosses of each difficulty had been killed at least
once by the end of each raid night, with a table of first-kill night, pulls
and nights to the first kill per boss; **"Worth a look"** callouts computed
from the data: progression trend (median of the three best pulls per night,
how many pulls reached the deepest phase), what starts the wipes, share of
first deaths with no defensive cast, a player who starts the wipe far more
often than the median, an avoidable-damage outlier, pulls started without
flask or food, last night's idle share, regulars missing on the last main
night, avoidable-list review flags, this week's M+ requirement; and a **last
raid night** panel. With both main and open nights in range, Home shows one
section per type.

By default the callouts **name nobody** - the file is meant to be shared.
`--callouts named` (or `HOME_CALLOUTS=named`) produces a private build for the
raid lead; `--callouts off` drops the cards about individuals.

## Global filters (toolbar)

**Nights** (main + open / main / open), **Raid night** and **Player** apply
to every boss tab and to the Players tab. Pick a night and each boss badge
shows that night's best pull and pull count (bosses not pulled are greyed
out); pick a player and every tab opens on their focus block (their numbers
vs the raid median, rank, their deaths with the defensives they cast, their
row highlighted), while the Players tab becomes a per-boss breakdown for
them. Clicking pulls inside a tab narrows further. Esc or "clear filters"
resets everything. "wide layout" is remembered between visits.

Night classification: `MAIN_RAID_DAYS` (e.g. `Thu,Sun`) are main nights;
`OPEN_RAID_DAYS` in .env or `_open_days` in `nights.json` (e.g. `["Mon"]`)
are open nights; a report on any other weekday is **not a raid night and is
skipped** (the console says so). A report title containing an
`OPEN_NIGHT_KEYWORDS` word counts as open. If no open days are configured,
every non-main night is open. Override per report code or date in
`nights.json` with `main`, `open` or `skip` (see `nights.example.json`); its
`_ignore` list drops reports, `_include` adds logs that are not on the guild
page.

## What each boss tab contains

Everything below the pull grid is rendered in the browser for the current
selection (all pulls, a night, a set of pulls, or one pull). Click a pull,
ctrl/shift-click several, click a night chip or a point in the progression
chart. A section navigation row jumps between sections.

| Section | What it is |
|---|---|
| Pulls | WCL-style grid (compact mode available): boss HP left (or KILL), pull number, time, duration, deaths, **fight %** (WCL's fight progress when it differs from boss HP - phases, council bosses), phase the pull ended in; break tiles between pulls. On a progression boss a **phase strip** shows how often and how fast each phase was reached |
| Progression | HP-left chart with night separators and break lines (nights differ by colour, line style and marker); Breaks table (5 pulls before vs after); **Phases**: wipes by phase and **time to reach each phase** per pull with median/fastest/slowest; per-night table with median time to first death |
| Summary | WCL Summary: damage done by source, healing done by source, damage taken by ability |
| Damage done / Healing done | Grouped by role: parse (kills only), amount, DPS/HPS, **Active DPS**, median and best pull, active %, pulls; per-pull DPS box plot; **median DPS per night** for the top DPS (is the raid getting better or luckier) |
| Deaths | First death of every pull: what really killed them (last seconds), who, when, **in which phase**, one-shots, avoidable involvement, **defensives** (own casts and externals received, or "none"); **wipe anatomy** (first→second death gap, cascades within 10 s); per-player "started the wipe" and "no defensive" counts; expandable recap with every cast in the window and every external received. A single pull shows every death in order |
| Damage taken | Damage/hits per ability (hits = separate occasions, not ticks), player x ability heatmap with values, when avoidable hits land, players table with role and *Hide tanks*, abilities table with *Cast by*, *Who gets hit* (raid-wide / tank / few / spread) and ⚠ flags for avoidable-listed abilities that behave like unavoidable damage. A **phase filter** restricts hit counts to one phase |
| Preparation & consumables | Flask, food, Vantus rune, augment rune at pull start (combatant info); **pre-pot** (combat potion cast in the 5 s before the pull); **combat potions, healing potions, Healthstones and mana potions used during the pull**, per player and per pull (from cast events - WCL's Casts table omits item uses) |
| Interrupts & dispels | Counts and per-pull rates per player |

A difficulty segment above the tabs shows one difficulty's boss tabs at a
time (remembered between visits); on phones a drop-down replaces the tab bar.

## Raid tab

The raid as an organisation: **night report** (bosses pulled, pulls, kills,
boss combat, trash, idle, pulls/hour, median recovery, breaks, players,
**bench** = in the raid but in no boss pull) with a minutes-per-boss chart;
**attendance matrix** (main nights only; `bench` and `from #n` mark players
who sat out or joined mid-night);
**average WCL parse per player across kills** - the one performance number
that is fair across bosses; farm kill-time trend. One Raid tab per night type
when both exist.

## Excluding a boss

Encounters you do not want in any statistic (a rare, a world boss the logger
caught) go in `nights.json` under `_exclude_bosses`, or in `EXCLUDE_BOSSES`
in `.env`. The default file excludes `Nymrissa Wavecaller`.

## Posting to Discord automatically

```
python post_discord.py dashboard_2026-08-23_to_2026-09-21.html     # needs DISCORD_WEBHOOK_URL in .env
```

`systemd/` holds a user service and timer that build the tier-to-date
dashboard and post it after every raid night (Thu, Sun, Mon 23:45); the
service file has the install commands. `post_discord.py` refuses files over
Discord's 10 MB limit.

## Configuration files

| File | Purpose |
|---|---|
| `avoidable.json` | Per-boss list of avoidable abilities; `"*"` for every boss; `_ignore` for trinket/enchant effects. Build once, then fill it from `abilities_seen.json` (written every build) and the ⚠ flags in the ability tables |
| `consumables.json` | What counts as flask / food / vantus / rune (aura names at pull start) and combat / healing / mana potion and Healthstone (cast names; `-word` excludes). Defaults built in; see `consumables.example.json` |
| `defensives.json` | Which casts count as a defensive in the death tables. Defaults built in (personals, externals, Healthstone, healing potions); see `defensives.example.json` |
| `nights.json` | Night type overrides, `_include`, `_ignore` |
| `roster.txt` | Characters tracked for Mythic+ |

Ability names must match WCL's spelling; case and punctuation are ignored.

## Mythic+ tab (Raider.IO)

```
python mplus.py --roster-from-raid 2026-09-01 2026-09-21 --nights main   # once: roster.txt from main-night raiders
python mplus.py                                                          # weekly: fetch + merge into mplus_history.json
python mplus.py --show   /   --failing                                   # print without fetching
```

Weekly requirement (default **4 runs at +10 or higher**; `MPLUS_REQUIRED_RUNS`,
`MPLUS_REQUIRED_LEVEL`, `MPLUS_REQUIRE_TIMED`). Raider.IO only exposes this
week and last week, so `mplus.py` snapshots into `mplus_history.json`;
`build_dashboard.py` runs that refresh automatically when the history is
older than `MPLUS_MAX_AGE_HOURS` (12).

## .env reference

| Key | Meaning |
|---|---|
| `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` | WCL v2 API client |
| `GUILD_NAME`, `GUILD_SERVER_SLUG`, `GUILD_SERVER_REGION` | as in the guild's WCL URL |
| `RAID_TIMEZONE` | e.g. Europe/Amsterdam |
| `DIFFICULTIES` | default difficulties, e.g. `normal,heroic,mythic` |
| `DEATH_WINDOW_SECONDS` (6) | recap / defensives window before each death |
| `BREAK_MINUTES` (4.5) | idle minutes between pulls that count as a break |
| `MAIN_RAID_DAYS`, `OPEN_RAID_DAYS`, `OPEN_NIGHT_KEYWORDS` | night classification (open days can also live in `nights.json` `_open_days`) |
| `BOSS_ORDER` | bosses forced to the front of the tab order |
| `HOME_CALLOUTS` (anonymous) | Home callout mode |
| `WCL_PARALLEL` (4), `WCL_TIMEOUT_SECONDS` (60), `WCL_MAX_ATTEMPTS` (4) | fetching |
| `MPLUS_*`, `RIO_REGION`, `RESET_WEEKDAY`, `RESET_HOUR_UTC` | Mythic+ |

## Tests

```
pip install pytest quickjs          # quickjs is optional: enables the JS syntax check
python tests/make_fixtures.py       # once, needs network: records one small report into tests/fixtures/
python -m pytest -q
```

The suite replays a real report offline (any network access fails the test),
checks the payload round-trip and the HTML structure, and parses `dash.js`.

## Files

| File | Purpose |
|---|---|
| `wcl_client.py` | OAuth token + GraphQL wrapper with timeout and retries |
| `cache.py` | On-disk cache: query-keyed entries and per-fight entries |
| `fetch_reports.py` | Lists guild reports in a date range |
| `collect_data.py` | Everything per pull: fights, phases, deaths, damage taken, tables, casts, consumables |
| `build_dashboard.py` | CLI entry point |
| `dash/` | Rendering package: `common`, `payload`, `home`, `raid`, `players`, `mplus_tab`, `page`, `static/dash.js`, `static/dash.css` |
| `mplus.py` | Raider.IO Mythic+ tracker |
| `tests/` | pytest suite + fixture recorder |
| `legacy/merge_pulls.py` | Early single-boss CLI, kept for reference |
