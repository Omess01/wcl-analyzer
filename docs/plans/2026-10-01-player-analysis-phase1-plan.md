> Orchestrator's working plan for Phase 1, copied verbatim on 2026-10-02; the §4 owner-decision defaults were adopted (see `docs/CHANGES_2026-10-02.md` for what was actually built).

# Phase 1 implementation plan — "Mine the cache": per-player cards, deaths/prep/avoidable/throughput/gear/healer/tank metrics, RL rollups

All paths are under `/home/omess/Projects/WCL_analyzer/`. Line numbers were verified against the working tree on 2026-10-01 (Phase 0 uncommitted).

## 0. Measured baselines and contracts the tasks share

**Payload today.** Fixture (`tests/fixtures`, 4 pulls, 15–16 players): 18,636 B base64 total = **4,659 B base64 per pull** (raw JSON 14.5 KB/pull). Real builds in `dashboards/`: `dashboard_2026-09-01_to_2026-09-21.html` = 138 pulls, 830,288 B base64 (6,016 B/pull), file 1.26 MB; `dashboard_2026-08-19_to_2026-10-01.html` = 269 pulls (6,284 player-pulls, 23.4 players/pull), 1,589,504 B base64 (5,908 B/pull), file 2.24 MB. Raw JSON is 47 % `dt`, 33 % `deaths`. Raw→base64 ratio measured 4.2:1. A "month" ≈ 140–200 pulls; the +0.7 MB/month budget (Q4) therefore allows ≈ +3.5 KB base64 per pull; the design's Phase-1 target is ≤ +0.8 KB base64 per pull and the estimate below lands at ≈ +0.65 KB/pull (+ ≈ 60 KB per build for the Players-tab block) ≈ **+0.18–0.2 MB/month**.

**Fixture facts (what tests can exercise).** One night only (`Wed 2026-09-09 open`) → the own-history baseline is never available on the fixture (synthetic tests only); roles: 2 Vengeance DH tanks (`Airohdh` actor 13, `Ixavior` actor 5 — actor 5 is one of the 3 full-cinfo players), 2 healers (`Gigaspinning` Mistweaver actor 3, full cinfo; `Maxiumus` Holy Paladin), 12–13 DPS (role median with ≥ 3 others works for DPS; tanks use the co-tank; healers fall to bands). Fights: 2 Nek'zali kill 199.5 s (0 deaths), 7 Coiled Altar kill 250.6 s (5 deaths, 4 without `killingBlow`), 8 Ula'tek wipe 105.0 s (17 deaths at 57.1, 66.1, 70.1, 92.5, 93.6, 94.0, 94.6, 94.7, 94.8, 95.0, 95.6, 96.2, 99.0, 99.6, 101.0, 104.0, 104.8 s), 9 Ula'tek kill 273.2 s (1 death). Kills carry rankings for every player (`rankPercent`, `bracketPercent`, `spec`). `buffs` is present on 93–99 % of damage events (≥ 99 % on the two tanks; Demon Spikes 203819 is up on 55–82 % of their connected hits), `mitigated` on ~88 %, `hitType` always (values 0,1,2,7,8,10 — no block codes; the `blocked` key never appears). `deathSaveAbility` appears on 0 Deaths rows. Table rows (all players) carry `itemLevel`, `overheal` (healing table), `gear[{slot,id,itemLevel,permanentEnchant,permanentEnchantName,gems,bonusIDs}]`; cinfo gear only for 3 players per fight (no `slot`, index = slot). Fixture gear majority: enchants on slots 0,2,4,6,7,10,11,15 (14–15 of 15), 0/15 on back (14) and wrist (8), 4/15 off hand; gems 15/15 on neck (1) and rings (10, 11). `consumables` for all players on all 4 pulls; `consumable_use` for 3–6 players per pull; first-death cast data on fights 7, 8, 9. `wipe_called_s` is `None` on every pull.

**Contract A — `PM_COLS` (Phase 1, 23 columns; `ish` removed, see §3).** Defined once in `analysis/player_metrics.py`; `dash/payload.py` imports it; the roundtrip test asserts equality with this exact list. Appending only.

```
act dps hps dth fd alv avh avm dtk dtps prep pot hs ir ds ilvl rp bp oh mit am amw gap
```

All values small ints or `null`; trailing `null`s popped (JS tolerates short vectors). Definitions (pull dict fields; `cutoff` = Contract B):

