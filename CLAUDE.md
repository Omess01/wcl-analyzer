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
build_dashboard.py   CLI only: args -> collect() -> dash.page.build_html() -> dashboards/; writes data/abilities_seen.json
mplus.py             Raider.IO Mythic+ tracker -> data/mplus_history.json; roster tools (--roster-from-raid [--nights main])
post_discord.py      Post a built dashboard to a Discord webhook
wcl_client.py        OAuth + GraphQL POST to WCL v2; timeout, retries/backoff (429/5xx/net/rate-limit), thread-safe   [stable]
cache.py             On-disk JSON cache in data/cache/: cached_query (sha1(query+vars)) + get_entry/put_entry; lock; atomic writes
fetch_reports.py     Guild report list for a date range (NEVER cached)
collect_data.py      All data collection -> {(boss, difficulty): [pull, ...]}  (see §5)
path.py              Folder layout constants (import from here, never compute paths from __file__ elsewhere)
dash/common.py       esc/fmt, avoidable config, roles/specs, table()/kpis()/player_cell()/empty_state()/gotab(), fig_html, breaks, all_pulls, player_stats
dash/payload.py      pull_grid() (server-rendered click surface) + pull_payload() (compact per-pull JSON, gzip+base64)
dash/home.py         Home tab: progress strip, insights(), last night
dash/raid.py         Raid tab: night report, attendance, parse table, kill-time trend
dash/players.py      Players tab (static part)
dash/mplus_tab.py    Mythic+ tab + update_mplus_if_stale()
dash/page.py         Page assembly: header, toolbar, ARIA tablist, panels, inlines static/dash.css + static/dash.js
dash/static/dash.js  THE renderer for boss tabs (all sections) + global filters + Players-tab dynamic view
dash/static/dash.css Styles (dark theme, WoW class colours lightened for contrast, focus rings, reduced motion, responsive)
dash/static/tokens.css  Design tokens (the ONLY place colours/type/spacing live; Python load_tokens(), JS TOK read it)
config/              Files YOU edit (tracked, except nights.json and roster.txt which are per-guild and ignored)
  avoidable.json       Per-boss avoidable abilities + _ignore (+ _uncertain checklist)
  consumables.json / defensives.json   optional name-pattern overrides (defaults built in; *.example.json provided)
  nights.json          night-type overrides, _include / _ignore report codes
  roster.txt           Characters tracked for M+ (Name,realm-slug)
data/                Files the TOOL writes (whole folder ignored)
  cache/               WCL responses + report_meta.json (endTime seen per report)
  abilities_seen.json  Written every build: abilities per boss with hit counts + sources
  mplus_history.json   Written by mplus.py; read by the dashboard
dashboards/          Built HTML (ignored: contains player names); default output of build_dashboard.py
docs/                CHANGES_<date>.md, ROADMAP_*.md, reviews/REVIEW_*.md, plans/
tests/               pytest suite; tests/make_fixtures.py records one report into tests/fixtures/ (offline replay)
systemd/             user service + timer + build-and-post script
legacy/merge_pulls.py  superseded early CLI
```

## 3. Setup / run

```
python -m venv venv && source venv/bin/activate.fish     # fish shell!
pip install -r requirements.txt                          # requests, python-dotenv, plotly (+ pytest, quickjs for tests)
python build_dashboard.py 2026-08-23 2026-09-21          # -> dashboards/dashboard_<start>_to_<end>.html
python -m pytest -q                                      # 94 tests, offline
```

CLI (`build_dashboard.py`): `--difficulty ...` (default `DIFFICULTIES` in .env, else heroic mythic) · `--zone` · `--boss` · `--player` ·
`--progression-only` · `--nights {all,main,open}` · `--reports CODE...` · `--add-report CODE...` · `--callouts {anonymous,named,off}` ·
`--refresh` · `--mplus` / `--no-mplus` · `--uncompressed` (plain JSON payload) · `-o FILE`.

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
consumables {label: {flask, food, vantus, rune, prepot}}, consumable_use {label: {combat_potion, healing_potion, mana_potion, healthstone}}, has_extras`.

- `deaths[i]`: `player, actor_id, class, seconds_into_fight, ability (killing blow), recap, window_damage, top_contributor, biggest_hit,
  one_shot, hits_in_window`; first death additionally `casts [[seconds_before, name]], defensives [...], has_cast_data`.
- `damage_taken[i]`: `player, class, ability, hits (instances), ticks, events, amount, hit_amount, tick_amount, unmitigated, avoided,
  uptime_seconds, times, sources`.

Console prints per report: night type, `[new report] / [unchanged - cached] / [changed since last run - re-downloading new fights]`,
`-> 0 pulls used ...` hints, and `WCL API calls this run: N (of which M re-downloaded recent reports) - cache hits: K`.

## 6. Cache (`cache.py`)

