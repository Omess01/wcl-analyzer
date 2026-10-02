# Change log

## [FIX] 2026-10-02 — Review follow-ups: deterministic Players block, co-tank name hidden on the public card

**Files:** analysis/severity.py, dash/static/dash.js, docs/CHANGES_2026-10-02.md
**Why:** the Phase 1 review found (1) the `sev` block's label order came from set iteration, so the `data_tabPlayers` payload changed between runs with `PYTHONHASHSEED` (T3's "shifts by a few bytes"), and (2) the public tank card named the co-tank next to their DTPS — design §7.4 says nothing per-name renders until a name is chosen, and T2's wording is "co-tank 118 k".
**What:**
- `severity._pull_records`: `for lab in sorted(labels)` — `recs` / `aggs` / `sev` key order is now label-sorted within each pull; verified identical sha1 of `players_data()` under `PYTHONHASHSEED=1/2/3` (was three different hashes).
- `playerCardHtml` tank section: the co-tank column shows the co-tank's name only when `named`; public builds print `co-tank`. The DTPS numbers are unchanged (design T2 is public).
- `venv/bin/python -m pytest -q` → 288 passed; quickjs syntax check OK; ad-hoc check: Ixavior's public card no longer contains "Airohdh", the named card does.
**Notes:**
- No new tests were added (CLAUDE.md §3 keeps 288); `test_card_renders_for_every_player` only asserts the "Co-tank (DTPS)" header.
- Still unverified without a browser: `renderPlayerCard` DOM wiring, the death-box / copy-link / show-my-card handlers, `history.replaceState` on `file://`, and the card at 390 px.

## [DOCS] 2026-10-02 — Phase 1 verification and docs

**Files:** docs/CHANGES_2026-10-02.md (new), docs/plans/2026-10-01-player-analysis-phase1-plan.md (new), CLAUDE.md, docs/plans/2026-09-25-player-analysis-design.md
**Why:** Phase 1 T9 (design P1.V + P1.D): verify the Phase 1 build and record it in the per-day change doc, CLAUDE.md and the design roadmap.
**What:**
- Verification: `pytest -q` → 288 passed; quickjs syntax check on dash.js OK; offline fixture builds (0 API calls) anonymous/named, compressed + `--uncompressed`: 313,833 / 335,964 / 368,587 / 392,180 B; boss-tab payload 21,840 B base64 = 5,460 B/pull (was 4,659, +801); Players block 3,724 B (anon) / 4,080 B (named) base64; privacy spot-check passed (no roster name in `static_tabPlayers` outside the roster table, no Raid lead, Home names nobody, `cfg.named` false; named build has `raid_lead` and `cfg.named` true).
- Headless-Firefox screenshots NOT taken: attempt 1 exited 1 with no PNG (crash reporter / telemetry noise), attempt 2 denied by the permission classifier. `dashboards/verify_p1*.html` deleted.
- `docs/CHANGES_2026-10-02.md`: T1–T8 sections from the entries below, Verification with the size table and monthly projection (+0.2–0.3 MB/month vs +0.7 MB budget), Open / next.
- Plan copied verbatim with a one-line header.
- CLAUDE.md: §2 (analysis/ modules, dash/rollups.py, configs, data/tank_buffs_seen.json, plan path), §3 (288 tests, new test files), §5 (wipe_cutoff_s heuristic, player_events, gear, event aura keys, overheal, parse bracket keys), §7 (payload pm/pmcols/wc/av, 6-element dd/hd, tank recap AM flag, data_tabPlayers, cfg.named, `#tabPlayers?player=`, team strip, card, Raid lead, Home prep insight), new §8b (tank_mitigation.json, gear_checks.json), §10 card-components marker block, §11 Phase 1 done / Phase 2 next / owner follow-ups, §12 entry 18.
- Design doc §8 Phase 1 table: task cells P1.1–P1.9, P1.D `[DONE 2026-10-02]` with deviations, P1.V `[PARTLY DONE]`.
**Notes:**
- Browser verification of the card is still open (owner or a session with Firefox permission). Deltas/sparklines/consistency plots are untested end-to-end (fixture has one night).
- `data/tank_buffs_seen.json` currently holds fixture-derived counts (Vengeance only, written 2026-10-02 00:26); the first real build overwrites it.
- The exit criterion "≤ baseline + 0.8 KB/pull" is met only as 819 B or without the per-tab `pmcols` constant (+724 B); T3's split guard documents this.
- CLAUDE.md §3 had said 146 tests (stale since the Phase 0 review follow-ups made it 152); now 288.

## [FEAT] 2026-10-02 — Phase 1 T6: per-player card on the Players tab

