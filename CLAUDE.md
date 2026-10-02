# WCL Multi-Report Analyzer — project handoff (CLAUDE.md)

> Read this first. It is the complete record of what exists, why it was built the way it was,
> and what is unfinished. Claude Code reads this file automatically from the project root.
> Detailed per-session change records live in `docs/CHANGES_<date>.md`; the review that drove the
> 2026-09-23 rework is `docs/reviews/REVIEW_2026-09-23.md`. **Every code change must be recorded in a tagged .md.**
>
> Tag legend used throughout:
> `[ADDED]` new capability · `[CHANGED]` behaviour changed · `[FIXED]` bug fix · `[REMOVED]` deliberately taken out ·
> `[DECISION]` a design choice with a reason · `[CAVEAT]` a known limit to keep in mind · `[TODO]` not done yet

---

## 0. Working agreement for Claude Code — delegation policy `[ADDED 2026-09-25]`

The orchestrating Claude Code session **never does the work itself**. It plans, dispatches sub-agents, reads their
reports, and integrates. This is a standing instruction from the user and overrides the default "do it inline" behaviour.

- **Plan first.** Break the request into tasks with explicit inputs, files, constraints and acceptance criteria before
  dispatching anything. Non-trivial work gets a written plan (`docs/plans/` or the reply) that the user can correct.
- **One sub-agent per task.** Every task is its own `Agent` call with a self-contained prompt (context, files, the rules
  in this document, expected report format). Never bundle unrelated tasks into one agent.
- **Independent tasks run in parallel.** Dispatch them in the same message so they run concurrently. A task that depends
  on another waits for that agent's report.
- **Model routing — pass `model` on every `Agent` call, no exceptions:**

  | Task kind | Model | `model` value |
  |---|---|---|
  | Architecture, design decisions, hard bugs / root-cause analysis, code and security reviews | Fable 5.1 | `fable` |
  | Edits, tests, docs, refactors, fixtures, routine implementation from an existing plan | Opus 5.5 | `opus` |

  When in doubt about difficulty, start with Opus 5.5; escalate to Fable 5.1 if the report shows the agent got stuck.
- **Read the reports, not only the files.** A sub-agent's final report is the primary evidence. Read it in full, check
  its claims against the acceptance criteria, and relay what matters to the user. Re-read files to verify a specific
  claim, never as a substitute for reading the report.
- **Verification is delegated too.** `pytest`, the quickjs syntax check and headless-Firefox screenshots run inside a
  sub-agent (Opus 5.5) whose report must include the raw command output. Do not claim success without that output.
- **What the orchestrator may still do itself:** clarify requirements, write the plan, read reports, do the minimal
  orienting reads needed to write a good prompt (a single `grep`/`sed -n`, not a review), update memory, and run the
  `git commit` the user asked for. Everything else is dispatched.

---

## 1. What this is

A Python tool that reproduces Warcraft Logs' paid **Multiple Report Analysis** for the user's guild
("Serenity", EU, main realm Tarren Mill) and goes further: it aggregates every raid night in a date range
into a single self-contained **HTML dashboard** (Home, one tab per boss, Raid, Players, Mythic+) with
client-side filtering, and a Raider.IO-based Mythic+ tracker.

- Raid: **The Venomous Abyss** (8 bosses + Nymrissa Wavecaller, a rare/extra encounter). Current prog boss: **Ula'tek Heroic**.
- Main raid nights: **Thu + Sun**. **Mon/Wed** = open nights (different roster, Normal difficulty).
- User: `Omess` (Havoc Demon Hunter). Runs Arch/CachyOS, fish shell, Code-OSS, Python 3.14 in a venv. No `node`; Firefox is
  available for headless screenshots (`firefox --headless --new-instance --profile <fresh dir> --screenshot out.png <url>`;
  it captures from the document top only). `quickjs` (pip) is used for JS syntax checks.