| col | definition | scale | null when |
|---|---|---|---|
| `act` | `round(100·active_seconds/duration_seconds)`; healers (role from Contract D) use the healing row, others the damage row, fallback the other row | % | no row |
| `dps` | `round(damage_done.total / active_seconds / 1000)` (active DPS) | k | no damage row or active_seconds < 1 |
| `hps` | `round(healing_done.total / active_seconds / 1000)` — **healers only** (pinned: every player has a self-heal row; emitting it for all is noise and bytes) | k | role ≠ healer or no row |
| `dth` | count of `deaths[]` with `player == label` and `seconds_into_fight <= cutoff` (no cutoff → all) | int | — |
| `fd` | `1` if `deaths[0].player == label` else `0` | 0/1 | pull has no deaths |
| `alv` | `int(min(first own death s, duration))`, floor 1 | s | — |
| `avh` | Σ over `damage_taken` rows with `normalize(ability) in avoidable − ignored` of `len([t for t in times if t <= cutoff])` | int | boss has no avoidable list |
| `avm` | `round(avh / (alv/60) · 10)` | ×10 | `avh` null or alv < 1 |
| `dtk` | Σ `amount` of non-self enemy damage events with `seconds <= cutoff` (from the Contract C digest), `round(/1000)`. **Pinned deviation:** `_ignore` abilities are *not* excluded (the digest is computed in `collect_data`, which does not load `avoidable.json`; they are trinket procs worth a few k) | k | no digest |
| `dtps` | `round(dtk_raw / alv / 100)` (so 1420 ↔ 142.0 k/s) | ×10 k/s | as `dtk` |
| `prep` | bitmask flask 1 · food 2 · rune 4 · prepot 8 · vantus 16 from `consumables[label]` | int | `has_extras` false or label absent |
| `pot` / `hs` | `consumable_use[label].combat_potion` / `healing_potion + healthstone` | int | pull has no `consumable_use` entries at all (`{}`) |
| `ir` / `ds` | `interrupts[label]`, `dispels[label]` (0 default) | int | `has_extras` false |
| `ilvl` | table `ilvl` (damage row, else healing row); fallback mean of cinfo gear ilvl over slots ∉ {3, 17} with ilvl > 0 | int | neither |
| `rp` / `bp` | `parses[label]` rank / bracket percentile of the role metric (hps for healers, dps otherwise) | int | wipe or no ranking |
| `oh` | `round(100·overheal/(total+overheal))` from the healing row, healers only | % | role ≠ healer or total+overheal = 0 |
| `mit` | `round(100·(Σmitigated + Σabsorbed)/ΣunmitigatedAmount)` over the tank's non-self, enemy-source damage events (ticks included) that carry `unmitigatedAmount > 0`; missing `mitigated`/`absorbed` count as 0 | % | role ≠ tank or no such events |
| `am` | over the tank's **connected** non-tick non-self enemy hits (`hitType ∈ {1,2,4,5}`) that carry a `buffs` key: `round(100·hits with an AM id of the tank's spec in the dot-separated buffs string / hits)`. **Pinned deviation:** avoidable hits are *not* excluded (keeps the digest free of `avoidable.json`; tanks take few) | % | role ≠ tank, spec not in `tank_mitigation.json`, 0 hits, or hits lacking `buffs` > 30 % of the tank's connected hits ("aura data incomplete") |
| `amw` | same, weighted by `unmitigatedAmount` (fallback `amount+absorbed`) | % | as `am` |
| `gap` | gear-gap count for this pull's gear from `analysis/gear.py` (Contract E) | int | no gear |

**Contract B — post-wipe cutoff (fallback for the unusable `wipe_called_s`).** `analysis/wipe.py::wipe_cutoff_s(kill, duration_s, death_times, wipe_called_s) -> float|None`: if `wipe_called_s` is not None return it; kills → `None`; otherwise sort death times and take the longest suffix whose consecutive gaps are all ≤ `WIPE_CASCADE_GAP_S = 10.0`; if that suffix has ≥ `WIPE_CASCADE_MIN_DEATHS = 3` deaths and its last death is within `WIPE_TAIL_S = 20.0` of `duration_s`, the cutoff is the **first death of the suffix** (that death still counts; everything strictly after it does not); else `None`. Fixture fight 8 → cutoff 92.5 (deaths at 57.1/66.1/70.1/92.5 count, 13 excluded); fights 2/7/9 → `None`. Pull dict key `wipe_cutoff_s`; payload per pull `wc`. `fd` and `alv` ignore the cutoff; `dth`, `avh`, `avm`, `dtk`, `dtps`, `mit`, `am`, `amw` apply it (`seconds <= cutoff`). Card wording: "deaths and hits after the wipe started are not counted (a wipe starts at the first death of a run of 3+ deaths within 10 s that runs to the end of the pull)".

**Contract C — per-player event digest in the pull dict.** `collect_data` stores `pull["player_events"] = {label: {"dtk": int, "hits": int, "hits_buffs": int, "am_up": int, "amw_num": int, "amw_den": int, "mit_num": int, "mit_den": int, "dodge_parry_miss": int}}` from `analysis.mitigation.digest_events(events, participants, spec_ids, cutoff)`; only tanks get the `am*`/`mit*` keys. `get_damage_events` keeps per event: `buffs` (str or None), `mitigated` (int or None), `hit_type` (int), `blocked` (int or None). Pull dict also gets `pull["gear"] = {label: [[slot, item_ilvl, enchant_id_or_0, n_gems, item_id], ...]}` (18 rows from the damage-table row's `gear` with `slot`; fallback healing row; fallback cinfo `gear` with index = slot) and `healing_done[i]["overheal"]`, `parses[label]` gains `bdps`/`bhps` (bracket) and `spec`.

**Contract D — roles.** Per pull: `specs.spec_of(pull["spec_ids"][label])` → role; fallback `dash.common.pull_specs(p)` token → `specs.role_of_token`. Support specs (`SUPPORT_SPECS`) are excluded from role medians and get a Note.

**Contract E — Players-tab payload** `<script type='application/gzip+base64' id='data_tabPlayers'>` (plain JSON under `--uncompressed`), produced by `dash/payload.py::players_payload(...)`:
```
{cols: PM_COLS,
 roster: {label: {cl, spec, role, pulls, support: 0/1}},
 nights: [[night, type, startMs], ...]  (chronological),
 sev: {label: {night: [[metric, value, baseline, bkind, level, score, tpl, affected, pulls], ...]}},
 gear: {label: {ilvl, gaps: ["head: no enchant", "ring 2: empty socket", "wrist 15 ilvl below your average"], ilvl_min, ilvl_max}},
 advice: {tpl: "sentence with {value} {baseline} placeholders"},
 named: true|false}
```
`bkind ∈ own|role|cotank|band|null`, `level ∈ good|watch|note`, `metric` is a PM col name or one of `nodef`, `prepot`, `dps_ratio`. The per-boss `cfg` script gains `"named": bool`.

## 1. Tasks

### T1 — Analysis core: `PM_COLS`, metric vector, wipe cutoff, event digest, tank mitigation, collector hooks (fable)

**Goal.** Create the `analysis/` package with the single source of truth for Phase-1 metrics and give `collect_data` the few extra reads it needs from already-cached data (no new API calls, no cache-key change). **User-visible result:** none yet (data layer); console gains `tank mitigation: <spec> ids never seen in any tank's buffs: …` and `data/tank_buffs_seen.json`.