- `cached_query(query, vars, refresh)` keyed by sha1(query text + vars) → changing a query's text re-fetches automatically.
- `get_entry(key, refresh)` / `put_entry(key, data)` for explicit keys (bundles, casts). `count_api_call()` for batched requests.
- Invalidation by **endTime change** per report, at **fight granularity** (§5). `report_meta.json` stores the endTime seen.
- Thread-safe (lock around stats; temp-file + `os.replace` writes).

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
ir,ds,cons {name:[flags in cats order]},hx`. Boss level: `boss,diff,avoidable,ignored,break_minutes,busy,src {ability:[top sources]},cats`.

**Tab order**: Home · bosses Normal→Heroic→Mythic then WCL zone order (`BOSS_ORDER` pins) · Raid (per night type) · Players · Mythic+.
Tabs are an ARIA tablist with arrow-key navigation; deep links `#tabN` and `#tabN:section` (`prog,sum,dd,hd,deaths,dt,prep,util`).

**Toolbar**: Nights (when both types exist) · Raid night · Player · clear · wide (persisted in localStorage). Filters apply to every
boss tab (badges, greyed-out bosses, jump to first boss with pulls) and to the Players tab. Esc clears. `[CHANGED 2026-09-24]` not sticky;
a `<details class='filters'>` (open on desktop, closed under 700 px) whose summary counts the active filters.

**Home**: per night type: KPI tiles; progress cards (buttons); **Progression by first kills** (`progression_timeline()`: step chart
of bosses killed at least once per raid night, one trace per difficulty + table with first-kill night / pulls / nights per boss in zone
order); "Worth a look" callouts: progression trend (median of 3 best
pulls per night), pulls reaching the deepest phase, top wipe-starter, share of first deaths with no defensive cast, wipe-starter
outlier, avoidable outlier, flask/food missing, idle share of last night, regulars missing, avoidable-list review flags (with
difficulty), M+ met/total. `[DECISION]` default `anonymous`; `named` = private RL build; `off`.

**Boss tab sections (JS, in order)**: Pulls grid (boss HP band, fight % line when it differs >1 pt, phase, breaks) · KPI tiles ·
Progression (inline-SVG HP chart + "Show the N pulls as a table", breaks table, **Phases**: wipes by phase + **time-to-phase** chart/table, per-night table) · Summary ·
Damage done / Healing done (role groups, parse, active DPS, median/best, box plot) · Deaths (first-death KPI tiles incl. "no defensive
cast", charts, histogram, players table, first-death table with **Defensives cast** + recap incl. casts; single pull = all deaths) ·
Damage taken (KPI tiles, charts, heatmap, avoidable timing histogram, players table with Role + Hide tanks, abilities table with Cast by /
Who gets hit / "review" tag) · **Preparation** (flask/food/rune/prepot per player) · **Interrupts & dispels**. Player filter adds the
focus block. All tables sortable (header buttons). Charts are drawn one by one; failures show in the `#jsError` banner at the top.
Section headings are `h2` / `h3` (no `h4`/`h5` in `dash.js`); Plotly titles are `<h3>` above the plot, never in the canvas; no modebar.

**Raid tab**: night report (idle/trash aware), attendance matrix (main nights), average parse across kills, farm kill times.
`[DECISION]` no raw cross-boss sums.

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
  `// --- pure chart helpers (quickjs-testable) ---` … `// --- end pure chart helpers ---`.
- No hex colours in Python or JS: read TOKENS / TOK. New tables go through table()/tbl(); new KPI strips through kpis()/kpisHtml(); new charts
  through chart()/fig_html() so they get the figure frame.
- Never leave keys `undefined` in Plotly objects. Syntax-check with `venv/bin/python -c "import quickjs; quickjs.Context().eval('(function(){' + open('dash/static/dash.js').read() + '})')"`.
- Any new report-specific query goes through `cq()` / `cached_query()` or per-fight `get_entry`/`put_entry`; report list and report
  meta are never cached. Batch per-fight requests with aliases; keep per-fight cache keys so live logs refresh only new fights.
- Console output is the user's audit trail. Record every change in a tagged `docs/CHANGES_<date>.md` and keep this file current.
- File locations come from `path.py` (`CONFIG_DIR`, `DATA_DIR`, `DASHBOARD_DIR`); never build paths from `__file__` in other modules.
- Tests must stay offline: regenerate fixtures with `python tests/make_fixtures.py` when a query text changes (`--slim` shrinks them).

## 11. Open items / next steps

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

- `[TODO]` User: add `DIFFICULTIES=normal,heroic,mythic` to `.env` (Claude Code cannot edit it); revoke the leaked token (see CHANGES).
- `[TODO]` Visual check of the deeper boss-tab sections in a real (non-headless) browser, including sticky tab / section nav while scrolling;
  `[CHANGED 2026-09-24]` the 14,000 px Task 9 capture was inspected section by section (Phases, Preparation and Interrupts look right).
- `[TODO]` Consumable / defensive name patterns are educated defaults for this expansion — check the Preparation table against a
  known-good pull and adjust `consumables.json` (rune name!) / `defensives.json`.
- `[TODO]` Optional: weekly cron/systemd build + Discord post; hosting (GitHub/Cloudflare Pages) would remove the size ceiling entirely.
- `[TODO]` Optional: per-player defensive lookups for *every* death in the single-pull view (currently first death only).
- `[CAVEAT]` `tests/fixtures/` is ~4 MB; if this bothers you, pick an even smaller report for `make_fixtures.py`.

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