- The dashboard is shared in the raid Discord, so it is treated as a **public artefact** (no names on Home; file must stay
  under Discord's 10 MB limit — it is ~1.7 MB per month now).

## 2. Repo layout

`[CHANGED 2026-09-24]` Folders group files by kind; `path.py` is the only module that knows where they are
(`ROOT`, `CONFIG_DIR`, `DATA_DIR`, `DASHBOARD_DIR`; creates `data/` and `dashboards/` on import).

```
build_dashboard.py   CLI only: args -> collect() -> dash.page.build_html() -> dashboards/; writes data/abilities_seen.json + data/tank_buffs_seen.json
mplus.py             Raider.IO Mythic+ tracker -> data/mplus_history.json; roster tools (--roster-from-raid [--nights main])
post_discord.py      Post a built dashboard to a Discord webhook
wcl_client.py        OAuth + GraphQL POST to WCL v2; timeout, retries/backoff (429/5xx/net/rate-limit), thread-safe; rateLimitData + WCLRateLimited
cache.py             On-disk JSON cache in data/cache/: cached_query (sha1(query+vars)) + get_entry/put_entry; lock; atomic writes
fetch_reports.py     Guild report list for a date range (NEVER cached)
collect_data.py      All data collection -> {(boss, difficulty): [pull, ...]}  (see §5)
path.py              Folder layout constants (import from here, never compute paths from __file__ elsewhere)
specs.py             Spec/role table SPECS {specID: (class, spec_token, role, simc_token, support)}; spec_of/role_sets/role_of_token  [2026-10-01]
analysis/            Per-player analysis (pure; wipe.py + mitigation.py import nothing from dash/ or collect_data)  [2026-10-02]
  player_metrics.py    PM_COLS (23 cols) + player_metrics(pull, avoidable, ignored, gear_gaps) -> {label: vector}; trim()
  wipe.py              wipe_cutoff_s(): post-wipe cutoff (WCL wipe call, else death-cascade heuristic)
  mitigation.py        tank_mitigation.json loader, am_ids_for(), digest_events() (per-player event digest), TANK_BUFFS_SEEN
  gear.py              roster_rules() (majority rule), gear_report() (ilvl + gap strings), latest_gear()
  severity.py          compute(): Good/Watch/Note per player x night x metric (baselines, tolerances, score, ADVICE)
dash/common.py       esc/fmt, avoidable config, roles/specs, table()/kpis()/player_cell()/empty_state()/gotab(), fig_html, breaks, all_pulls, player_stats
dash/payload.py      pull_grid() (server-rendered click surface) + pull_payload() (compact per-pull JSON, gzip+base64); all_metrics()/players_data() (Players block)
dash/home.py         Home tab: progress strip, insights(), last night
dash/raid.py         Raid tab: night report, attendance, parse table, kill-time trend
dash/players.py      Players tab (static part): team strip (no names), roster table (alphabetical; first-death sort when named)
dash/rollups.py      Named-build Raid-lead section (R1-R3, R5, R7-R9) from pm vectors + severity block  [2026-10-02]
dash/mplus_tab.py    Mythic+ tab + update_mplus_if_stale()
dash/page.py         Page assembly: header, toolbar, ARIA tablist, panels, inlines static/dash.css + static/dash.js
dash/static/dash.js  THE renderer for boss tabs (all sections) + global filters + Players-tab dynamic view
dash/static/dash.css Styles (dark theme, WoW class colours lightened for contrast, focus rings, reduced motion, responsive)
dash/static/tokens.css  Design tokens (the ONLY place colours/type/spacing live; Python load_tokens(), JS TOK read it)
config/              Files YOU edit (tracked, except nights.json and roster.txt which are per-guild and ignored)
  avoidable.json       Per-boss avoidable abilities + _ignore (+ _uncertain checklist)
  consumables.json / defensives.json   optional name-pattern overrides (defaults built in; *.example.json provided)
  tank_mitigation.json / gear_checks.json   tank active-mitigation ids, gear-check rules (see §8b; *.example.json provided)  [2026-10-02]
  nights.json          night-type overrides, _include / _ignore report codes
  roster.txt           Characters tracked for M+ (Name,realm-slug)
data/                Files the TOOL writes (whole folder ignored)
  cache/               WCL responses + report_meta.json (endTime seen per report)
  abilities_seen.json  Written every build: abilities per boss with hit counts + sources
  tank_buffs_seen.json Written every build with tank aura data: top 25 buff ids per tank spec (check tank_mitigation.json against it)
  mplus_history.json   Written by mplus.py; read by the dashboard
dashboards/          Built HTML (ignored: contains player names); default output of build_dashboard.py
docs/                CHANGES_<date>.md, ROADMAP_*.md, reviews/REVIEW_*.md, plans/ (incl. 2026-10-01-player-analysis-phase1-plan.md)
tests/               pytest suite; tests/make_fixtures.py records one report into tests/fixtures/ (offline replay)
tools/wcl_probe.py   One-off live WCL probe (never uses/writes the cache) -> docs/research/2026-09-25-player-analysis/06-live-probe.md
systemd/             user service + timer + build-and-post script
legacy/merge_pulls.py  superseded early CLI
```

## 3. Setup / run

```
python -m venv venv && source venv/bin/activate.fish     # fish shell!
pip install -r requirements.txt                          # requests, python-dotenv, plotly (+ pytest, quickjs for tests)
python build_dashboard.py 2026-08-23 2026-09-21          # -> dashboards/dashboard_<start>_to_<end>.html
python -m pytest -q                                      # 288 tests, offline
venv/bin/python tests/make_fixtures.py --clean          # re-record fixtures (network; default report 3w1jJ8BZ2m9kMrYG)
```

`[CHANGED 2026-10-01]` Tests include `tests/test_wcl_client.py` (rate-limit paths, fake session) and `tests/test_make_fixtures.py` (recorder).
`[ADDED 2026-10-02]` Phase 1 tests: `test_player_metrics.py`, `test_mitigation.py`, `test_gear.py`, `test_severity.py` (synthetic),
`test_players_tab.py` (deep links + the card rendered in quickjs for every fixture label), `test_rollups.py` (team strip privacy, named Raid lead).
Fixtures: `tests/fixtures/` is 6.85 MB; `make_fixtures.py` keeps gear/talentTree/stats for 3 players per fight, `buffs/mitigated/hitType/blocked`
on event pages, top 8 abilities, and stops above `SIZE_BUDGET` = 7.5 MB (`--clean` empties the fixture cache first; `--slim` re-slims only).

CLI (`build_dashboard.py`): `--difficulty ...` (default `DIFFICULTIES` in .env, else heroic mythic) · `--zone` · `--boss` · `--player` ·
`--progression-only` · `--nights {all,main,open}` · `--reports CODE...` · `--add-report CODE...` · `--callouts {anonymous,named,off}` ·
`--refresh` · `--mplus` / `--no-mplus` · `--uncompressed` (plain JSON payload) · `-o FILE`.
`[ADDED 2026-10-01]` Exit code **3** = stopped on the WCL hourly point limit (finished fights are cached; re-run later), or `--refresh` refused
because more than 80 % of the hour's points are already spent.

`[CAVEAT]` `.env` and `.env.example` are **protected by the Claude Code permission settings** (cannot be read or edited from
Claude Code). As of 2026-09-23 the user still has to add `DIFFICULTIES=normal,heroic,mythic` to `.env` by hand.

## 4. Configuration (.env)

| Key | Meaning |
|---|---|
| `WCL_CLIENT_ID`, `WCL_CLIENT_SECRET` | WCL v2 API client (client-credentials; public reports only) |
| `GUILD_NAME`, `GUILD_SERVER_SLUG`, `GUILD_SERVER_REGION` | exactly as in the guild's WCL URL |
| `RAID_TIMEZONE` | e.g. Europe/Amsterdam; night labels + M+ week boundaries |
| `DIFFICULTIES` | default difficulties (`normal,heroic,mythic`) |
| `DEATH_WINDOW_SECONDS` (6) | recap + defensive-cast window before each death |
| `BREAK_MINUTES` (4.5) | idle minutes between pulls that count as a break |
| `MAIN_RAID_DAYS` (Thu,Sun) / `OPEN_RAID_DAYS` (unset → `nights.json` `_open_days` = Mon) / `OPEN_NIGHT_KEYWORDS` (open) | night classification; other weekdays are skipped |
| `EXCLUDE_BOSSES` (unset → `nights.json` `_exclude_bosses` = Nymrissa Wavecaller) | encounters left out of every statistic |
| `DISCORD_WEBHOOK_URL` | for `post_discord.py` / the systemd timer |
| `BOSS_ORDER` (Nymrissa Wavecaller) | bosses forced to the front of the tab order |
| `HOME_CALLOUTS` (anonymous) | see §7 Home |
| `WCL_PARALLEL` (4) / `WCL_TIMEOUT_SECONDS` (60) / `WCL_MAX_ATTEMPTS` (4) | fetching |
| `WCL_RATE_WAIT_MAX` (900) | `[ADDED 2026-10-01]` optional, **user adds it to `.env` by hand**: max seconds to sleep for the hourly point reset when ≥ 95 % is spent; longer → stop (exit 3) |
| `MPLUS_REQUIRED_RUNS` (4) / `MPLUS_REQUIRED_LEVEL` (10) / `MPLUS_REQUIRE_TIMED` (false) / `MPLUS_MAX_AGE_HOURS` (12) | Mythic+ |
| `RIO_REGION`, `RESET_WEEKDAY`, `RESET_HOUR_UTC` | Raider.IO region / weekly reset |

## 5. Data collection (`collect_data.py`)

`collect(start, end, difficulties, boss, zone, player, progression_only, nights, reports)` returns
`{(boss_name, difficulty_name): [pull, ...]}` sorted chronologically.

**Two passes.** Pass 1 selects reports (guild list minus `_ignore`, plus `_include`, or `--reports`), classifies nights, fetches
`FIGHTS_QUERY` for each and feeds the actors to the `Labeller`. Pass 2 processes each report:
report-level `PHASES_QUERY`, `ABILITIES_QUERY`, `NPC_ACTORS_QUERY`; then **fight bundles**; then damage events + rankings per fight
from a `ThreadPoolExecutor`; then **casts before the first death**; then the pull dicts.

- `[ADDED 2026-09-23]` **Fight bundles** (v3): `DamageDone`, `Healing`, `Deaths`, `Interrupts`, `Dispels` tables + `CombatantInfo` events,
  5 fights per HTTP request via GraphQL aliases (`damage_12: table(...)`, `cinfo_12: events(...)`), cached **per fight** under
  `entry:bundle:v3:full:<code>:<fid>`. If WCL rejects the extras → warn once, fall back to `min` bundle (damage/healing/deaths).
  `[CAVEAT]` WCL's **Casts table omits item uses** (potions, Healthstones) - never use it for consumables.
- `[ADDED]` **Casts + buffs** (`events(dataType: Casts, sourceID: <dying actor>)`, `events(dataType: Buffs, targetID: ...)`) for the
  window before the first death of each pull, 10 pulls per request, key `entry:casts1:v2:<code>:<fid>:<window>`. `[DECISION]` first death only.
- `[ADDED]` **Consumable casts**: `events(dataType: Casts, filterExpression: "ability.id in (...)")` per fight from 5 s before the pull,
  ids = report abilities whose names match the cast categories in `consumables.json`; 10 fights per request, key
  `entry:cons:v1:<code>:<fid>:<ids-hash>`. Gives pre-pot + combat / healing / mana potion + Healthstone uses per player.
- `[ADDED 2026-09-29]` **Who pulled** (`get_pull_events()` + `pull_initiator()`): per fight `events(dataType: DamageDone / Casts, hostilityType: Friendlies)`
  from `PULL_TOLERANCE_MS` (1 000) before to `PULL_WINDOW_MS` (5 000) after fight start (aliases `pbd_<fid>` / `pbc_<fid>`, limits 1000 / 500),
  10 fights per request, key `entry:puller:v1:<code>:<fid>`; enemy and pet ids from the cached report-level `PULL_ACTORS_QUERY`
  (`fights { enemyNPCs, friendlyPets }` + `masterData` Pet actors; per-fight `friendlyPets` wins). Puller = participant (pet → owner, `via_pet`)
  behind the earliest `damage` on an enemy, or `cast` (never `begincast`) on an enemy whose ability also damages an enemy in the window
  or is in `PULL_TAUNTS`; same ms → damage before cast, then log order; nothing → `None`. `[DECISION]` the damage/taunt condition because
  WCL logs self-buffs (Ascendance) with the caster's current target. `WCLError` → warn once, pullers unknown.
- `[ADDED 2026-10-01]` **Pagination rule**: every aliased `events` part requests `nextPageTimestamp`; `_follow_pages()` fetches the rest with
  single-alias follow-ups (1 point / `count_api_call(1)` each; the cursor must strictly advance, at most `MAX_PAGES` = 50 follow-ups) and concatenates (bundle `cinfo`, consumables, first-death casts + buffs;
  `get_pull_events()` deliberately reads only the first page). Consumables pass `filterExpression` as the `$filter` variable.
  First-death buffs are kept only if `targetID` is the dying actor (externals no longer include buffs they cast on others).
- `[ADDED 2026-10-01]` **Spec table**: `specs.py` (40 specIDs incl. 1480 Devourer); `spec_ids_from_cinfo()` → pull key `spec_ids`;
  `dash.common.pull_specs()` prefers the specID; role sets reach `dash.js` via `<script type='application/json' id='cfg'>`.
- `[ADDED 2026-10-01]` **Rate limits** (`wcl_client.py`): `rateLimitData` appended at send time; `WCLRateLimited` (not a `WCLError`) after
  the short backoff when ≥ 95 % is spent and the reset is beyond `WCL_RATE_WAIT_MAX`. Cost is ~1 point per alias / page, independent of size;
  limit 9000 points/hour (live probe, `docs/research/2026-09-25-player-analysis/06-live-probe.md`). Separate `x-ratelimit-limit`
  request-count header: observed 300 (probe) and 800 (build); window length unknown. The long wait sleeps `pointsResetIn` minus the time
  since that value was read, plus `RATE_WAIT_MARGIN` (5 s).
- `[ADDED]` **Labeller**: player identity is (name, realm); label is the bare name unless the name exists on >1 realm in the dataset →
  `Name-Realm`. Tables matched by actor `id`, rankings by `name` + `server.name`, events by `targetID`.
- `[CHANGED]` **Refresh granularity**: a report with a changed endTime re-fetches report-level queries and only fights with
  `report.startTime + fight.endTime > seen_end`. `REPORT_META_QUERY` is never cached (was the cause of stale `_include` reports).
- `[DECISION]` fight list fetched once per report and filtered in Python. `[DECISION]` **Hits = instances, not events**
  (`INSTANCE_GAP_SECONDS` 2.5). `[DECISION]` self-inflicted damage excluded from stats, kept in recaps tagged `self`.
- `NIGHT_FIGHTS` — every fight incl. trash per night, so breaks/idle exclude trash (`busy_ms_between()`).
- Night classification (`classify_night` → `main` / `open` / `None`): nights.json by code → by date (`main`/`open`/`skip`) → title keyword →
  weekday in `MAIN_RAID_DAYS` → main; in open days (`OPEN_RAID_DAYS` env, else `nights.json._open_days`, currently `["Mon"]`) → open;
  otherwise **None = not a raid night, report skipped** (console explains). `[ADDED 2026-09-23]` at the user's request: only Mondays are open nights.

**Pull dict fields:** `report_code, report_title, zone, zone_id, night, night_type, fight_id, encounter_id, kill,
boss_percentage (boss HP left), fight_percentage (WCL fightPercentage, phases/council aware), duration_seconds, absolute_start_ms,
pull_time, participants {label: class}, phase, phase_timeline [[name, seconds]], deaths [...], damage_taken [...], damage_done [...],
healing_done [...], parses {label: {dps, hps}}, interrupts {label: n}, dispels {label: n},
consumables {label: {flask, food, vantus, rune, prepot}}, consumable_use {label: {combat_potion, healing_potion, mana_potion, healthstone}}, has_extras,
pulled_by {player, class, ability, offset_ms (int, from fight start), kind (damage|cast), via_pet} or None,
spec_ids {label: specID} (from CombatantInfo; {} without extras), wipe_called_s (seconds to WCL's wipe call, or None),
wipe_cutoff_s, player_events {label: {dtk, hits, hits_buffs, dodge_parry_miss[, am_up, amw_num, amw_den, mit_num, mit_den]}},
gear {label: [[slot, ilvl, enchant_id_or_0, n_gems, item_id], ...]}`. `[ADDED 2026-10-02]` (the last three, Phase 1; `parses[label]` also carries
`bdps`/`bhps` (bracket percentile) and `spec`; `healing_done[i]` carries `overheal`).
`[CAVEAT 2026-10-01]` `wipe_called_s` is `None` whenever WCL has no wipe call — never read `None` as a kill. In practice it is **always**
`None` for this guild: a cache scan found 0 of 201 boss wipes across 18 reports with a `wipeCalledTime` (the loggers never use WCL's wipe-call
feature), so post-wipe exclusion needs a fallback heuristic (see `docs/CHANGES_2026-10-01.md` Open / next).
Neither key is emitted in the payload.
`[ADDED 2026-10-02]` **Wipe cutoff** (`analysis/wipe.py`, pull key `wipe_cutoff_s`, payload `wc`): `wipe_called_s` when set; kills → `None`;
otherwise the longest run of deaths with gaps ≤ 10 s (`WIPE_CASCADE_GAP_S`), ≥ 3 deaths (`WIPE_CASCADE_MIN_DEATHS`), ending ≤ 20 s
(`WIPE_TAIL_S`) before the pull end → cutoff = the run's **first** death (it still counts); else `None`. Applied (`seconds <= cutoff`) to
`dth/avh/avm/dtk/dtps/mit/am/amw`, not to `fd/alv`. Fixture fight 8 → 92.5 s. `player_events` / `gear` are not emitted raw.

- `deaths[i]`: `player, actor_id, class, seconds_into_fight, ability (killing blow), recap, window_damage, top_contributor, biggest_hit,
  one_shot, hits_in_window`; first death additionally `casts [[seconds_before, name]], defensives [...], has_cast_data`.
- `damage_taken[i]`: `player, class, ability, hits (instances), ticks, events, amount, hit_amount, tick_amount, unmitigated, avoided,
  uptime_seconds, times, sources`.
- `[ADDED 2026-10-02]` Damage events (inside `collect()`, used by recaps and `digest_events`) also keep `buffs` (dot-separated aura ids or None),
  `mitigated`, `hit_type`, `blocked`. `TANK_BUFFS_SEEN` (cleared per `collect()`) feeds `data/tank_buffs_seen.json`.

Console prints per report: night type, `[new report] / [unchanged - cached] / [changed since last run - re-downloading new fights]`,
per fight of new/changed reports `<boss> fight N: D deaths, E damage events, pulled by <name> (<ability>, +0.05 s)` (or `puller unknown`),
`-> 0 pulls used ...` hints, and `WCL API calls this run: N (of which M re-downloaded recent reports) - cache hits: K`.
`[ADDED 2026-10-01]` Also: `  [wcl] <op> <spent>/<limit> pts this hour, reset in <s> s[; <previous op> cost N pts]` per request (WCL reports
`pointsSpentThisHour` one response late, so the cost is attributed to the previous request, only when nothing else was in flight),
`WCL points this run: X of Y per hour ...` at the end (`rate_summary()`), `  (page 2+ needed for <code>:<fid> <kind>)` once per fight/kind,
and `unknown specID N for <label> (<class>)` once per id.

## 6. Cache (`cache.py`)

- `cached_query(query, vars, refresh)` keyed by sha1(query text + vars) → changing a query's text re-fetches automatically.
- `get_entry(key, refresh)` / `put_entry(key, data)` for explicit keys (bundles, casts). `count_api_call()` for batched requests.
- Invalidation by **endTime change** per report, at **fight granularity** (§5). `report_meta.json` stores the endTime seen.
- Thread-safe (lock around stats; temp-file + `os.replace` writes).
- `[ADDED 2026-10-01]` `rateLimitData` is appended by `wcl_client` at send time and stripped from the response before caching, so cache keys and
  cached files are unaffected. Changing `FIGHTS_QUERY` text (e.g. `wipeCalledTime`) re-fetches one cheap call (~2 points) per report.

## 7. Dashboard

**Single renderer** `[DECISION 2026-09-23]`: boss tabs are rendered only in the browser (`dash/static/dash.js`) from the per-boss
payload; Python emits the pull grid + payload. Reason: the Python and JS versions of every table/chart had drifted and doubled the
file size. Home, Raid, Players (static part) and Mythic+ stay Python-rendered (Plotly `to_html`).

**Design system** `[CHANGED 2026-09-24]`: visual system replicated from `serenity-dashboard-rebuilt.html`. Tokens in `dash/static/tokens.css`
(surfaces, ink, accent `#c9a227`, status, six series colours, 15 px base type, 4 px spacing). Patterns: `kpis()` / `kpisHtml()` KPI tiles,
`.progress-grid .boss` cards, `article.insight` with `Good/Watch/Note` badge + jump button, `table()` / `tbl()` = `.scroller` + visible caption +
`<th><button>` sorting via `aria-sort`, `player_cell()` / `playerCell()`, `figure.chart` around every chart. The boss-HP progression chart is inline
SVG (`drawProgression`); all other charts are Plotly styled from the tokens. `tests/test_dashboard.py::test_no_raw_colours_outside_tokens` forbids
hex literals in `dash.js` and `dash/*.py`. Density defaults (`limit`, rows past it behind "Show all N"): 10 per role table (Damage / Healing done), 15 in the player tables
(Deaths → Players, Damage taken → Players, Preparation, Interrupts & dispels, Players tab), 12 abilities; box plot capped at 15, line chart top 6.
Charts with < 4 values (lines, histograms, every box) or < 2 non-zero bar categories fall back to a sentence (`chart()` / `fig_html()` skip
rule, applied where the call site passes a `fallback`; every Deaths chart and the box plot do). Pull boxes, SVG points
and the grid legend share four HP bands: kill / near (< 10 %) / mid (< 40 %) / far, via `hp_band()` / `hpBand`; change both together.
Page chrome: `header.page`, a toolbar that scrolls away (a `<details class='filters'>` disclosure, closed on phones, summary "Filters (n active)"),
a sticky `nav.tabnav` (the strip wraps into rows on desktop, `--tabnav-h` is measured by `dash.js`; tab `<select>` with optgroups under
700 px), a loading skeleton with the tab strip `inert` until `dashReady` (tab wiring happens before the payloads inflate; a payload that
cannot be decoded empties only its own tab), and
`footer.page` with the build info.

**Payload** (`dash/payload.py`): `<script type='application/gzip+base64' id='data_tabN'>` — gzip+base64 JSON, inflated with
`DecompressionStream`; `--uncompressed` embeds `application/json`. Per pull: `i,n,t,k,p (boss HP%),fp (fight%),d,a,o,ph,pt,code,fid,
parts,specs,parses,deaths (recap capped 8; first death has hc/def/cs),dt [[player,ability,hits,amount,(times for avoidable)]],dd,hd,
ir,ds,cons {name:[flags in cats order]},hx,pb [label,ability,offset_ms,'d'|'c'] or null`. Boss level: `boss,diff,avoidable,ignored,break_minutes,busy,src {ability:[top sources]},cats`.
`[ADDED 2026-10-02]` Phase 1: per pull `pm {label: [≤ 23 ints/null, trailing nulls popped]}` (columns = boss-level `pmcols` = `PM_COLS`:
`act dps hps dth fd alv avh avm dtk dtps prep pot hs ir ds ilvl rp bp oh mit am amw gap`) and `wc` (wipe cutoff s or null); `deaths[].av`
(0/1: killing blow or ≥ 50 % of window damage avoidable); a dying **tank**'s recap rows get a 6th element `1/0/null` = AM buff up at that hit
(rendered as a Mitigation column by `recapHtml`); `dd`/`hd` rows are 6 elements `[name, class, spec, total, active_s, ilvl]`; `parses` carry
`bdps/bhps/spec`. **Players block** `<script ... id='data_tabPlayers'>` (same encoding) = `{cols, roster {label: {cl, spec, role, pulls, support}},
nights [[night, type, startMs]], sev {label: {night: [[metric, value, baseline, bkind, level, score, tpl, affected, pulls(, rank)]]}},
gear {label: {ilvl, gaps, ilvl_min, ilvl_max}}, advice {tpl: text}, named}` from `dash/payload.py::players_data()` + `analysis/severity.compute()`.
The `cfg` script carries `named` (true only for `--callouts named`). Fixture: 4,659 → 5,460 B base64 per pull; real builds ≈ +1.0–1.1 KB/pull.

**Tab order**: Home · bosses Normal→Heroic→Mythic then WCL zone order (`BOSS_ORDER` pins) · Raid (per night type) · Players · Mythic+.
Tabs are an ARIA tablist with arrow-key navigation; deep links `#tabN` and `#tabN:section` (`prog,sum,dd,hd,deaths,dt,prep,util`), and
`[ADDED 2026-10-02]` `#tabPlayers?player=<URL-encoded label>` (`playerHash()` / `parsePlayerHash()`; the hash is split on `?` before `:`;
written on change while the Players tab is active; last player remembered in localStorage `wcl_dash_player`).

**Toolbar**: Nights (when both types exist) · Raid night · Player · clear · wide (persisted in localStorage). Filters apply to every
boss tab (badges, greyed-out bosses, jump to first boss with pulls) and to the Players tab. Esc clears. `[CHANGED 2026-09-24]` not sticky;
a `<details class='filters'>` (open on desktop, closed under 700 px) whose summary counts the active filters.

**Home**: per night type: KPI tiles; progress cards (buttons); **Progression by first kills** (`progression_timeline()`: step chart
of bosses killed at least once per raid night, one trace per difficulty + table with first-kill night / pulls / nights per boss in zone
order); "Worth a look" callouts: progression trend (median of 3 best
pulls per night), pulls reaching the deepest phase, top wipe-starter, share of first deaths with no defensive cast, wipe-starter
outlier, avoidable outlier, flask/food missing, idle share of last night, regulars missing, avoidable-list review flags (with
difficulty), M+ met/total, `[ADDED 2026-10-02]` "Preparation: N% flask and food" (rates only, vs previous night). `[DECISION]` default
`anonymous`; `named` = private RL build; `off`.

**Boss tab sections (JS, in order)**: Pulls grid (boss HP band, fight % line when it differs >1 pt, phase, breaks) · KPI tiles ·
Progression (inline-SVG HP chart + "Show the N pulls as a table" incl. a **Pulled by** column, breaks table, **Phases**: wipes by phase + **time-to-phase** chart/table, per-night table) · Summary (+ **Who pulled** table: Player / Pulls / Share / Most used opener, Unknown row) ·
Damage done / Healing done (role groups, parse, active DPS, median/best, box plot) · Deaths (first-death KPI tiles incl. "no defensive
cast", charts, histogram, players table, first-death table with **Defensives cast** + recap incl. casts; single pull = all deaths) ·
Damage taken (KPI tiles, charts, heatmap, avoidable timing histogram, players table with Role + Hide tanks, abilities table with Cast by /
Who gets hit / "review" tag) · **Preparation** (flask/food/rune/prepot per player) · **Interrupts & dispels**. Player filter adds the
focus block. All tables sortable (header buttons). Charts are drawn one by one; failures show in the `#jsError` banner at the top.
Section headings are `h2` / `h3` (no `h4`/`h5` in `dash.js`); Plotly titles are `<h3>` above the plot, never in the canvas; no modebar.

**Raid tab**: night report (idle/trash aware), attendance matrix (main nights), average parse across kills, farm kill times.
`[DECISION]` no raw cross-boss sums.

**Players tab**: static Python view + a JS panel (`renderPlayersTab()`). `[CHANGED 2026-09-29]` the panel also renders without a filter:
a **Who pulls first** matrix (columns Player | Total | boss tabs in tab order with short heads such as `Nek'zali H` via `shortBossHeads()`, full title in the
th `title` / `aria-label` (optional 3rd `tbl()` head element), N / H / M legend in the footnote; sticky Player column and tight padding via `table.pull-matrix`, Unknown row,
one row per **participant** of the counted pulls (players who never pulled show dashes / 0, after the pullers; caption "P of N players started X of Y boss pulls"),
limit 15; `pullerMatrix()` / `pullerMatrixHeads()`), under the static view when
unfiltered and under the filtered tables when Nights / Raid night / Player filters are active; directly below it (same filter predicate)
the **All pulls** table (`allPullsHtml()` / pure `allPullRows()`): every pull of every boss tab and difficulty, one row each, columns
Boss (gotab button) | Night | Pull | Started | Result | Duration | Deaths | Pulled by | Ended in, chronological by payload `a`, limit 25.
`[ADDED 2026-10-02]` **Phase 1 Players tab.** Static part: a **Team** strip without names (flask + food %, non-tank avoidable hits/min alive,
first deaths with no defensive, raid interrupts per pull, each vs the previous night) with "pick your name in the toolbar", then **Roster**
sorted by name (public) or first-death rate (named). Named builds only (`--callouts named`, never posted to Discord): `<h2 id='raid_lead'>Raid lead</h2>`
(`dash/rollups.py`): R1 who needs help with what, R2 prep misses, R3 avoidable trend + top abilities, R5 first deaths without a defensive,
R7 interrupts per pull, R8 tanks side by side, R9 gear readiness. Unfiltered JS panel adds "Show my card" (stored name). With a Player
filter the JS panel renders the **player card** (`renderPlayerCard()` → pure `playerCardHtml()`): headline + Good/Watch/Note counts,
"One thing to work on" (`article.insight` + `h3`), items (public: ≤ 3 Watch via `capItems`, counts after the cap; named: uncapped + rank),
KPI tiles with deltas vs earlier same-type nights + sparklines (≥ 4 nights), per-boss rows, consistency small multiples (≥ 4 pulls),
role section (DPS bullet; healer HPS/overheal; tank AM uptime / mitigated share / co-tank DTPS), deaths box row (+ recap, wipe-cutoff wording),
preparation glyph rows (pre-pot "under-reported"), gear; then Who pulls first and All pulls. Severity is computed in Python only
(`analysis/severity.py`); JS orders, caps and formats. Copy-link button (`.copy-link`). `[CAVEAT]` not yet checked in a real browser.

**Accessibility**: `[ADDED 2026-09-23]` tablist roles, real buttons for pull boxes/progress boxes/gotab links, focus rings, sortable
headers are `<button>`s with `aria-sort` on the `th`, visible captions (`[CHANGED 2026-09-24]`, were sr-only), skip link, lightened class/parse
colours on the card surface, 12 px minimum (`--fs-micro`), 44 px tab buttons, `prefers-reduced-motion`, responsive
toolbar/grids at ≤700 px, horizontally scrolling `.scroller` table wrappers, status never carried by colour alone (HP bands with swatch legend,
prep glyphs + sr-only word, visible "review" tag).
`[CAVEAT]` Plotly's `cleanData` throws on keys present with value `undefined` (e.g. `marker: undefined`) — only set keys when defined.

## 8. Avoidable-damage config (`avoidable.json`)

Keys: boss name → list; `"*"` → every boss (Falling); `_ignore`; `_uncertain` (free-form checklist ignored by the tool); `_changelog`.
Names matched case/punctuation-insensitively. `[DECISION]` removed as raid-wide after data: Soulcoil Rite, Cremation, Caustic Explosion,
Caustic Surge, Plague Froth, Congealing Bolt, Toxic Droplets, Unstable Miasma, Clinging Murk, Noxious Blast, Blink Nova, Mighty Thud,
Venomous Surge, Raging Crosswinds, Venom Rupture, Fangs of the Coiled Altar, Toxic Fumes; Stone Breaker removed as tank mechanic.
**Kept although raid-wide:** Putrid Membrane, Unchecked Rage (fail-triggered). `[CAVEAT]` Only Ula'tek was researched from guides;
the "review" tags (formerly ⚠) in the ability tables are the review tool. Rattler Slam (Ula'tek) is currently flagged too — review.

## 8b. Tank-mitigation and gear-check config `[ADDED 2026-10-02]`

- `config/tank_mitigation.json` (+ `.example.json`): `{"<Spec>": {"am": [{id, name}], "major": [{id, name}]}}` keyed by spec token, shared
  tokens as `"Protection Paladin"` / `"Protection Warrior"`; `am` = active-mitigation buffs for the AM-at-hit share (`am`/`amw`), `major` is
  validated but unused until Phase 3. `[CAVEAT]` only Vengeance ids are verified (Demon Spikes 203819 etc.); the others are TWW-era guesses —
  the build warns `tank_mitigation.json: <spec> ids never seen in any <spec> tank's buffs ...`; compare with `data/tank_buffs_seen.json`.
  Unknown tank spec → `am` null + one console note.
- `config/gear_checks.json` (+ `.example.json`): `enchantable` / `socket_slots` = `"auto"` (a slot is required when **more than** `majority`
  (0.5) of the roster's non-empty items in it are enchanted / socketed) or explicit slot lists; `skip_slots` [3, 17]; `low_slot_gap` 15
  (item ilvl ≤ own mean − 15 → "N ilvl below your average"); `slot_names` (Blizzard inventory order). Missing/invalid file → built-in defaults.

## 9. Mythic+ (`mplus.py`)

Raider.IO public API; only current + previous week → `mplus_history.json` is a merged snapshot log, auto-refreshed by the build when
older than `MPLUS_MAX_AGE_HOURS`. `--roster-from-raid START END [--min-pulls N] [--nights main]` builds `roster.txt` and resolves
combat-log realm names to slugs via WCL's server list. `[CAVEAT]` Only an in-game addon gives true run counts.

## 10. Conventions

- Python 3.12+ (user runs 3.14). HTML by string concatenation with `esc()`; `table(headers, rows_html, extra_class='', caption='', limit=None)`
  → `.scroller` + visible `<caption>` + `<th><button aria-label='Sort by …'>`, with `limit` a `data-limit` + "Show all N" button;
  `kpis(items, extra_class='', raw=False)`; `player_cell(name, cls, role='', spec='')`; `fig_html(fig, height=380, div_id=None, fallback=None)`;
  `empty_state(what, why, action='')`; `section_note(text_html)`; `hp_band(pct, kill=False)`; `gotab()` for in-page tab links (buttons, not anchors).
- JS: one IIFE in `dash/static/dash.js`; `chart(traces, layout, height, title, fallback)` returns a `figure.chart` and queues the Plotly draw for
  `drawCharts()` (pure `shouldSkipChart` decides the fallback sentence; `chartLayout` adds axis `automargin`; `narrowLegend` puts legends
  below the plot at ≤ 700 px, also for the Python-rendered charts at `dashReady`); `tbl(heads, rows, extra, caption, limit)`, `kpisHtml(items, extra)`,
  `playerCell`, `emptyHtml`, `hpBand`, `prepCell` mirror the Python helpers; state `G` (global filters) and
  `PD[tab] = {data, sel:Set, player, dirty, rendered}`. Pure helpers live in two marker blocks the tests evaluate in quickjs:
  `// --- table helpers (quickjs-testable) ---` … `// --- end table helpers ---` and
  `// --- pure chart helpers (quickjs-testable) ---` … `// --- end pure chart helpers ---`, and `[ADDED 2026-10-02]`
  `// --- card components (quickjs-testable) ---` … `// --- end card components ---` (sparkline, bulletBar, boxRow, smallMultiples,
  deltaText, uptimeBar, plus the card's pure helpers pickNight/capItems/oneThing/fillAdvice/perBossRows/consistencySeries/playerCardHtml;
  depends on `escH` from the table helpers). `playerHash` / `parsePlayerHash` / `kpisHtml` live in the table-helpers block.
- No hex colours in Python or JS: read TOKENS / TOK. New tables go through table()/tbl(); new KPI strips through kpis()/kpisHtml(); new charts
  through chart()/fig_html() so they get the figure frame.
- Never leave keys `undefined` in Plotly objects. Syntax-check with `venv/bin/python -c "import quickjs; quickjs.Context().eval('(function(){' + open('dash/static/dash.js').read() + '})')"`.
- Any new report-specific query goes through `cq()` / `cached_query()` or per-fight `get_entry`/`put_entry`; report list and report
  meta are never cached. Batch per-fight requests with aliases; keep per-fight cache keys so live logs refresh only new fights.
- Console output is the user's audit trail. Record every change in a tagged `docs/CHANGES_<date>.md` and keep this file current.
- File locations come from `path.py` (`CONFIG_DIR`, `DATA_DIR`, `DASHBOARD_DIR`); never build paths from `__file__` in other modules.
- Tests must stay offline: regenerate fixtures with `python tests/make_fixtures.py` when a query text changes (`--slim` shrinks them).

## 11. Open items / next steps

- `[ADDED 2026-09-25]` **Next phase proposed:** per-player combat analysis (DPS / healer / tank / RL views) — design + roadmap in `docs/plans/2026-09-25-player-analysis-design.md`,
  research in `docs/research/2026-09-25-player-analysis/`. `[DECISION 2026-10-01]` Q1–Q10 (design §9) proceed under the design's own recommendations unless
  the owner says otherwise. `[CHANGED 2026-10-01]` **Phase 0 done** (P0.1–P0.8; FIGHTS+PHASES merge skipped, optional P0.9 `--prune-cache` skipped) — see
  `docs/CHANGES_2026-10-01.md`. (`pointsResetIn` wait margin done.) `[CHANGED 2026-10-02]` **Phase 1 done** (player card, team strip, named
  Raid-lead rollups, Home prep insight; `ish`/`kc`/`deaths[].ds`/block counts dropped, D5 deferred to Phase 3) — see `docs/CHANGES_2026-10-02.md`
  and `docs/plans/2026-10-01-player-analysis-phase1-plan.md`. `[TODO]` **Phase 2** (casts pipeline + spell oracle) is next.
  `[TODO]` Owner follow-ups: check `config/tank_mitigation.json` ids against `data/tank_buffs_seen.json` after the first real build; review
  `config/gear_checks.json` defaults; answer the T6 questions (Watch cut order, first death with a defensive = Good, per-night tiles vs
  selection-wide blocks); sanity-check the wipe-cutoff constants on real wipes; open the card in a real browser (headless screenshots were
  not possible in the agent sandbox).
- `[CHANGED 2026-09-24]` Folder reorganisation (`config/`, `data/`, `dashboards/`, `docs/`, `path.py`) - see `docs/CHANGES_2026-09-24.md`.
  `[TODO]` optional second step: move the root modules into a `wcl/` package (touches 12 imports, `python -m wcl.mplus`, systemd, test bootstrap).
- `[ADDED 2026-09-24]` Whole-project review `docs/reviews/REVIEW_2026-09-24.md` (32 verified bugs/risks, ranked) and phased `docs/ROADMAP_2026-09-24.md`;
  visual redesign plan `docs/plans/2026-09-24-dashboard-redesign.md` (replicates `dashboards/serenity-dashboard-rebuilt.html`, local only). Start with review §0.
  `[ADDED 2026-09-24]` The plan now carries a **UX audit of the real build** (21 findings → task amendments + Tasks 10-12: density defaults,
  status without colour, mobile pass). `[CAVEAT]` headless-Firefox deep-link screenshots need the delayed-`load` copy described in that section.
- `[CHANGED 2026-09-24]` Redesign Tasks 1-12 done and visually verified (Task 9 in `docs/CHANGES_2026-09-24.md`).
  `[TODO]` Replace the remaining Plotly charts with inline SVG if the CDN dependency should go (the example has none); box plots and heatmaps are the hard ones.
  `[TODO]` The example shows an ilvl column in Damage done; the payload has no item level yet (CombatantInfo carries it).
  `[TODO]` Roadmap 4.4 per-tab inflation replaces the skeleton with real content sooner.
  `[TODO]` Boss-tab height: the 2-pull fixture boss (`#tab2`) is ~13,150 px tall at 1440 px, far over the plan's ≤ 3,500 px target. Measured causes, largest
  first (final review): the Damage taken Abilities rows (3-4-line "Who gets hit" cells), the near-empty Deaths charts (now sentences), the six
  role tables (Damage done + Healing done × DPS/Tanks/Healers) with two-line player cells, the uncapped Preparation / Interrupts tables (now 15),
  and the SVG progression chart scaled ~1.5× (viewBox capped at 920 in a ~1,500 px host). `div.plot` min-height is not a cause. Next step:
  collapse the low-value role tables behind `details.table-view`.

- `[FIXED 2026-09-23]` Everything in `docs/reviews/REVIEW_2026-09-23b.md` except `logging`/`mypy`/browser test - see `docs/CHANGES_2026-09-23.md` Follow-up 3.
  Bundle is **v3**, casts entry **v2** (+ `buffs` for externals), consumable casts **v1** (filtered events); `NIGHT_PLAYERS` for bench;
  `_exclude_bosses` in nights.json (Nymrissa Wavecaller). `[CAVEAT]` `"*"` in avoidable.json is special-cased in `load_avoidable()`.
- `[TODO]` Check the Preparation table once against a pull you know: pre-pot window is 5 s before → 1.5 s after the pull
  (`PREPOT_BEFORE_MS/AFTER_MS`), rune patterns are guesses for this expansion (`consumables.json`).
  `[CAVEAT 2026-09-29]` **WCL returns no events before a fight's startTime** (verified with and without `fightIDs`), so the 5 s before
  the pull are never seen: the "prepot" flag only catches potions pressed in the first 1.5 s and under-reports. Same reason
  `PULL_TOLERANCE_MS` only guards synthetic input. `[TODO]` decide whether pre-pots need another source (e.g. the potion buff at fight start).
- `[CAVEAT 2026-09-29]` **Who pulled on self-starting bosses**: Ula'tek starts on its own (proximity / RP); in 3 of 19 prog pulls the first
  friendly attack came 372-453 ms after fight start, so the credited player is the first attacker, not a true puller. Offsets ≥ ~300 ms
  are the tell (the pull table shows the offset). Body pulls are credited the same way. See `docs/CHANGES_2026-09-29.md`.

- `[TODO]` User: add `DIFFICULTIES=normal,heroic,mythic` to `.env` (Claude Code cannot edit it); revoke the leaked token (see CHANGES).
- `[TODO]` Visual check of the deeper boss-tab sections in a real (non-headless) browser, including sticky tab / section nav while scrolling;
  `[CHANGED 2026-09-24]` the 14,000 px Task 9 capture was inspected section by section (Phases, Preparation and Interrupts look right).
- `[TODO]` Consumable / defensive name patterns are educated defaults for this expansion — check the Preparation table against a
  known-good pull and adjust `consumables.json` (rune name!) / `defensives.json`.
- `[TODO]` Optional: weekly cron/systemd build + Discord post; hosting (GitHub/Cloudflare Pages) would remove the size ceiling entirely.
- `[TODO]` Optional: per-player defensive lookups for *every* death in the single-pull view (currently first death only).
- `[CAVEAT]` `tests/fixtures/` is 6.85 MB (budget 7.5 MB, `SIZE_BUDGET`); if this bothers you, pick an even smaller report for `make_fixtures.py`.

## 12. Timeline of notable changes (compressed)

1. `[ADDED]` WCL API client, report listing, single-boss pull merge.
2. `[ADDED]` Multi-boss tabbed HTML dashboard with caching; MRA-style filters; pull grid; phases; Players tab.
3. `[ADDED]` Damage taken from raw events; avoidable.json workflow. `[FIXED]` tick vs hit → instances.
4. `[ADDED]` Death recaps + main contributor; first-death focus.
5. `[ADDED]` WCL-style Summary / Damage done / Healing done.
6. `[ADDED]` Mythic+ tracker + weekly requirement; roster generation with realm-slug fix.
7. `[ADDED]` Who-gets-hit pattern detection + ⚠ review; role inference; spec-split rows.
8. `[ADDED]` Click-to-inspect pulls → client-side filtered rendering; global toolbar; grey-out of empty bosses.
9. `[ADDED]` Breaks (idle-based, trash-aware), Raid tab, Home tab with anonymous callouts.
10. `[ADDED]` Main/open night classification, `nights.json`, `--reports`, `--add-report`, `BOSS_ORDER`.
11. `[FIXED]` Cache re-download loop (endTime change detection); guardian sources.
12. `[CHANGED] 2026-09-23` Full rework from `docs/reviews/REVIEW_2026-09-23.md`: token leak + .gitignore fixed; `dash/` package; browser is the only
    boss-tab renderer; gzip payload (8.3 MB → 1.7 MB); realm-safe identities; fight %; fight bundles + per-fight cache + thread pool;
    time-to-phase, preparation, interrupts/dispels, defensives before first death; accessibility pass; pytest suite with offline fixtures.
    Details: `docs/CHANGES_2026-09-23.md`.
13. `[CHANGED] 2026-09-24` Folder reorganisation: `config/` (edited), `data/` (generated), `dashboards/` (output), `docs/`; `path.py`.
    Details: `docs/CHANGES_2026-09-24.md`.
14. `[CHANGED] 2026-09-24` Dashboard redesign (Tasks 1-12 of `docs/plans/2026-09-24-dashboard-redesign.md`) — details: `docs/CHANGES_2026-09-24.md`.
15. `[ADDED] 2026-09-25` Delegation policy (§0) and the per-player combat analysis design proposal
    (`docs/plans/2026-09-25-player-analysis-design.md`, not yet approved). Details: `docs/CHANGES_2026-09-25.md`.
16. `[ADDED] 2026-09-29` Who pulled: `pulled_by` per pull (collector), payload `pb`, boss-tab "Who pulled" table + "Pulled by" column,
    Players-tab "Who pulls first" matrix. Plan `docs/plans/2026-09-29-who-pulled.md`; details: `docs/CHANGES_2026-09-29.md`.
17. `[CHANGED] 2026-10-01` Per-player analysis Phase 0 (hygiene): buffs targetID fix, `nextPageTimestamp` pagination, rate-limit logging + exit 3,
    `specs.py`, fixture recorder + re-record, live probe, `wipe_called_s`. Details: `docs/CHANGES_2026-10-01.md`.
18. `[ADDED] 2026-10-02` Per-player analysis Phase 1: `analysis/` package (PM_COLS metrics, wipe cutoff, tank mitigation digest, gear checks,
    severity engine), payload `pm/pmcols/wc/av` + Players block, player card + deep links, team strip, named Raid-lead rollups, Home prep insight.
    Details: `docs/CHANGES_2026-10-02.md`.