**Files / functions.**
- New `analysis/__init__.py` (empty docstring), `analysis/wipe.py` (Contract B, stdlib only), `analysis/mitigation.py` (Contract C digest; `load_tank_mitigation()` reading `config/tank_mitigation.json` via `path.CONFIG_DIR`; `am_ids_for(spec_token) -> set[int]`; `TANK_BUFFS_SEEN` counter per spec token), `analysis/player_metrics.py` (`PM_COLS`, `COL = {name: idx}`, `player_metrics(pull, avoidable: set, ignored: set, gear_gaps: dict|None) -> {label: list}`, `trim(vec)` popping trailing nulls; may import `collect_data.normalize` and `specs` — it is imported only from `dash/`, so no cycle; `analysis/wipe.py` and `analysis/mitigation.py` must import nothing from `dash/` or `collect_data`).
- `collect_data.py`: `get_damage_events` 1269–1319 — extend the event dict at 1294–1316 with `buffs`, `mitigated`, `hit_type`, `blocked`; `player_tables_from_bundle` 837–873 — add `"overheal": e.get("overheal") or 0` next to `ilvl` at 869; new `gear_from_bundle(bundle, actors, lab, participants)` after 873 (table gear by `slot`, fallback cinfo gear by index); `get_parses` 1395–1420 — at 1416–1419 also store `b<metric>` = `bracketPercent` and `spec`; in `collect()` insert before the pull dict (after 1663): `cutoff = wipe_cutoff_s(fight.get("kill"), duration, [d["seconds_into_fight"] for d in deaths], wipe_called)`, `digest = digest_events(events, participants, spec_ids, cutoff)`, `gear = gear_from_bundle(...)`; add keys `wipe_cutoff_s`, `player_events`, `gear` to the dict at 1670–1704 (comment: not emitted raw in the payload); module-level `TANK_BUFFS_SEEN` next to `NIGHT_FIGHTS` (cleared in `collect()` like `NIGHT_FIGHTS.clear()` at 1524).
- `build_dashboard.py`: `write_tank_buffs_seen()` next to `write_abilities_seen` (39–58) writing `data/tank_buffs_seen.json` = `{spec_token: {buff_id: count}}` top 25 per spec, called from `main()` after line 170; `validate_config` (61–95) warns for each configured AM/major id never seen on that spec's tanks in the build (skip when the spec had no tank).
- New `config/tank_mitigation.json` + `config/tank_mitigation.example.json`.
- Tests: new `tests/test_player_metrics.py`, `tests/test_mitigation.py` (synthetic), append to `tests/test_collect_offline.py`.