**Files:** dash/static/dash.js, dash/static/dash.css, tests/test_players_tab.py
**Why:** Phase 1 T6 / design §7.3: choosing a player in the toolbar now shows a personal card built from the Phase 1 payload (per-pull `pm`, `wc`, death `av`, the tank recap AM flag, and the Players block's `sev`/`gear`/`advice`). It replaces the old per-boss table.
**What:**
- Loading block: `const PLAYERS = { data, error }` inflates `data_tabPlayers` in its own try/catch (also plain JSON). If decoding fails, only the card shows an empty state; Who pulls first and All pulls still render. With no block, `data` stays null and the card renders from `pm` alone, without severity items or gear.
- Card components block (quickjs-testable), new pure helpers: `pickNight(nights, G, have?)`, `capItems(items, named)` (public: the first 3 Watch in engine order, every Good, every Note; named: no cap), `oneThing(items)` (first Watch in engine order), `fillAdvice(tpl, item)` (`{value} {baseline} {n} {pulls}`, null -> `n/a`), `perBossRows(lists, name, cols)`, `consistencySeries(lists, name, cols, metric, history, label, fmt)`, `playerCardHtml(name, lists, players, G, opts)`. Private helpers: `cardRecs`, `cardNight` (mirrors `severity.aggregate_night`), `bestGood`, `CARD_METRIC` / `CARD_BKIND` / `CARD_PREP`, and small formatters.
- `kpisHtml` moved into the table-helpers block (one line, unchanged) so the card block can be evaluated in quickjs.
- New `renderPlayerCard(name, copy)` sits right before `renderPlayersTab`. It passes every pull of every boss tab plus `{named: CFG.named, recap: recapHtml, roleOf, support}`. The card applies the night / nights-type filter itself, so earlier nights stay available for the deltas. The filtered `G.player` branch is now: the card, then Who pulls first, then All pulls. The header's `.copy-link.linklike` button is still written in `renderPlayersTab`, so T7's source test keeps passing.
- Card blocks, in order (all inside `div.card.player-card`, headings h2/h3 only):
  - sr-only `role=status` line.
  - `h2.panel-title`: name, spec, class, role, nights, pulls, scope.
  - `p.card-counts`: Good, Watch and Note counts (via `statusText`), "this night", and the copy link.
  - `article.insight.warn|good` with an `h3`, "One thing to work on: ...".
  - `ul.card-items` (Watch and Good), plus `details.card-notes` for the Notes. The named build adds the rank.
  - `h3` "<night>: key numbers": `kpisHtml(.., 'card-kpis')` with 7-8 tiles (deaths/pull, first death, avoidable/min alive when the boss has a list, active %, median active DPS or HPS, prep misses, kills parse/bracket, ilvl). Each tile has a `deltaText` against the median of your earlier same-type nights, and a sparkline over up to 12 nights.
  - Per-boss `tbl()` with gotab buttons.
  - Consistency: `smallMultiples` per boss with 4 or more pulls of at least 60 s. The band is the IQR of earlier nights.
  - Role section:
    - DPS: `bulletBar` (you, DPS median of non-support others, your earlier nights), plus the same-spec line only when `named`.
    - Healer: HPS and HPS parse/bracket tiles, an overheal bullet (healer median, or a reference of 30 with no other healer), and an H9 damage-done note.
    - Tank: `uptimeBar` for `am` / `amw`, mitigated share, and a co-tank paired DTPS table per pull.
  - Deaths: `boxRow` in `.card-deaths`. Watch = avoidable, or a first death with no defensive and no external. Good = first death with a defensive. Clicking a box opens `details.card-deathlog` (table + `recapHtml`). The Contract-B wording shows whenever any selected pull has `wc`, and deaths after `wc` are left out and counted.
  - Preparation: `ul.prep-rows`, one glyph row per category with "missed on N of M". Vantus is skipped and pre-pot is tagged "under-reported". Below it, the potion and healthstone use counts.
  - Gear: from `players.gear`.
- `recapHtml`: when recap rows have a 6th element (dying tank) it adds a Mitigation column: "AM up" / "AM down" / "unknown". This also applies on the boss tabs.
- One delegated click handler: `.card-deaths .box[data-death]` opens the death table and that death's recap, and focuses its summary.
- CSS: `.player-card > h3`, `.card-counts`, `.insight h3` (same as `.insight h4`), `.card-items`, `.card-notes`, `.card-line`, `.prep-rows` / `.prep-glyphs` / `.prep-count`, `.card-gear`. The ≤ 700 px prep-row stacking is inside T5's last `@media` block, which `test_card_css_classes_present` checks via `rindex`.
- Tests (+8 in tests/test_players_tab.py):
  - The card renders for every fixture roster label from a real `build_html` payload: blocks present, no `<h4`/`undefined`/`NaN`/`null`, Contract-B wording, an uptime bar plus a co-tank table for Ixavior and Airohdh, an overheal bullet plus HPS for Gigaspinning and Maxiumus, and no same-spec line in the public build.
  - The named build adds the same-spec line and the rank.
  - Night and type filters, the no-pulls empty state, and the null Players block.
  - Unit tests for `pickNight`, `capItems` / `oneThing`, `fillAdvice` over every `ADVICE` template, and `perBossRows` / `consistencySeries`.
  - Source checks: placement before `renderPlayersTab`, `CFG.named`, the own try/catch, and card -> matrix -> All pulls order.
**Notes:**
- What the fixture cannot exercise (one open night, 1-2 pulls per boss): own-history deltas, sparklines (need ≥ 4 nights), the consistency plots and the IQR band (need ≥ 4 pulls per boss), and a non-null `wc` combined with deaths before it on a kill. These are covered by the synthetic `perBossRows` / `consistencySeries` tests only; deltas and sparklines are not tested end-to-end.
- The toolbar has no boss filter (only night, nights type and player), so the card always covers every boss tab with pulls. The boss tabs' own pull selection does not affect it.
- "This night" is `pickNight`: the toolbar night, or the latest night of the type filter (or of any type) that the player was in. KPI tiles and severity items are for that night. The per-boss rows, consistency, deaths and preparation cover the whole filtered selection. Deltas compare with the player's earlier nights of the same type, ignoring the night filter, so a single-night filter still shows a trend.
- `oneThing` takes the first Watch item in the engine's order (level, then tier, then score). The design text says "highest score, tier breaks ties", but the engine sorts tier first and T6 follows the engine.
- Headline counts are the counts after the cap, so the public build does not reveal hidden Watch items. A sentence says when more than 3 Watch items were cut.
- The co-tank and role medians on the bullets are computed in JS from `pm` over the selection. They are not the `sev` baselines, which are per night with a ≥ 3-other rule. The healer overheal bullet falls back to a reference of 30 when there is no other healer.
- Not verified in a real browser: the headless-Firefox screenshot command was permission-denied in this session. Verified with pytest, the quickjs syntax check, and quickjs rendering of `playerCardHtml` for every fixture label. The death-box click handler and `renderPlayerCard`'s DOM wiring have not been run.

## [FEAT] 2026-10-02 — Phase 1 T8: Players team strip, alphabetical roster, named Raid-lead rollups, Home prep insight

**Files:** dash/rollups.py (new), dash/players.py, dash/home.py, dash/page.py, tests/test_rollups.py (new), tests/test_dashboard.py (one edit: `rollups.py` added to the no-hex list)
**Why:** Phase 1 T8 (design P1.8 + P1.9): the public Players tab gets team numbers with no names and a name-sorted roster; the private `--callouts named` build gets the raid-lead rollups; Home gets an anonymous preparation callout.
**What:**
- `dash/rollups.py`: `prep_rates(pulls)` (`ff` = flask and food share over player-pulls where both were checked, same rule as `common.night_stats` prep; `rune` share separately; `n`), `nights_in_order(pulls)`, `night_series(bosses, pm_by_key)` (per night: `prep`, `avm` = non-tank Σavh / (Σalv/60) from the pm vectors, role per pull via `player_metrics.role_of`; `nodef` = share of first deaths with cast data and no defensive/external; `irpp` = raid Σir / pulls with interrupt data), and `rollups_named(bosses, ordered, players_block, pm_by_key=None, avoidable_cfg=None) -> str`: `<h2 id='raid_lead'>Raid lead</h2>` + h3 sections R1 "Who needs help with what" (one row per raider, latest night in their `sev`, up to 3 Watch items by score with value + baseline + baseline kind, else their first item; rows sorted by (level, -score, name); `data-level`/`data-score` on each `tr`), R2 "Preparation misses" (flask/food/rune misses per player from `consumables`), R3 "Avoidable damage" (per-night non-tank hits/min alive + top 5 abilities with top-5 "who", cutoff applied), R5 "First deaths without a defensive" (per night count/share + names), R7 "Interrupts" (per pull per player from pm `ir`), R8 "Tanks side by side" (rows night × {am, amw, mit, dtps}, one column per tank; am/amw/mit = mean of per-pull values, dtps = Σdtk/Σalv k/s), R9 "Gear readiness" (ilvl min/median/max tiles + players with gaps and their gap strings from `players_block.gear`). All tables via `table()`, status = `tag` class + word.
- `dash/players.py`: `players_tab(bosses, avoidable_cfg, mode="anonymous", players_block=None, pm_by_key=None, ordered=None)`; new `team_strip()` (`<h2>Team</h2>`, section note with "pick your name in the toolbar to see your card", `kpis(..., "team-strip", raw=True)`: Night, Flask + food at pull start (+ rune line), Avoidable hits / min alive (non-tanks), First deaths with no defensive, Raid interrupts per pull; each with `home._delta` vs the previous night); `<h2>Roster</h2>` before the table; `player_table_lowpart(..., by_first_death=True)` — public builds sort `(name.lower(), -pulls)`, named keeps the first-death-rate sort; the Raid-lead section is appended only when `mode == "named"`.
- `dash/home.py`: `insights()` adds one "Preparation: N% flask and food" insight (all modes, rates only: latest night's flask+food share over player-pulls, rune share, previous night's share with better/worse/about the same; good ≥ 95 %, warn < 80 %, else info; jump button to `tabPlayers`); `home_section` labels the `tabPlayers` jump "Open Players".
- `dash/page.py`: `players_block = players_data(...)` computed once (reusing `pm_by_key`), encoded with `payload._encode` for `data_tabPlayers` (identical output to `players_payload`) and passed with `mode`, `pm_by_key`, `ordered` into `players_tab`.
- `tests/test_rollups.py` (11 tests): public/off builds name no participant in `#static_tabPlayers` outside the roster table (regex of `test_home_anonymous_names_nobody`, roster table cut out by its caption) and have no Raid lead; strip tiles present; roster alphabetical; named build has all 7 h3 sections, named roster first-death sort, R1 one row per raider sorted by (level, -score), R8 columns Ixavior + Airohdh with the 4 metrics, R9 ilvl 312/318 + gaps; Home prep insight in anonymous and named + Home still names nobody; Players headings start at h1, never skip, max h3; named HTML < 1.5 MB; strip "vs previous night" on a synthetic two-night copy; `prep_rates` synthetic.
**Notes:**
- Privacy: the strip, its note, the Roster heading/intro and Home's prep text contain only rates and the night label; names render only inside roster rows (public) and, in named builds, in the Raid-lead section. Verified by the tests above for `anonymous` and `off`.
- Strip and Home compare with the chronologically previous night of any type (same as `last_night_panel`), not the previous night of the same type.
- R3 top abilities and the avoidable rate exclude tanks (same population as the plan's avoidable/min formula). R8's "night" mean of am/amw/mit is a plain mean of per-pull values, not severity's median-over-≥60 s rule.
- Fixture: every player-pull has `rune: False`, so R1 is dominated by the `prep` Watch item (4 of 4 pulls) and R2 lists everyone; real builds with a working rune pattern will look different (see CLAUDE.md §11 rune TODO).
- `.team-strip` has no CSS (T6 owns dash.css); it renders as the standard `.kpis` grid.

## [FEAT] 2026-10-02 — Phase 1 T3: payload pm/pmcols/wc/av, ilvl in dd/hd, Players-tab data block, cfg.named

**Files:** dash/payload.py, dash/page.py, tests/test_dashboard.py
**Why:** Phase 1 T3: ship every Phase-1 datum (metric vectors, wipe cutoff, death flags, ilvl, severity/gear block) to the browser so T6 (card) and T8 (rollups) only render.
**What:**
- `_death_payload(d, first, avoid=None, tank_spec=None)`: new `av` (1 when the killing blow or >= 50 % of `window_damage`, summed over the full recap, is from `avoidable - ignored`, else 0; always 0 when the boss has no avoidable list). Dying tank (role from `pull_specs`): every recap row gets a 6th element `1/0/null` = an `am_ids_for(spec, class)` id is in that event's `buffs`; `null` when the event has no `buffs` or the spec has no tank_mitigation.json entry. Non-tank recap rows stay 5 long.
- `pull_payload(..., compress=True, pm=None)`: per pull `"pm": {label: trim(vec)}` (every participant; `pm=None` computes the vectors in place via `player_metrics` with `gap` null) and `"wc": wipe_cutoff_s` (last keys of the pull: smallest gzip output); `dd`/`hd` rows gain `ilvl` as 6th element (int, `null` when the table has 0); `parses` as stored (T1 bracket keys kept); boss level `"pmcols": PM_COLS`. `kc` never existed in this payload, nothing to drop. Shared `_encode(obj, compress)`.
- New `gear_rules_for(bosses, gear_cfg=None)`, `all_metrics(bosses, avoidable_cfg, gear_cfg=None) -> {(boss, diff): [{label: untrimmed vec}]}` (per-pull `gap` = `gear_report(...)["n_gaps"]` against `roster_rules(latest_gear(all pulls))`), `players_data(...)` (dict) and `players_payload(bosses, ordered, avoidable_cfg, pm_by_key, named, compress=True, gear_cfg=None) -> (mime, text)` = Contract E.
- `dash/page.py::build_html`: `mode` derived like `home.py`; `pm_by_key = all_metrics(...)` once; `boss_tab(..., pm=)`; `<script type='application/gzip+base64' id='data_tabPlayers'>` (plain JSON under `--uncompressed`) right before `static_tabPlayers` inside the Players panel; `cfg` = `{**specs.role_sets(), "named": mode == "named"}`.
- Tests (+4, suite 265 -> 269): `test_payload_phase1_keys`, `test_death_av_flag_and_tank_recap_flag`, `test_players_payload_block` (keys, roster = participants, sev for every player on the fixture night, gear ilvl for every damage-table player, size guards), `test_players_payload_named_and_uncompressed`; helpers `_players_block`, `_script_text`, `_pre_phase1`; `test_role_config_script_feeds_dash_js` expects `named: False`.
**Notes:**
- Sizes (fixture, 4 pulls, 3 boss tabs): pre-Phase-1 (computed in-process by stripping pm/pmcols/wc/av/recap flag/ilvl/parse bracket keys) 18,636 B base64 = 4,659 B/pull (matches the plan); after 21,840 B = 5,460 B/pull (+801); without the per-tab `pmcols` constant 21,532 B = 5,383 B/pull (+724). Breakdown (avoidable cfg `{}`): pm ~1,850 B, T1 parses keys ~620, pmcols ~316 (105/tab), ilvl ~144, recap flag ~24, wc ~20, av ~16. Players block ~3.7 KB base64 (varies by a few bytes run to run: severity's label order comes from a set).
- Guard deviation: the per-pull guard is `(after without pmcols - before)/pulls <= 800` plus `(after - before)/pulls <= 850`, because `pmcols` is a per-boss-tab constant that the 4-pull fixture charges as ~80 B/pull (real builds: ~3-10 B/pull). Literal `after <= before + 800` misses by 1 B.
- Projection: pm/ilvl/parses scale with players (fixture ~15.5/pull, real 23.4), so real builds grow ~+1.0-1.1 KB base64/pull (above the plan's 0.65 estimate) -> +150-220 KB per 140-200 pulls, plus the Players block (~230 B per player-night -> ~60-80 KB/month) = ~+0.22-0.3 MB/month, under the +0.7 MB budget.
- T6/T8: per-pull keys are `pm` (`{label: [..<=23 ints/null]}`, columns = boss `pmcols` = Players `cols`), `wc` (float or null; present on every pull), `deaths[].av` (0/1), tank recap row `[ago, ability, source, amount, self, am]`, `dd`/`hd` `[name, class, spec, total, active_s, ilvl]`. Players block: `roster` sorted case-insensitively (spec = most common token, role from it, `support` 0/1), `sev`/`nights`/`advice` exactly as `severity.compute(..., cols=PM_COLS, named=named)` returns (10th `rank` element only in named builds), `gear[label] = {ilvl, gaps, ilvl_min, ilvl_max}` from each player's latest gear (ilvl falls back to the latest pm `ilvl` when they have no gear rows; min/max = raid-wide range, same on every entry). `all_metrics` is computed once in `build_html` as `pm_by_key`; T8 can reuse it and `players_data(...)` for `sev`/`gear` rather than recomputing.
- `tests/_tmp_probe_test.py` was already gone (not in `git status`); nothing deleted.

## [FEAT] 2026-10-01 — Phase 1 T1: analysis core (PM_COLS, wipe cutoff, event digest) + collector hooks

**Files:** analysis/__init__.py (new), analysis/wipe.py (new), analysis/mitigation.py (new), analysis/player_metrics.py (new), collect_data.py, build_dashboard.py, config/tank_mitigation.json (new), config/tank_mitigation.example.json (new), tests/test_mitigation.py (new), tests/test_player_metrics.py (new), tests/test_collect_offline.py
**Why:** Phase 1 of the per-player design needs one source of truth for the per-player-per-pull metric vector, a usable post-wipe cutoff (WCL's `wipeCalledTime` is never set), and a few extra reads of data the v3 bundles / event pages already cache (no new API calls, no cache-key change, no version bump).
**What:**
- `analysis/wipe.py`: `wipe_cutoff_s(kill, duration_s, death_times, wipe_called_s) -> float | None` with `WIPE_CASCADE_GAP_S = 10.0`, `WIPE_CASCADE_MIN_DEATHS = 3`, `WIPE_TAIL_S = 20.0` (Contract B; stdlib only). Fixture fight 8 -> 92.5, fights 2/7/9 -> None.
- `analysis/mitigation.py`: `load_tank_mitigation()` (cached parse of `config/tank_mitigation.json` -> `{label: {"am": set, "major": set, "names": {id: name}}}`), `spec_label(cls, token)` ("Protection Paladin" only for shared tokens), `mitigation_entry()`, `am_ids_for(spec_token, cls=None) -> set[int] | None` (without a class a shared token returns the union), `parse_buffs()`, `digest_events(events, participants, spec_ids, cutoff) -> {label: {dtk, hits, hits_buffs, dodge_parry_miss[, am_up, amw_num, amw_den, mit_num, mit_den]}}` (Contract C: one entry per participant, tank keys only for tanks; `spec_ids` values may be specIDs or spec tokens), module-level `TANK_BUFFS_SEEN = {spec label: Counter}`; constants `CONNECTED_HIT_TYPES = {1, 2, 4, 5}`, `DODGE_PARRY_MISS_TYPES = {0, 7, 8}`, `AM_BUFFS_MISSING_MAX = 0.30`. Imports only stdlib + `specs` + `path`.
- `analysis/player_metrics.py`: `PM_COLS` (23, Contract A: `act dps hps dth fd alv avh avm dtk dtps prep pot hs ir ds ilvl rp bp oh mit am amw gap`), `COL`, `trim(vec)`, `role_of()`, `player_metrics(pull, avoidable, ignored, gear_gaps=None) -> {label: untrimmed vector}`. Role via `dash.common.pull_specs` + `specs.role_of_token` (Contract D). `hps`/`oh` healers only, `mit/am/amw` tanks only, the 30 % aura-data rule, cutoff applied to `dth/avh/avm/dtk/dtps/mit/am/amw` (`seconds <= cutoff`), not to `fd/alv`.
- `collect_data.py`: event dict gains `buffs` (str | None), `mitigated` (int | None), `hit_type` (int | None), `blocked` (int | None); table rows gain `overheal` (healing rows; 0 on damage rows); new `_gear_rows()` + `gear_from_bundle(bundle, actors, lab, participants) -> {label: [[slot, ilvl, enchant_id_or_0, n_gems, item_id], ...]}` (damage row gear by `slot`, then healing row, then cinfo gear by index); `get_parses` stores `bdps`/`bhps` (`bracketPercent`) and `spec`; `collect()` clears `TANK_BUFFS_SEEN`, hoists `duration_s` / `wipe_called_s`, builds `digest_specs` (specIDs + table spec-token fallback) and adds pull keys `wipe_cutoff_s`, `player_events`, `gear`.
- `build_dashboard.py`: `write_tank_buffs_seen()` -> `data/tank_buffs_seen.json` (`{spec label: {buff id: hits}}`, top 25 per spec; returns None and writes nothing when no tank hit carried aura data), called from `main()` after `write_abilities_seen`; `tank_mitigation_warnings()` (unknown spec keys; configured am/major ids never seen on that spec's tanks in the build, silent for specs without a tank) appended by `validate_config()`.
- `config/tank_mitigation.json` + `.example.json`: Vengeance, Protection Paladin, Protection Warrior, Blood, Guardian, Brewmaster with the plan's default id list.
- Tests (152 -> 265 with the other wave-1 tasks; T1 adds 58): `test_mitigation.py` (cutoff cases incl. fixture list, `am_ids_for`, digest filters / weights / cutoff / unknown spec), `test_player_metrics.py` (Contract A list, trim, null rules, healer/tank/no-row/cutoff/kill/death-at-0 cases), `test_collect_offline.py` (+8: new pull keys, fight 8 cutoff 92.5, both tanks `am` 50-90 with `hits_buffs/hits >= 0.95`, overheal, bracket parses, 18 gear rows per damage-table player, full vectors for every participant, `tank_buffs_seen` writer + warnings).
**Notes:**
- **Payload deviation (intended by the plan, flagged here):** `dash/payload.py` emits `parses` as stored, so the new `bdps`/`bhps`/`spec` keys reach the browser now: fixture payload 17,660 -> 18,288 B base64 total (4,415 -> 4,572 B per pull, +157 B/pull, kills only). Contract C pins the bracket keys inside `parses[label]` and T3 is written against that ("parses emitted as stored"), so the alternative (a separate pull key) would have broken T3. Everything else (`wipe_cutoff_s`, `player_events`, `gear`, `overheal`, event aura keys) is pull-dict only.
- Spell ids: only the four Vengeance ids are verified (all seen on the fixture tanks: Demon Spikes 203819 x1767 hits, Fiery Brand 207771, Metamorphosis 187827, Soul Barrier 263648). The other five specs' ids are TWW-era guesses; the build prints `tank_mitigation.json: <spec> ids never seen in any <spec> tank's buffs in this range: ...` once a real build has such a tank.
- Pinned deviations accepted by the plan: `dtk` and `am` do not exclude `_ignore` / avoidable abilities (the digest runs in `collect_data`, which does not load `avoidable.json`). Friendly pets as damage sources count as enemy hits (same as `aggregate_damage`).
- A tank whose spec has no config entry gets `mit_*` but no `am_*` keys in the digest (so `am`/`amw` are null) and one console note per spec label per process.
- `digest_events` runs in the sequential per-fight loop of `collect()`, so `TANK_BUFFS_SEEN` needs no lock. `_noted_missing` and the config cache in `analysis/mitigation.py` are process-wide.
- The fixture cannot exercise: `wipe_called_s` set, blocked hits (hitType 4/5 / `blocked`), non-Vengeance tank specs, cinfo-only gear fallback (every fixture damage-table player has table gear), the 30 % rule (fixture tanks are at >= 96.9 % aura coverage). All of those are covered synthetically.

## [FEAT] 2026-10-01 — Phase 1 T4: severity engine (analysis/severity.py)

**Files:** analysis/severity.py (new), tests/test_severity.py (new)
**Why:** Design §7.3 pins one Good/Watch/Note scorer in Python so the browser never re-scores; Phase 1 T4 delivers it as a pure module T3 (`dash/payload.py`) can call with `PM_COLS`.
**What:**
- `compute(bosses, pm_by_key, specs_by_key, cols, named=False) -> {"sev": {label: {night: [items]}}, "advice": ADVICE, "nights": [[night, type, startMs], ...]}`; item = `[metric, value, baseline, bkind, level, score, tpl, affected, pulls]` (+ `rank` "3 of 12" as 10th element only when `named=True`).
- Helpers `aggregate_night(recs, role)`, `baseline(metric, own_history, peers, role)`, `tolerance(metric, baseline)`, `score(value, baseline, tol, affected, pulls)`; constants `RULES` (tolerance/kind/direction/tier), `NOTE_ONLY`, `BANDS`, `SHORT_EXCLUDED`, `ADVICE`.
- Night values, baseline cascade (own ≥ 2 earlier nights of the same type → role median ≥ 3 others present ≥ 25 %, tanks → co-tank → band → null), tolerances/directions/tiers, Watch rule `affected ≥ max(3, ceil(0.25·pulls))`, `prepot` Note-only, < 60 s exclusion for act/dps_ratio/hps/oh/am, support specs excluded from role medians and from `dps_ratio`, ordering (level watch<good<note, tier, score desc, metric).
- 27 synthetic tests; full suite 217 passed.
**Notes:**
- Imports: stdlib + `specs` only. Pull-dict fields read: `night` (fallback: derived from `absolute_start_ms` in the collector's `%a %Y-%m-%d[ open]` format), `night_type` (default main), `absolute_start_ms` (fallback `start_ms`), `duration_seconds`, `kill`, `participants`, `deaths[0].player/has_cast_data/defensives/externals` (for `nodef`). Labels = pm keys ∪ participants; a missing vector is all-null.
- Pinned beyond the plan: healers get an `hps` item (median active HPS, ±8 % rel, higher, tier 6) instead of `dps_ratio`; tanks get neither. `prep`/`prepot` have a fixed baseline 0 with `bkind="band"`, and `prep` is the one band-baselined metric that may be Watch. Worse-beyond-tolerance but below the affected floor → Note. For Good items `affected` counts pulls *better* than the baseline beyond tolerance (so "best Good" has a score); for `prep`/`prepot` it is the missed pulls and for `nodef` the first deaths without defensive/external (these fill `{n}`). Relative tolerance with a 0 baseline uses the factor as an absolute floor (avm 0.25 hits/min). Note-only metrics (`ilvl`, `gap` latest; `rp`/`bp` mean over kills; `ir`/`ds` per pull, only when > 0; `prepot`) get own/role/co-tank baselines when available, never a band, score 0, tier 9. Values/baselines/scores rounded to 2 decimals. Co-tank baseline = median of the other tank(s) present ≥ 25 %, no minimum count. Role for a player-night = the role played on most pulls; role metrics use only pulls in that role.
- `ADVICE` placeholders: `{value}`, `{baseline}`, `{n}` (= `affected`), `{pulls}`. JS must apply the public cap (≤ 3 Watch, ≥ 1 Good); the engine emits everything.

## [FEAT] 2026-10-01 — Phase 1 T7: Players deep links (#tabPlayers?player=), click-your-name, Show my card, copy link

**Files:** dash/static/dash.js, tests/test_players_tab.py (new)
**Why:** design §7.2 (minus the datalist): a raider opens the Discord link with their name pre-selected, and clicking a name anywhere sets the Player filter.
**What:**
- Table-helpers block (quickjs-testable): `playerHash(name) -> '#tabPlayers?player=<enc>'` (`'#tabPlayers'` for empty; encodeURIComponent plus `' ( ) ! * ~` -> %XX, so `Nek'zali` -> `Nek%27zali`; `Name-Realm` unchanged) and `parsePlayerHash(hash) -> label | null` (with or without `#`, any `&` position, `+` = space, malformed `%` keeps raw text, empty/whitespace -> null).
- Deep-link block: hash split on the first `?` before the `:` split (`#tab3:deaths` unchanged); `parsePlayerHash(rawHash)` pre-selects the player if it is a `gPlayer` option and calls `applyGlobal()` before `activateTab(wanted)` (one render). Tab-button click writes `playerHash(G.player)` for the Players tab when a player is set, else `#tabN`.
- `syncPlayerHash(strip)`: on the Players tab writes `playerHash(G.player)` (`#tabPlayers` when none); elsewhere leaves the hash alone; `strip` (clearAll) drops a `?player=` left on another tab. `applyGlobal` stores `wcl_dash_player` (only when non-empty; clearAll keeps the stored name) and calls it.
- `hasPlayerOption(name)`, `pickPlayer(name)`; one delegated click handler for `tr[data-player] .player, [data-player-pick]` -> `gPlayer.value = name; applyGlobal();` (names not in the toolbar list are ignored).
- Unfiltered Players panel starts with `<p class='my-card'><button id='showMyCard' data-player-pick='NAME'>Show my card (NAME)</button></p>` when the stored name is an option.
- Delegated `.copy-link` handler (`data-player` or current filter): `navigator.clipboard.writeText(location.href.split('#')[0] + playerHash(name))`, button reads "Link copied" for 2 s; fallback inserts/updates `<code class='copy-url'>` after the button with the URL as textContent and selects it. The current per-player Players view has a `Copy link` `.copy-link.linklike` button under the title.
- tests/test_players_tab.py: 16 tests (quickjs round-trips for apostrophes, Name-Realm, spaces, unicode, `&=?#`; parse variants and nulls; source checks: `?` split before `:`, applyGlobal before activateTab, single guarded scroll, sync in applyGlobal/clearAll, click/showMyCard/copy-link handlers).
**Notes:**
- T6: keep the `.copy-link` button (with `data-player`) in the card header and put any name-pick controls on `[data-player-pick]`; the `#showMyCard` line belongs to the **unfiltered** branch and must stay above `whoPullsFirstHtml` (test checks `myCard + whoPullsFirstHtml`). The card goes in the filtered `G.player` branch.
- No CSS added (`.my-card`, `.copy-url` unstyled; `.copy-link` uses the existing `.linklike`). Name spans are not keyboard-focusable; the toolbar select is the keyboard path.
- The mobile `tabSelect` change still does not write the hash (it never did).

## [FEAT] 2026-10-01 — Phase 1 T5: card components in dash.js (sparkline, bullet, box row, small multiples, delta)

**Files:** dash/static/dash.js, dash/static/dash.css, tests/test_dashboard.py
**Why:** T6 (player card renderer) needs pure, quickjs-testable HTML/SVG builders so it only composes; no user-visible change until T6.
**What:**
- New marker block `// --- card components (quickjs-testable) ---` ... `// --- end card components ---` directly after `// --- end pure chart helpers ---`: `sparkline(values, opts)`, `bulletBar(value, target, own, max, labels)`, `boxRow(items)`, `statusText(level)`, `smallMultiples(series)`, `deltaText(cur, prev, fmt, lowerIsBetter, period)` (same text/classes as `dash/home.py::_delta`), `uptimeBar(share, text)`; private helpers `cardNum/cardR1/cardFmt/cardMedian/cardPct`, `CARD_LEVEL` (good ✓ / watch ! / note •).
- Colours only via `TOK` (SVG) or CSS vars; status = class + glyph + sr-only/visible word.
- CSS: `.card`, `.card .kpis`, `.card .kpi dd .spark`, `.status-good/-watch/-note`, `.bullet*`, `.boxrow .box.lvl-*`, `.multiples`/`.multiple`/`.multiples-skip`, `.uptime*`; <= 700 px: card KPI tiles 2-up, multiples min 120 px.
- Tests: `_card_components(quickjs)` evaluator + 8 tests (skip rules, titles, tick text, glyph/sr word, `_delta` parity, CSS present, block placement and no hex).
**Notes:** The block depends on `escH` from the table-helpers block; `_card_components` evaluates TOK stub + table helpers + card block in one eval. T6 should add its pure helpers (`pickNight`, `capItems`, ...) inside this same block. `deltaText` passes `fmt` output through unescaped (like `_delta`). `smallMultiples` skip sentences render inside the `.multiples` grid.

## [FEAT] 2026-10-01 — Phase 1 T2: gear checks (analysis/gear.py, config/gear_checks.json)

**Files:** analysis/gear.py (new), config/gear_checks.json (new), config/gear_checks.example.json (new), tests/test_gear.py (new), analysis/__init__.py (created only if T1 had not yet)
**Why:** Phase 1 player cards (block 9) and R9 need ilvl + gear gaps; Midnight's enchantable/socketed slots differ from the design's list, so required slots come from the roster majority.
**What:**
- `slot_name(slot, cfg=None)`, `roster_rules(gear_by_label, cfg=None) -> {"enchant_slots": set, "gem_slots": set}`, `gear_report(rows, rules, cfg=None) -> {"ilvl": int|None, "gaps": [str], "n_gaps": int}`, `latest_gear(pulls_by_label) -> {label: rows}`, `load_gear_checks(file=None)` (defaults when missing/invalid; `slot_names` merged per key; `_`-keys dropped), `DEFAULTS`, `GEAR_CHECKS_FILE`.
- Rows = Contract C `[slot, item_ilvl, enchant_id_or_0, n_gems, item_id]`; rows with item_id 0, ilvl 0 or slot in `skip_slots` [3, 17] are ignored everywhere (mean, majority, gaps).
- Gap strings: `"head: no enchant"`, `"ring 2: empty socket"`, `"wrist 19 ilvl below your average"` (item ilvl <= mean - `low_slot_gap`; N = round(mean - ilvl)); order = slot order, per slot enchant -> socket -> low.
- 13 tests in tests/test_gear.py (suite 152 -> 165 at time of run, includes other agents' new tests).
**Notes:**
- Majority rule is **strict** (`enchanted / non-empty > majority`), not the plan's `>=`: on the real fixture off hand is 4 enchanted of 8 non-empty (exactly 0.5), and the plan requires 16 not to be picked. Fixture result: enchant {0,2,4,6,7,10,11,15}, gem {1,10,11} (head has gems on 4/16).
- `latest_gear` accepts `{label: [pull]}` or a plain list of pulls; "most recent" = max `absolute_start_ms`, ties/missing by list order.
- `gear_report` returns `ilvl: None` (not an int) when a player has no usable rows.

## [FIX] 2026-10-01 — Review follow-ups: cinfo follow-up degrade, exit-3 covers build_html, pager guard, reset wait elapsed time

**Files:** collect_data.py, build_dashboard.py, wcl_client.py, tests/test_units.py, tests/test_wcl_client.py, CLAUDE.md, docs/CHANGES_2026-10-01.md, .claude/CHANGES.md
**Why:** the Phase 0 code review found four robustness gaps (a failing cinfo page-2 crashed the build, exit 3 missed `build_html`, the pager only stopped on a repeating cursor, the reset wait ignored elapsed time) plus doc nits.
**What:**
- `_fetch_bundle_batch`: `_follow_pages` for `cinfo_<fid>` wrapped in `try/except WCLError` -> `_warn_once("_cinfo_page_warning_shown", "  (combatant info page 2+ unavailable - using page 1 only: ...)")`, keeps page 1 data, skips `put_entry` for that fight (re-fetched next run). `WCLRateLimited` still propagates.
- `build_dashboard.main()`: exit-3 message factored into a local `_stop_rate_limited(exc)`; `build_html(...)` now also in a `try/except WCLRateLimited`.
- `_follow_pages`: loop requires `cursor > last` (strictly advancing); new module constant `MAX_PAGES = 50` -> warn once (`_pages_cap_warning_shown`, "stopped following pages ... after N follow-ups") and stop.
- `wcl_client`: `_record_rate` stores `"at": time.monotonic()` in `last_rate`; `_exhausted()` returns `max(0, pointsResetIn - elapsed)`, which is compared against `WCL_RATE_WAIT_MAX` and reported in `WCLRateLimited.reset_in`; sleep = that + new `RATE_WAIT_MARGIN = 5.0`. Docstring date fixed to 2026-10-01.
- Tests (146 -> 152): `test_bundle_cinfo_follow_up_failure_degrades_and_is_not_cached`, `test_follow_pages_stops_on_non_advancing_cursor`, `test_follow_pages_stops_on_backwards_cursor`, `test_follow_pages_page_cap` (units); `test_429_exhausted_elapsed_time_brings_reset_within_wait_max`, `test_build_dashboard_exits_3_when_build_html_rate_limited`; `wcl` fixture patches `time.monotonic` with a hand-advanced clock; the reset-wait test now expects `[600 - 100 + 5]`.
- Docs: x-ratelimit request-count limit reworded to "observed 300 (probe) and 800 (build); window length unknown" (CLAUDE.md §5, docs CHANGES, the rate-limit entry below); `wipe_called_s` caveat strengthened (0 of 201 boss wipes across 18 cached reports have `wipeCalledTime`); two `[TODO]`s in docs/CHANGES_2026-10-01.md Open / next (post-wipe exclusion fallback; Phase 2 page-boundary duplicate check); CLAUDE.md pagination bullet mentions advance rule + `MAX_PAGES`; "Review follow-ups" section in docs CHANGES.
**Notes:**
- `last_rate` now has an extra `"at"` key; `rate_summary()` and `build_dashboard`'s fallback still print the raw `pointsResetIn` of the last response (not elapsed-adjusted).
- The page-cap warning is once per process, not per fight. The cinfo degrade warning is also once per process.
- Tests patch `time.monotonic` on the global `time` module (via `wcl_client.time`), same as the existing `time.sleep` patch; monkeypatch restores it.

## [DOCS] 2026-10-01 — Phase 0 documentation pass (CHANGES_2026-10-01, CLAUDE.md, design Phase 0 table)

**Files:** docs/CHANGES_2026-10-01.md (new), CLAUDE.md, docs/plans/2026-09-25-player-analysis-design.md
**Why:** P0.D of the per-player design: record today's Phase 0 hygiene work in the project's tagged per-day change doc and keep the handoff file current.
**What:**
- `docs/CHANGES_2026-10-01.md`: one section per Phase 0 task (fetcher hygiene, rate limits, spec table, fixture recorder, live probe, wipeCalledTime), tests (146), Open / next list.
- `CLAUDE.md`: §2 layout (`specs.py`, `tools/wcl_probe.py`, wcl_client note), §3 Setup / run (146 tests, new test files, fixture size/budget, `--clean` re-record command, exit code 3), §4 `WCL_RATE_WAIT_MAX`, §5 pagination / spec table / rate-limit bullets, `spec_ids` + `wipe_called_s` pull keys, new console lines, §6 `rateLimitData` vs cache keys, §11 known-bug caveats replaced by "Phase 0 done, Phase 1 next, Q1–Q10 per design recommendations", fixture-size caveat updated, §12 entry 17.
- Design doc §8 Phase 0 table: P0.1–P0.7 `[DONE]`, P0.8 `[PARTLY DONE]` (merge skipped), P0.9 `[SKIPPED]`; no other sections touched.
**Notes:** The design doc still states the old acceptance criteria (32 spec names, 6.5 MB budget, "Δpoints log", `cache.py` change, wipeCalledTime `null` only when no wipe called); the CHANGES doc records what was actually built.

## [FEAT] 2026-10-01 — wipeCalledTime in FIGHTS_QUERY -> pull["wipe_called_s"]

**Files:** collect_data.py, tests/make_fixtures.py, tests/test_units.py, tests/test_collect_offline.py, tests/fixtures/cache/* (re-recorded), tests/fixtures/report.json
**Why:** the upcoming per-player analysis must be able to exclude deaths and hits after the raid leader called the wipe.
**What:**
- `FIGHTS_QUERY` `fights { ... }` now also selects `wipeCalledTime`.
- Pull dict gains `"wipe_called_s"`: seconds from fight start to WCL's wipe call, rounded to 0.1, or `None` when WCL has no value. Not emitted in `dash/payload.py` (payload delta 0).
- FIGHTS and PHASES queries deliberately stay separate (the live probe showed merging saves only 1 point per report).
- Tests: `test_fights_query_requests_wipe_called_time` (units), `test_every_pull_has_wipe_called_s` (offline: key present, `None` or float >= 0).
- Fixtures re-recorded with `tests/make_fixtures.py --clean` (report 3w1jJ8BZ2m9kMrYG): 16 API calls, 63 (+1 lagged) WCL points, 8.5 s, 28 cache files. 146 tests pass offline.
**Notes:**
- Fixture cache is 6.85 MB. `SIZE_BUDGET` in `tests/make_fixtures.py` was raised from 6.5 to 7.5 MB (docstring updated) instead of dropping data: the `buffs`/`mitigated`/`hitType` event keys (about 0.63/0.38/0.31 MB) are needed by the per-player phases, and the 10 MB Discord limit applies only to the dashboard. The first `--clean` run stopped at the old 6.5 MB budget; `--slim` then reported `6.85 MB (budget 7.5 MB)` and exited 0. The four damage-event pages are about 5.4 MB of the total.
- The first real build after this change fetches `FIGHTS_QUERY` again once for every report (the cache key is sha1 of the query text). That is 1 cheap call (~2 points) per report; bundles, events and casts stay cached.
- In the fixture, fight 8 (Ula'tek, a wipe with 17 deaths) also has `wipeCalledTime: null`, so every pull there has `wipe_called_s = None`. WCL does not always set the field on wipes. Downstream code must treat `None` as "no wipe call known", not as "kill".
- Fixture sanity: 138 `gear` keys in cinfo, about 22k `buffs` and about 25k `hitType` on events. Fixture-only replay makes 0 API calls (conftest `_no_network` would raise).

## [FEAT] 2026-10-01 — Single spec/role table from specID (specs.py)

**Files:** specs.py (new), collect_data.py, dash/common.py, dash/page.py, dash/static/dash.js, tests/test_units.py, tests/test_collect_offline.py, tests/test_dashboard.py
**Why:** Python and JS kept separate literal tank/healer sets that could drift; players missing from the damage/healing tables got no spec; support specs (Augmentation) need to be identifiable for later exclusion from role medians.
**What:**
- `specs.py`: `SPECS = {specID: (class, spec_token, role, simc_token, support)}` with WCL icon tokens (`BeastMastery`, `Havoc`, ...); helpers `spec_of()`, `role_sets()`, `role_of_token()`. 40 ids: the 39 retail specs plus 1480 Demon Hunter `Devourer` (dps), verified from real cache (specID 1480 always pairs with icon `DemonHunter-Devourer`, 566 rows). Augmentation 1473 is `support=True`.
- `collect_data.py`: new `spec_ids_from_cinfo()` -> `{label: specID}` from CombatantInfo (participants only; unknown ids print `unknown specID N for <label> (<class>)` once per id via `_unknown_spec_ids`). New pull key `"spec_ids"`. `player_tables_from_bundle(..., spec_ids=None)` falls back to the specID token when the icon yields no spec.
- `dash/common.py`: `TANK_SPECS` / `HEALER_SPECS` (+ new `SUPPORT_SPECS`) derived from `specs.role_sets()`; `pull_specs()` lets the CombatantInfo specID win, falling back to the tables (healing table still wins for flex healers).
- `dash/page.py`: emits `<script type='application/json' id='cfg'>` with `specs.role_sets()` next to `tab_names`.
- `dash/static/dash.js`: `TANKS` / `HEALERS` / `SUPPORT` built from the `cfg` JSON instead of literals (`SUPPORT` not used yet).
- Tests: fixture specIDs resolve; fixture icon tokens equal the table token for the player's specID; role sets equal the old literals; unknown id -> None; icon-less fallback; warn-once; every pull has `spec_ids` and `pull_specs` covers every participant; `cfg` script present/parseable and dash.js reads it.
**Notes:**
- `spec_ids` is not emitted into the browser payload; no cache/version bump. Payload `specs` strings are unchanged for players that already had one, but players absent from both tables (0.71% of CombatantInfo player-pulls in data/cache) now gain a `specs` entry — that is the intended fix.
- In the real cache every icon-less table row is a `Boss`-type healing entry (not a player), so the `player_tables_from_bundle` fallback recovers 0 rows today; the coverage gain comes from `pull_specs` reading `spec_ids`.
- Bundles without extras have no cinfo -> `spec_ids == {}` and the icon path is the only source, as before.
- `role_of_token()` is safe because shared tokens (Holy, Protection, Restoration, Frost) share a role; a unit test enforces this.

## [DOCS] 2026-10-01 — P0.7 live WCL probe: shapes, point costs, archive status

**Files:** tools/wcl_probe.py (new), docs/research/2026-09-25-player-analysis/06-live-probe.md (new)
**Why:** settle the [unverified] items of research doc 04 with real calls so Phase 2 batch sizes, the FIGHTS+PHASES merge (P0.8) and E9 rest on data.
**What:**
- `tools/wcl_probe.py`: calls `wcl_client.run_query` directly (never `cached_query`, never writes `data/cache`), appends `rateLimitData` itself and reads it from the raw HTTP body (wraps `wcl_client._session.post`; no production code change), redacts player names to P1..Pn and refuses to write if a name leaks, stops on the second HTTP 429.
- `06-live-probe.md`: calls/points table (lag-corrected), rate headers, JSON shapes of table Casts/Buffs/Summary, `includeResources` keys, playerDetails, pagination, whole-fight casts volume, archiveStatus, enemy casts vs Interrupts table, specIDs, hand-written Findings, four decisions.
- Decisions: FIGHTS+PHASES merge meets the >= 50 % rule (PHASES 1 vs FIGHTS 2 points) but saves only 1 point/report; whole-fight casts = 2 pages (10,000 + 757) for a 623 s pull; fixture 3w1jJ8BZ2m9kMrYG not archived; no unknown specID.
**Notes:**
- `pointsSpentThisHour` lags one request (a response shows the total before its own charge); cost is ~1 point per alias/subquery or page, independent of bytes, so batching saves HTTP requests, not points.
- Every response has `x-ratelimit-limit` / `x-ratelimit-remaining` headers (request-count limit observed 300 (probe) and 800 (build); window length unknown); no 429 seen.
- Interrupts table lists only spells interrupted at least once; spellsBegun/spellsCompleted equal enemy begincast/cast counts for those. Never-kicked interruptible spells are missing from the E9 denominator.
- Re-running the script overwrites 06-live-probe.md including the hand-written Findings section. The probe was run twice (~106 points, 41 queries): run 1 lost the counter because a concurrent wcl_client.py change pops `rateLimitData` from the returned data.

## [FEAT] 2026-10-01 — WCL rate-limit visibility and clean stop (exit 3)

**Files:** wcl_client.py, collect_data.py, build_dashboard.py, tests/test_wcl_client.py
**Why:** Long builds died after minutes of blind backoff when the hourly WCL point budget ran out, with no way to see how much budget a run was using.
**What:**
- `wcl_client.run_query` appends ` rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }` inside the outermost braces **at send time only** (`_with_rate_fields`); the caller's `query` string is untouched, so `cache._cache_path` (sha1 of caller text + variables) and every existing cache key are unchanged. Skipped when the query already contains `rateLimitData`.
- `rateLimitData` is popped from `payload["data"]` before returning, so cached files and fixtures keep their shape. It is stored in the lock-guarded module dict `wcl_client.last_rate` and one line is printed per request: `  [wcl] <opname> Δ<pts> pts, <spent>/<limit> this hour, reset in <s> s` (opname from `query X(`; Δ is spent-now minus previous spent, `?` on the first request).
- `rate_summary()` → `WCL points this run: X of Y per hour (...); resets in Z s`; printed by `collect()` right after `cache.summary()`.
- Wait-or-stop on HTTP 429 or a GraphQL "rate limit" error: the existing short backoff (`_retry_delay` / 60 s) runs first; then, only if `last_rate` says spent ≥ 95 % of the limit: sleep `pointsResetIn` and retry once when it is ≤ `WCL_RATE_WAIT_MAX` (default 900 s), otherwise raise `WCLRateLimited`. A second rate-limit after the long wait also raises. Below 95 % behaviour is exactly as before.
- New `WCLRateLimited(RuntimeError)` — deliberately **not** a `WCLError`, so the degrade-silently fetchers (`_fetch_bundle_batch`, `get_consumable_casts`, `get_pull_events`, `get_first_death_casts`, all `except WCLError`) let it through. Carries `.reset_in/.spent/.limit`.
- `collect_data.py`: `except WCLRateLimited: raise` added before the bare `except Exception` in `zone_encounter_order`, `fetch_reports_by_code`, `get_phases`, `get_parses`; `print(rate_summary())` after `cache.summary()`. No other changes; per-report `save_meta` inside the loop is untouched so finished reports stay cached and the exception propagates through the existing `finally` (pool shutdown).
- Retry-After / X-RateLimit-* headers of a 429 are printed once per process (or a note that none were sent).
- `build_dashboard.main()`: `collect()` wrapped in `try/except WCLRateLimited` → prints `stopped: hourly points exhausted, resets in N s; finished fights are cached, re-run later` and `sys.exit(3)`. `--refresh` now first issues one minimal `query RateLimit { rateLimitData {...} }` (bypasses cache; the only extra API call) and refuses with exit 3 when spent > 80 % of the limit (`RATE_REFRESH_MAX_FRACTION`).
- `tests/test_wcl_client.py` (11 tests, offline: fake session/token/sleep): send-time injection with unchanged caller text and popped data, cache-key invariance, per-request line + summary, 429 < 95 % → short backoff only, 429 ≥ 95 % → short backoff then one sleep of `pointsResetIn`, reset too far → `WCLRateLimited` with no further POST, GraphQL rate-limit message path, `WCLRateLimited` not a `WCLError`, 429 headers logged once, `build_dashboard.main` exit 3 for both the collect path and the `--refresh` refusal.
**Notes:**
- `WCL_RATE_WAIT_MAX` is a new optional `.env` key (seconds, default 900). Claude cannot edit `.env`; add it by hand if you want a different ceiling. `.env.example` was not touched for the same reason.
- `cache.py` and `cache.stats` keys are unchanged; the offline fixture suite still makes 0 network calls (`conftest._no_network`).
- The long wait sleeps exactly `pointsResetIn` with no safety margin; if WCL rounds that value down, the retry can land a second early and the run then stops with `WCLRateLimited("still rate limited after waiting")` instead of continuing. Follow-up candidate: add a few seconds of margin.
- Δ for the very first request of a run is unknown (`?`) and that request's cost is not included in "points this run". With `WCL_PARALLEL` > 1 responses can arrive out of order, so individual Δ values are best-effort (can be negative); the run total uses a running max and detects an hour rollover via `pointsResetIn` jumping up.
- The `rateLimitData` field is a top-level `Query` field in WCL v2, so it is only valid directly inside the outermost braces, which is where it is inserted; all queries in the repo (including the dynamically built bundle/casts/events queries) end with `}`.

**Follow-up (same day, after the live probe in `docs/research/2026-09-25-player-analysis/06-live-probe.md`):**
- `pointsSpentThisHour` lags one request (a response reports the total *before* its own charge). The per-request line is now `  [wcl] <op> <spent>/<limit> pts this hour, reset in <s> s` and appends `; <previous op> cost N pts` only when both that previous request and the current one ran with nothing else in flight (`_post` tracks in-flight count and a start counter; `sole` flag). Under `WCL_PARALLEL=4` the bundle fetches overlap, so they show the running total only; the sequential stages (ReportMeta, ReportFights, ReportPhases, ...) get an exact, correctly attributed cost. The old `Δ`/`?` output is gone.
- `rate_summary()` now says the total excludes the last request's cost ("+ the last request's cost, which WCL reports one response late"). No extra closing `RATE_QUERY` is issued by default.
- Every 200 response's `x-ratelimit-limit` / `x-ratelimit-remaining` headers (observed 300 / N; a request-count window separate from points, window length unknown) are stored in `last_rate["req_limit"]` / `last_rate["req_remaining"]`, shown in `rate_summary()` as `requests: R of L remaining (x-ratelimit window)`, and a one-time warning is printed when remaining < 10 % of the limit (`REQ_BUDGET_WARN_FRACTION`). 429 header logging unchanged (`Retry-After` still never observed).
- Tests: `test_per_request_line_attributes_lagged_cost_to_previous_op`, `test_no_cost_attribution_when_requests_overlap` (two threads on a barrier), `test_request_count_headers_captured_and_warned_once`; the `last_rate` shape assertion gained the two `req_*` keys. 13 tests in `tests/test_wcl_client.py`.

## [TEST] 2026-10-01 — Fixture recorder keeps gear/talents/buffs/abilities, adds --clean and 6.5 MB budget

**Files:** tests/make_fixtures.py, tests/test_make_fixtures.py
**Why:** The upcoming per-player analysis reads gear, talent trees, stat blocks, top abilities and event buffs/mitigation, which slim() was stripping; re-recording also needed to start from an empty fixture cache.
**What:**
- `_TABLE_DROP` is now `{talents, damageAbilities, given, taken, pets}` (keeps `gear`, `targets`); `abilities` truncated to top 8 by `total`.
- cinfo: every player keeps `timestamp,type,fight,sourceID,auras,specID`; up to 3 players per fight (one tank/healer/dps first, role from table icon via `dash.common.spec_role`, then cinfo order) also keep `gear`, `talentTree` and the stat keys (`strength`..`versatilityDamageReduction`, list `_CINFO_STATS`, taken from a real cinfo event).
- `_EVENT_KEEP` += `buffs, mitigated, hitType, blocked`. Puller-entry branch unchanged.
- New `--clean` (real-record mode only) wipes `tests/fixtures/cache/*` via shutil/os before recording; ignored with `--slim`.
- `check_budget()` prints the fixture cache size and raises SystemExit above `SIZE_BUDGET` = 6.5 MB (runs after record and after `--slim`).
- Docstring documents budget and re-record procedure.
- New `tests/test_make_fixtures.py` (8 tests) on synthetic files in tmp_path.

**Notes:** Current fixtures were recorded with the old slimming, so they still lack gear/talents/buffs; `--slim` cannot restore them (4.63 MB now). The real re-record is pending: `venv/bin/python tests/make_fixtures.py --clean` (default report 3w1jJ8BZ2m9kMrYG); the budget only becomes meaningful then.
- Budget raised from 6.5 to 7.5 MB on the first real re-record (6.85 MB measured); see the wipeCalledTime [FEAT] entry. That re-record has now been done.

## [FIX] 2026-10-01 — Fetcher hygiene: buffs targetID leak, nextPageTimestamp pagination, filter as variable

**Files:** collect_data.py, tests/test_units.py, tests/test_collect_offline.py
**Why:** The first-death Buffs query (`targetID:`) also returns buffs the dying actor cast on others, so e.g. a dying healer's Pain Suppression on a tank showed up as an external they received. The aliased `events(...)` fetchers ignored `nextPageTimestamp` and silently truncated at their `limit`. The consumable filter was string-interpolated into the query text.
**What:**
- `attach_casts()`: skip any buff unless `targetID == death["actor_id"]`; self-buffs still skipped. Call site unchanged (it already passes `deaths[0]`, which carries `actor_id`).
- New `_follow_pages(code, fight, kind, alias, part_fn, page, query_name, var_decl, variables)`: follows `nextPageTimestamp` with single-alias follow-up queries (same variables), `count_api_call(1)` per follow-up, concatenates `data`, prints `  (page 2+ needed for <code>:<fid> <kind>)` once per fight/kind; stops if the cursor does not advance.
- New `_cinfo_part(fight, start_ms)`; `_bundle_query()` cinfo alias and `_fetch_bundle_batch()` now request/follow `nextPageTimestamp`.
- `get_consumable_casts()`: alias builder `part(f, start_ms)`; query is `ConsumableCasts($code: String!, $filter: String)` with `filterExpression: $filter`, variables `{"code", "filter"}`; pages followed.
- `get_first_death_casts()`: alias builder `part(kind, fight, death, start_ms)` + `window_of()`; casts and buffs pages followed.
- Follow-up failures in the cons/casts fetchers are inside the existing `WCLError` handler, so a partial result is never cached.
- `get_pull_events()` untouched (deliberately earliest events only).
- Tests: buff targetID filter (synthetic + fixture entry 67b181e8, Earth Shield 4->13), pagination for consumables / first-death buffs / bundle cinfo (2 run_query calls, api counter +2), filter-as-variable + unchanged `_cons_key`.
**Notes:** No version bumps: `_bundle_key`, `_cons_key`, `_casts_key` are built from version/code/fight id/ids/window only, never query text, so existing cache entries and fixtures stay valid. Cached entries fetched before this fix may still be truncated if they hit the limit; only `--refresh` (or a version bump) would re-fetch them. The buffs fix is applied at read time, so it corrects cached data too.