**Metric definitions.** Contracts A, B, C above (all of them are this task's deliverable). Self-inflicted events (`self`) and ticks are handled exactly as `aggregate_damage` does (1344–1362); enemy source = `source` not a participant label (use `src_actor` absence or the existing `source` string from `npc_names`).

**Payload impact.** None (pull-dict-only). Pull dicts grow by ~2 KB per pull in memory.

**Config (Q5).** `config/tank_mitigation.json`, schema `{"_comment": str, "<SpecToken>": {"am": [{"id": int, "name": str}], "major": [{"id": int, "name": str}]}, "_changelog": [...]}` keyed by the `specs.py` spec token (`Vengeance`, `Protection` is ambiguous → key `"Protection Paladin"`/`"Protection Warrior"` by `"<Class> <Spec>"` exactly as the design says; resolver maps `(class, token)`). Sensible default content can be written from game knowledge but **ids are TWW-era and must be verified by the owner** against `data/tank_buffs_seen.json`: Vengeance `am` Demon Spikes 203819 (verified in the fixture), `major` Metamorphosis 187827 (seen in fixture tank buffs), Fiery Brand 207771 (seen), Soul Barrier 263648; Protection Paladin `am` Shield of the Righteous 132403, `major` Ardent Defender 31850, Guardian of Ancient Kings 86659, Divine Shield 642, Eye of Tyr 387174; Protection Warrior `am` Shield Block 132404, Ignore Pain 190456, `major` Shield Wall 871, Last Stand 12975, Spell Reflection 23920; Blood `am` Bone Shield 195181, Rune Tap 194679, `major` Vampiric Blood 55233, Dancing Rune Weapon 81256, Icebound Fortitude 48792, Anti-Magic Shell 48707; Guardian `am` Ironfur 192081, `major` Barkskin 22812, Survival Instincts 61336, Rage of the Sleeper 200851; Brewmaster `am` Shuffle 215479, `major` Fortifying Brew 120954, Celestial Brew 322507, Dampen Harm 122278, Diffuse Magic 122783, Zen Meditation 115176. Unknown spec → nulls + one console note. `major` is unused in Phase 1 (Phase 3 T4) but validated now.

**Tests.** `test_player_metrics.py`: `PM_COLS` equals the Contract-A list; synthetic pull with a player who has no table row (nulls), a healer with overheal (`oh`, `hps`), a tank (digest → `mit/am/amw`), death at 0 s (`alv` = 1), wipe with cascade (cutoff excludes later deaths/hits from `dth/avh/avm/dtk` but not `fd/alv`), kill (`rp/bp` present, no cutoff), `trim()` pops trailing nulls only; `avh` counts `times <= cutoff`. `test_mitigation.py`: cutoff heuristic on the fixture death list (→ 92.5), on 2 deaths (None), on a cascade that ends 40 s before the fight end (None), on `wipe_called_s` set (returned as is); digest with/without `buffs`, the 30 % rule, connected-hit filter (hitType 7/8/10 excluded), weighted share, missing `mitigated`; `am_ids_for` resolves `(DemonHunter, Vengeance)`; unknown spec → `None`. `test_collect_offline.py`: every pull has `wipe_cutoff_s`, `player_events`, `gear`; fight 8 cutoff == 92.5 and the other three `None`; both tanks have `am` between 50 and 90 and `hits_buffs/hits ≥ 0.95`; healing rows carry `overheal`; parses on kills carry `bdps`/`bhps` ints 0–100 and `spec`; `gear[label]` has 18 rows for every damage-table player. Fixture cannot exercise: `wipe_called_s` set, blocked hits, non-DH tank specs.

**DoD.** `venv/bin/python -m pytest -q` green (expected 152 + new); `venv/bin/python -c "import quickjs; quickjs.Context().eval('(function(){' + open('dash/static/dash.js').read() + '})')"` unchanged; offline fixture replay prints 0 API calls; no payload change (fixture per-pull base64 still 4,659 ± 0).

**Dependencies / concurrency.** None. Sole owner of `collect_data.py`, `build_dashboard.py`, `analysis/{__init__,wipe,mitigation,player_metrics}.py`, `config/tank_mitigation*.json`, `tests/test_collect_offline.py` in wave 1. Hands over Contracts A–C to T3/T4 (pinned here, so they can start in parallel).

### T2 — Gear checks (opus)

**Goal.** Pure `analysis/gear.py` turning the Contract-C `gear` rows into ilvl stats and a gap list, using a roster-majority rule because Midnight's enchantable/socketed slots differ from the design's list (fixture: head/shoulder enchanted 14–15/15, back/wrist 0/15; gems on neck and rings). **User-visible result:** card block 9 "Gear: ilvl 312 (raid 305–321) · head: no enchant · ring 2: empty socket" and R9 counts (via T6/T8).

**Files.** New `analysis/gear.py`: `slot_name(slot)`; `roster_rules(gear_by_label, cfg) -> {"enchant_slots": set, "gem_slots": set}` (a slot is required when ≥ `majority` (0.5) of the roster's non-empty items in it carry `permanentEnchant` / ≥ 1 gem; explicit lists in the config override `"auto"`); `gear_report(rows, rules, cfg) -> {"ilvl": int, "gaps": [str], "n_gaps": int}` (missing enchant per required slot; 0 gems in a required gem slot → "empty socket"; item ilvl ≤ player mean − `low_slot_gap` (15) → "N ilvl below your average"; skip slots in `skip_slots` [3, 17] and rows with `item_id == 0` or ilvl 0); `latest_gear(pulls_by_label)` picking each player's most recent pull with gear. Imports `path.CONFIG_DIR` and json only. New `config/gear_checks.json` + `.example.json`. New `tests/test_gear.py`.

**Metric definitions.** As above; `gap` (PM col) = `n_gaps`.

**Payload impact.** None directly (T3 emits `gap` per pull and the `gear` block per player, ≈ 120 B raw per player per build).

**Config.** `gear_checks.json`: `{"_comment", "enchantable": "auto" | [slots], "socket_slots": "auto" | [slots], "majority": 0.5, "skip_slots": [3, 17], "low_slot_gap": 15, "slot_names": {"0": "head", "1": "neck", "2": "shoulder", "3": "shirt", "4": "chest", "5": "waist", "6": "legs", "7": "feet", "8": "wrist", "9": "hands", "10": "ring 1", "11": "ring 2", "12": "trinket 1", "13": "trinket 2", "14": "back", "15": "main hand", "16": "off hand", "17": "tabard"}}`. Default content can be written now (the slot order is Blizzard's inventory order and matches the fixture); the owner may later pin explicit lists.

**Tests.** `test_gear.py` (synthetic + fixture shapes copied as literals): majority rule picks slots {0,2,4,6,7,10,11,15} for the fixture-like distribution and not 14/16; explicit list overrides auto; empty socket only in gem slots; low-slot rule; shirt/tabard skipped; player with 3 rows only (cinfo-less) still gets an ilvl. Fixture coverage comes through T3's offline test (`gear` block for every roster player, 2–4 enchant slots required).

**DoD.** pytest green; no other files touched.

**Dependencies / concurrency.** None; disjoint from T1 (reads Contract C shape only). Wave 1.

### T4 — Severity engine (fable)

**Goal.** The single Good/Watch/Note engine in Python (`analysis/severity.py`) per player × night × metric, following design §7.3 with the definitions pinned below so the JS never re-scores. **User-visible result:** card headline counts, "One thing to work on", tile deltas, and the named rollups all read this block.

**Files.** New `analysis/severity.py`: `compute(bosses, pm_by_key, specs_by_key, cols, named=False) -> {"sev": …, "advice": ADVICE, "nights": [...]}` where `pm_by_key[(boss,diff)][i] = {label: vec}` and `specs_by_key[(boss,diff)][i] = {label: spec_token}` (caller supplies them; roles via `specs.role_of_token`, support via `specs.SPECS`); `ADVICE` template map; `aggregate_night(...)`; `baseline(...)`; `score(...)`. Imports only stdlib + `specs`. New `tests/test_severity.py`.

**Definitions (pinned where the design is vague).**
- Night value per metric (over the player's pulls that night; pulls < 60 s excluded from `act`, `dps_ratio`, `oh`, `am`): `dth` = Σdth/pulls; `fd` = 100·Σfd/pulls attended; `avm` = Σavh/(Σalv/60) over pulls with non-null avh; `nodef` = 100·(first deaths with `has_cast_data` and no `defensives` and no `externals`)/(first deaths with cast data), only if that denominator ≥ 2; `prep` = number of pulls with flask, food or rune missing (bits 1/2/4), Watch-eligible; `prepot` = pulls with bit 8 missing, **Note only** (CLAUDE.md §11: WCL returns no pre-pull events, so the flag under-reports); `act` = median; `dps_ratio` = median over pulls of 100·own `dps`/(median `dps` of the other same-role non-support players in that pull, ≥ 3 others); `oh` = median (healers); `am` = median (tanks); Note-only items: `ilvl` (latest), `rp`/`bp` (mean over kills), `gap` (latest), `ir`/`ds` (per pull).
- Baseline order: own history (median of the same metric over the player's **earlier nights of the same night type**, ≥ 2 such nights) → role median (median over the other players of the role present in ≥ 25 % of that night's pulls, ≥ 3 others; tanks → the co-tank's value, `bkind="cotank"`; support specs excluded) → band (`act` 90 %, `oh` 30 %, `am` 80 %, `nodef` 50 %, `avm` none, `dth` none) → null (Note, "first nights — no baseline yet").
- Tolerance / direction / tier exactly design §7.3: `dth` ±0.15 lower 1; `fd` ±10 pts lower 1; `avm` ±25 % rel lower 2; `nodef` ±25 pts lower 3; `am` ±5 pts higher 3; `prep` tolerance 1 pull, no-miss 4; `act` ±3 pts higher 5; `dps_ratio` ±8 % rel higher 6; `oh` ±5 pts lower 6.
- `affected` = pulls whose own per-pull value is worse than baseline beyond tolerance in the scored direction (for `prep`: missed pulls); `score = |value − baseline| / tolerance × affected / pulls`; level: Watch when worse beyond tolerance and `affected ≥ max(3, ceil(0.25·pulls))`; Good when at/better than baseline or within tolerance; Note when `bkind` is band/null or the metric is Note-only. Tier breaks ties (lower tier first). "One thing" = highest-scoring Watch of the night; "best Good" = highest score in the good direction. Public cap (≤ 3 Watch, always ≥ 1 Good if any Good exists) is applied in JS using `level` + `score`; the engine emits everything; `named` only adds the `rank` field (`"3 of 12"`) to items when true.
- ADVICE templates: one plain sentence per metric with `{value}`, `{baseline}`, `{n}`, `{pulls}` placeholders (e.g. `dth`: "Deaths {value} per pull vs {baseline}. Look at the recap of each death: was a defensive or a position available?"; `prepot`: "Pre-pot flagged on {n} of {pulls} pulls — WCL only sees potions pressed after the pull starts, so this under-reports."). No per-spec text.

**Payload impact.** `sev` ≈ 10 items × 45 B per player-night → real build ≈ 240 KB raw ≈ 55 KB base64 per build (not per pull); fixture ≈ 7 KB raw.

**Tests.** `test_severity.py` with synthetic pm vectors (use Contract-A column order via the `cols` argument): own-history baseline needs ≥ 2 earlier nights of the same type (open nights do not feed a main night's baseline); role median excludes self, support and < 25 % players; co-tank path; band fallback; score and the ≥ max(3, 25 %) rule; `prepot` never Watch; short pulls excluded from `act/dps_ratio/oh/am` but not from `dth/prep/avm`; `dps_ratio` uses per-pull others' median; deterministic ordering (level, tier, score). Fixture cannot exercise own history (one night).

**DoD.** pytest green; module imports only stdlib + `specs`.

**Dependencies / concurrency.** None (takes `cols` as an argument, so it does not import T1's module; T3 passes `PM_COLS`). Wave 1.

### T5 — Card components: sparkline, bullet bar, box row, small multiples, delta text (opus)

**Goal.** Pure, quickjs-testable HTML/SVG builders in `dash.js` plus their CSS, so T6 only composes. **User-visible result:** none until T6.

**Files.** `dash/static/dash.js`: new marker block right after `// --- end pure chart helpers ---` (line 220): `// --- card components (quickjs-testable) ---` … `// --- end card components ---` containing `sparkline(values, {w:96,h:28})` (SVG polyline + current point; returns `''` for < 4 values), `bulletBar(value, target, own, max, labels)` (≤ 24 px bar, target tick = role median, second tick = own median, all values as text), `boxRow(items)` (`<button class='box lvl-…'>` per item with glyph + `<span class='sr-only'>` word + `title`), `smallMultiples(series)` (per boss: dots per pull, own median line, grey band, kill marker; sentence for < 4 pulls), `deltaText(cur, prev, fmt, lowerIsBetter, period)` (mirrors `_delta` in `dash/home.py` 295–305, same `delta better|worse` classes), `uptimeBar(share, text)`. Colours only via `TOK`, status classes via CSS. `dash/static/dash.css`: `.card`, `.card .kpi dd .spark`, `.bullet`, `.boxrow .box`, `.multiples`, `.status-good/.status-watch/.status-note` (text + glyph, colour supplementary), ≤ 700 px rules (tiles 2-up, multiples 120 px). Tests appended to `tests/test_dashboard.py` with a `_card_components(quickjs)` evaluator like `_pure_chart_helpers` (125–134).

**Payload impact.** None.

**Tests.** quickjs: sparkline omitted below 4 values, SVG has a `<title>`; bulletBar labels every tick with text; boxRow glyph + sr word per level; smallMultiples skip rule; deltaText sign/period/direction; no hex literals (`test_no_raw_colours_outside_tokens` 531–538 keeps passing); JS syntax check.

**DoD.** pytest green, quickjs check passes.

**Dependencies / concurrency.** None; sole owner of `dash.js`, `dash.css`, `tests/test_dashboard.py` in wave 1.

### T3 — Payload: `pm`/`pmcols`/`wc`, death flags, ilvl/bracket, Players-tab block, `cfg.named`, size guard (opus)

**Goal.** Emit every Phase-1 datum to the browser within budget. **User-visible result:** none until T6 (payload only), but the fixture dashboard already carries the data.

**Files / functions.**
- `dash/payload.py`: `_death_payload` 73–84 adds `"av": 1 if killing blow (`kb`) or ≥ 50 % of `window_damage` comes from `avoidable − ignored` abilities else 0` (signature gains `avoidable, ignored`); for a dying **tank** each recap row (74–75) gains a 6th element `1/0/null` = AM id present in that event's `buffs` (needs `e.get("buffs")` on recap events — present after T1; `am_ids_for` from `analysis.mitigation`; `null` when the event has no `buffs`) — this is T7 of the design at ~50 B per tank death. `pull_payload` 109–176: new kwarg `pm: list[dict] | None`; per pull add `"pm": {label: trim(vec)}`, `"wc": p.get("wipe_cutoff_s")`; **`kc` (interrupt cast counts) is dropped from Phase 1** (no denominator available; R7 uses per-player `ir` counts only); `dd`/`hd` rows (156–157) gain `e["ilvl"]` as 6th element; `parses` emitted as stored (gains `bdps/bhps/spec` from T1); boss level `"pmcols": PM_COLS`. New `all_metrics(bosses, avoidable_cfg, gear_rules) -> {key: [ {label: vec} ]}` calling `analysis.player_metrics.player_metrics` with `avoidable_set(cfg, boss)`, `ignore_set(cfg)` and per-pull `gap` from `analysis.gear.gear_report`. New `players_payload(bosses, ordered, avoidable_cfg, pm_by_key, named, compress) -> (mime, text)` building Contract E via `analysis.severity.compute(..., cols=PM_COLS)` and `analysis.gear`.
- `dash/page.py`: `build_html` 74–214 — compute `mode` (`getattr(args, "callouts", None) or os.getenv("HOME_CALLOUTS", "anonymous")`, same as `home.py:407`), `pm_by_key = all_metrics(...)` once; pass `pm=pm_by_key[key]` into `boss_tab`/`pull_payload` (25–31); emit the Players payload script before `<div class='static' id='static_tabPlayers'>` at 115–116; `cfg` script (150) becomes `json_for_script({**specs.role_sets(), "named": mode == "named"})`.
- Tests in `tests/test_dashboard.py`: extend `_payloads` (23–32) regex to also capture `data_tabPlayers` separately (keep `len(payloads) == len(bosses)` in `test_build_html_structure` by filtering `tab\d+`); roundtrip test (35–55) asserts `pmcols == PM_COLS`, every participant has a `pm` vector of length ≤ 23 with ints/nulls, `wc` present (92.5 on fight 8), deaths carry `av`, `dd` rows have 6 elements; Players payload inflates, has `cols/roster/nights/sev/gear/advice/named`, `sev` has an entry for every roster player for the fixture night, `gear[label].ilvl` for every damage-table player; **size guard:** fixture per-pull base64 ≤ 4,659 + 800 B and Players block ≤ 25 KB base64; `cfg` JSON has `named` false by default and true with `callouts="named"`; `--uncompressed` works for the Players block too.

**Payload impact (per pull, 23.4 players).** `pm` ≈ 100 B raw per player → 2.3 KB; `wc` ≈ 10 B; `deaths[].av` ≈ 35 B (+ ≈ 50 B tank recap flags); `dd/hd` ilvl ≈ 190 B; `parses` bracket+spec ≈ 400 B on kills (≈ 140 B averaged). ≈ +2.75 KB raw/pull ≈ **+0.65 KB base64/pull** (measured ratio) → ≈ +90–130 KB per month of 140–200 pulls. Players block ≈ 55–65 KB base64 per build. Total ≈ +0.15–0.2 MB/month, under the +0.7 MB budget; boss-tab inflation time grows ≈ 5 %.

**Config.** None new.

**DoD.** pytest green incl. size guard; quickjs check; fixture build via `test_build_html_structure` writes `out.html`; report the measured fixture per-pull base64 before/after.

**Dependencies / concurrency.** After T1, T2, T4. Wave 2, concurrent with T7 (T7 touches only `dash.js` + a new test file; T3 touches no JS).

### T7 — Self-selection and deep links (opus)

**Goal.** Design §7.2 minus the datalist: `#tabPlayers?player=<label>` read on load and written on change, click-your-name in tables, remembered last player, "Show my card", copy-link handler. **User-visible result:** a raider opens the Discord link with their name pre-selected; clicking a name anywhere sets the Player filter.

**Files.** `dash/static/dash.js` only: deep-link parser 1124–1133 — split the hash on `?` before the `:` split; `playerHash(name)` / `parsePlayerHash(hash)` pure helpers (URL-encode/decode, apostrophes and `Name-Realm` labels) inside the table-helpers block (50–145); `applyGlobal` 1005–1024 writes `history.replaceState` with `#tabPlayers?player=…` when a player is set and the Players tab is active (else keeps `#tabN`), stores `wcl_dash_player` in `store`; `clearAll` 1030–1039 clears the hash param; delegated click on `tr[data-player] .player, [data-player-pick]` → sets `gPlayer.value` and calls `applyGlobal()`; "Show my card" button (`#showMyCard`, rendered by JS into `detail_tabPlayers` in the unfiltered state when a stored name exists in `gPlayer.options`); `.copy-link` delegated handler using `navigator.clipboard.writeText(location.href.split('#')[0] + playerHash(name))` with a textContent fallback. New `tests/test_players_tab.py`: quickjs tests for `playerHash`/`parsePlayerHash` (round-trip of `Nek'zali`-style apostrophes and `Name-Realm`), source assertions that the hash parser splits on `?` first and that `test_plain_hash_deep_link_does_not_scroll` (207) still holds.

**Payload impact.** None.

**DoD.** pytest + quickjs green.

**Dependencies / concurrency.** None functionally; wave 2 because `dash.js` is owned by T5 in wave 1 and T6 in wave 3.

### T6 — Player card renderer (opus; fable review)

**Goal.** Replace the per-boss table in `renderPlayersTab` (1088–1104) with the card (design §7.3 blocks 1–9, Phase-1 parts) and inflate the Players payload. **User-visible result:** selecting a player on the Players tab shows: headline with spec · nights · pulls · Good/Watch/Note counts; "One thing to work on" (`article.insight` with `h3`); KPI tiles (deaths/pull, first-death share, avoidable hits/min alive, active %, median active DPS or HPS, prep misses, kills parse·bracket, ilvl) with delta vs earlier nights and sparklines (≥ 4 nights); per-boss rows table (gotab links); consistency small multiples per boss with ≥ 4 pulls; role section — DPS: active-DPS bullet vs role median (+ same-spec line when `CFG.named`); healer: overheal bullet + HPS tile + "damage done" note (H9) + HPS parse/bracket (H10); tank: AM-at-hit uptime bar (`am`, `amw`), mitigated share, co-tank paired DTPS per pull (T2), death recap rows show the AM flag (T7); deaths report card (box row per death: first? avoidable `av`? defensive used/none/unknown (first death only), external received; expand → existing `recapHtml`), with the Contract-B wording; preparation glyph row per category + "missed on N of M", pre-pot marked "under-reported"; gear block from `gear`. The "Who pulls first" matrix and "All pulls" stay below. Empty states: < 2 nights → "first nights — no trend yet"; no pulls → existing empty state.

**Files.** `dash/static/dash.js`: inflate `data_tabPlayers` in the loading block (443–457) into `PLAYERS = {data}` (its own try/catch; failure empties only the card); `CFG.named`; new `renderPlayerCard(name)` placed **before** `function renderPlayersTab(` (the slice `renderPlayersTab` → `// deep links` must not contain `lowpart/showLow/lowgroup` — test 771–793); pure helpers `pickNight(nights, G)`, `capItems(items, named)` (≤ 3 Watch, ≥ 1 Good), `oneThing(items)`, `perBossRows(lists, name, cols)`, `consistencySeries(...)` in the card-components block (quickjs-tested); only `h2`/`h3` (test 600–604). `dash/static/dash.css`: card layout tweaks only. Tests appended to `tests/test_players_tab.py`: quickjs iteration over **every** fixture label building the card HTML from the fixture payloads (exit criterion "the card renders for every player") — do this by evaluating the pure helpers with the inflated fixture payload JSON from Python; `capItems` rules; named flag adds the same-spec line; no `<h4`.

**Payload impact.** None.

**DoD.** pytest + quickjs green; `test_heading_levels_never_skip`, `test_density_limits_at_call_sites`, `test_boss_tab_headings_normalised` still pass.

**Dependencies / concurrency.** After T3, T5, T7. Wave 3, concurrent with T8 (no file overlap: T8 is Python + `tests/test_rollups.py`).

### T8 — Public team strip, alphabetical roster, named RL rollups, Home prep callout (opus)

**Goal.** Design P1.8 + P1.9 in Python (static, Q10). **User-visible result (public build):** Players tab opens with a team strip without names (prep compliance %, avoidable hits/min alive this night vs previous, share of first deaths with no defensive, interrupts per pull, "pick your name in the toolbar to see your card" + the JS "Show my card" button), then the roster table **sorted by name** (secondary pulls) without the first-death-rate sort; Home gains one anonymous "Preparation" insight (flask/food/rune compliance over player-pulls, trend vs previous night). **Named build only:** a "Raid lead" section: R1 "Who needs help with what" (one row per raider: role, top Watch items of the latest night with number + baseline, sorted by level then score), R2 prep misses with names, R3 avoidable trend per night + top 5 abilities + who, R5 first deaths without defensive (share per night + names), R7 interrupts per pull per player (reduced, see §3), R8 tank pair table (am, amw, mit, dtps side by side per night), R9 gear readiness (ilvl min/median/max, players with gaps + their gaps); roster table keeps the first-death sort.

**Files.** New `dash/rollups.py` (`rollups_named(bosses, ordered, pm_by_key, sev, gear_report, cols) -> str`, every table via `table()`); `dash/players.py` 1–59: `players_tab(bosses, avoidable_cfg, mode="anonymous", pm_by_key=None, sev=None, gear=None)`; team strip via `kpis()`; `player_table_lowpart` sort key at line 41 becomes `(name.lower(), -pulls)` unless `mode == "named"`; `dash/page.py` 115–116 passes `mode`, `pm_by_key`, `sev`, `gear` (T3 computed them; refactor into one `players_block` dict if cleaner); `dash/home.py` `insights()` 107–292: add the prep-compliance insight after 201–212 (anonymous: rates only); add `rollups.py` to the no-hex list in `tests/test_dashboard.py` 531–538 (**coordinate:** T8 appends one filename to that tuple — the only `test_dashboard.py` edit in wave 3; T6 does not touch that file). New `tests/test_rollups.py`.

**Metric definitions.** Reuse the severity block and pm vectors; prep compliance = share of player-pulls with flask ∧ food (∧ rune reported separately); avoidable/min alive = Σavh / Σalv·60 over all non-tank players per night; no new formulas.

**Payload impact.** None (static HTML; the named section adds ≈ 20–40 KB HTML to the private build only).

**Tests.** `test_rollups.py`: anonymous build — no participant name in `#static_tabPlayers` outside the roster table rows (regex like `test_home_anonymous_names_nobody` 360–366 applied to the strip and the absence of `<h2>Raid lead`), roster rows alphabetical; named build — `Raid lead` section present with R1 rows sorted by level then score, R8 has both fixture tanks, R9 lists ilvl; Home has the prep insight and `test_home_anonymous_names_nobody` still passes; heading levels never skip.

**DoD.** pytest green; fixture build HTML < 1.5 MB (test 58–85).

**Dependencies / concurrency.** After T3 (needs `pm_by_key`, `sev`, `gear` plumbing) and T4. Wave 3 with T6.

### T9 — Verification and docs (opus)

**Goal.** Design P1.V + P1.D. Run `venv/bin/python -m pytest -q`, the quickjs syntax command, write the fixture dashboard (`dashboards/verify_p1.html`, e.g. by a small pytest that calls `build_html(bosses, _args(callouts="named"))` and the anonymous twin), headless-Firefox captures of `verify_p1.html#tabPlayers?player=Ixavior` (tank) and `?player=Gigaspinning` (healer) at 1440 and 390 px using the delayed-`load` copy from `docs/plans/2026-09-24-dashboard-redesign.md`; payload size table (fixture before/after per pull; the two real dashboards' numbers from §0 as the reference); then `docs/CHANGES_<date>.md`, `CLAUDE.md` §2 (analysis/, rollups.py, configs), §5 (new pull keys), §7 (Players tab card, payload keys `pm/pmcols/wc/av`, Players block), §8-style section for `tank_mitigation.json`/`gear_checks.json`, §10 (quickjs marker blocks), §11; design doc §6.10/§7.4/§8 Phase-1 table marked done with the deviations of §3 below.

**Then a final review (fable)** of the whole diff against the acceptance criteria (design "Phase exit criteria" row 1) and privacy rules.

## 2. Waves

| Wave | Tasks (parallel) | File ownership (no overlaps inside a wave) |
|---|---|---|
| 1 | **T1** (fable) · **T2** (opus) · **T4** (fable) · **T5** (opus) | T1: `analysis/{__init__,wipe,mitigation,player_metrics}.py`, `collect_data.py`, `build_dashboard.py`, `config/tank_mitigation*.json`, `tests/test_player_metrics.py`, `tests/test_mitigation.py`, `tests/test_collect_offline.py` · T2: `analysis/gear.py`, `config/gear_checks*.json`, `tests/test_gear.py` · T4: `analysis/severity.py`, `tests/test_severity.py` · T5: `dash/static/dash.js`, `dash/static/dash.css`, `tests/test_dashboard.py` |
| 2 | **T3** (opus) · **T7** (opus) | T3: `dash/payload.py`, `dash/page.py`, `tests/test_dashboard.py` · T7: `dash/static/dash.js`, `tests/test_players_tab.py` (new) |
| 3 | **T6** (opus + fable review) · **T8** (opus) | T6: `dash/static/dash.js`, `dash/static/dash.css`, `tests/test_players_tab.py` · T8: `dash/rollups.py` (new), `dash/players.py`, `dash/home.py`, `dash/page.py`, `tests/test_rollups.py` (new), one-line edit in `tests/test_dashboard.py` (no-hex list) |
| 4 | **T9** (opus), then final review (fable) | docs, `dashboards/verify_p1.html` |

Rationale: `dash.js` is one 1,144-line IIFE and `collect_data.py` one module; two agents editing either on the same working tree would clobber each other, so each wave has exactly one owner per file. T4 takes `cols` as an argument so it needs no import from T1 and can run in wave 1; T3 wires the three analysis modules together. 9 tasks + review.

## 3. What Phase 0 / the current code changes about the design's Phase 1

1. **`ish` (E9, R7) is not computable.** P0.7 found the Interrupts table lists only spells that were interrupted at least once, so "interruptible casts" has no denominator. Drop `ish` from `PM_COLS` (23 columns, Contract A) and reduce R7 to interrupts per pull per player; a pull-level listed-cast coverage would need a new `collect_data` read and is left out of Phase 1.
2. **`wipe_called_s` is never set** (0 of 201 wipes) → Contract B's death-cascade heuristic, emitted as `wc`, with the rule stated on the card. (WCL's `wipeCutoff` events argument is a death *count*, not usable without knowing it.)
3. **`deaths[i].ds` (death save) dropped:** `deathSaveAbility` appears on no cached Deaths row; `killingBlow` itself is missing on 4 of 5 deaths in fixture fight 7, so `av` must fall back to the recap share (it does).
4. **Pre-pot cannot drive a Watch:** WCL returns no pre-pull events (CLAUDE.md §11), so `prepot` is Note-only; `prep` (flask/food/rune) carries the Watch.
5. **Gear slot list in §6.5 is wrong for Midnight** (head/shoulder enchants exist, back/wrist do not) → roster-majority rule with override (T2).
6. **Block counts dropped:** no `blocked` key and no hitType 4/5 in any cached event; dodge/parry/miss stay in the digest only (not in `PM_COLS`).
7. **D5 (top spells share) deferred:** the pull dict does not carry `abilities[]`; emitting top-8 per player would cost ≈ 1.3 KB base64 per pull (half the Phase-1 budget). Deferred to Phase 3.
8. **T7 (tank death recap AM state) is cheap** (recap rows already in the payload) and is included in T3 instead of waiting.
9. Already done by Phase 0, nothing to build: spec table/roles (`spec_ids`, `SUPPORT_SPECS`, `cfg` script), fixture fields (`buffs/mitigated/hitType`, gear, overheal, abilities top 8), pagination. `dd/hd` ilvl is already in the pull dict (`e["ilvl"]`, `player_tables_from_bundle` 869) — payload only.
10. §6.9 proposed computing `pm` from "bundle rows + events" in one pure function; the raw events live only inside `collect()`, so the split is: `collect_data` stores a small per-player digest (Contract C), `dash/payload.py` assembles the vector. `analysis/wipe.py` and `analysis/mitigation.py` must not import `collect_data`/`dash` (import cycle: `dash.common` imports `collect_data`).
11. The design's `sev` estimate (≈ 15 KB) is low for a 66-player, 8-night build (≈ 55 KB base64); still far inside the budget.

## 4. Owner decisions — DEFAULTS ADOPTED by the orchestrator on 2026-10-01

1. Drop the per-player interrupt share (`ish`/E9) for Phase 1 — **drop**.
2. Post-wipe cutoff constants (≥ 3 deaths, gaps ≤ 10 s, ending ≤ 20 s before the pull ends; the cascade's first death still counts) — **as pinned**.
3. D5 top-spells share — **defer to Phase 3**.
4. `tank_mitigation.json` ids are TWW-era guesses except Demon Spikes 203819 (verified); the owner reviews them against `data/tank_buffs_seen.json` after the first real build — **ship the list, validate at build time**.
5. `am` and `dtk` ignore `avoidable.json` — **accept the two documented deviations**.

## 5. Privacy — what is visible only in `--callouts named`

Public Discord build: nothing per-name renders until a name is chosen in the toolbar (card behind the filter); comparisons are own history, role median / co-tank, bracket percentile (kills), fixed bands; ≤ 3 Watch and ≥ 1 Good on the card; Players tab unfiltered = team strip without names + roster table sorted by name; Home gets only the anonymous prep-compliance insight (test `test_home_anonymous_names_nobody` extended to the Players strip). The payload necessarily contains every name's `pm`/`sev` (names are already in `parts`/`dt`); the public rules are enforced at render time via `cfg.named = false`. **Named build only:** R1 "who needs help with what", R2/R3/R5/R9 names, R8 tank pair table, the first-death-rate roster sort, the same-spec comparison line and "rank among role" on the card, uncapped Watch lists. The named HTML is never posted to Discord (unchanged policy).

### Critical Files for Implementation
- collect_data.py (`get_damage_events` 1269–1319, `player_tables_from_bundle` 837–873, `get_parses` 1395–1420, pull dict 1670–1704)
- dash/payload.py (`_death_payload` 73–84, `pull_payload` 109–176)
- dash/static/dash.js (helper marker blocks 50–145 / 157–220, `playerFocus` 834–892, `renderPlayersTab` 1079–1122, deep links 1124–1133)
- dash/page.py (`build_html` 74–214; Players panel 115–116; `cfg` script 150)
- dash/players.py and dash/home.py (`insights()` 107–292, named gating 117–118)
