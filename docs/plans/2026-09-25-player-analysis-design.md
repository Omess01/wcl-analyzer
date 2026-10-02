# Per-player combat analysis — design proposal and roadmap

> **Status:** proposal, 2026-09-25. Nothing in this document is implemented. It exists so the user can strike assumptions,
> pick between options (§9) and approve phases; approved phases are then turned into implementation plans
> (`superpowers:writing-plans` format) and executed by sub-agents per `CLAUDE.md` §0.
>
> **Inputs** (persisted copies, read them for the evidence behind any claim here):
> `docs/research/2026-09-25-player-analysis/00-brief.md` (the brief) · `01-codebase-inventory.md` (what the code does, with
> `file:line`) · `02-wowanalyzer.md` · `03-simulationcraft.md` · `04-wcl-api.md` · `05-insight-catalogue.md`. Every `file:line`
> below comes from `01`; every URL from `02`–`05`. Where the research left something unverified it is marked **[unverified]**
> and a Phase 0 task measures it.
>
> Tag legend (house style): `[ADDED]` `[CHANGED]` `[FIXED]` `[REMOVED]` `[DECISION]` `[CAVEAT]` `[TODO]`, plus `ASSUMPTION` for
> readings of the user's intent that the user has not confirmed. Effort (sub-agent-days): **S** = 0.5–1, **M** = 2–4, **L** = 5–10,
> **S/M** = 1–2, **M/L** = 4–6; every phase total is the sum of its task rows (arithmetic under the §0 phase table).
> Model routing per `CLAUDE.md` §0: `fable` = design / hard logic / review, `opus` = routine implementation, tests, docs.

> `[CHANGED 2026-09-25]` Revised after a design review (45 findings, 1 blocker on effort totals; all applied):
> `docs/reviews/REVIEW_2026-09-25-player-analysis-design.md`. The user decisions are now **Q1–Q10**; D1–D10 are DPS feature ids (§4.2).

---

## 0. Summary (one page)

**What we build.** A per-player view of the dashboard: a raider selects their name and sees, for the nights in the build, how
they played — deaths and whether a defensive was used, avoidable damage, preparation, active time, throughput consistency,
cooldown usage, and one thing to work on — compared first with their own earlier nights, then with the role median in the
roster, then (kills only) with WCL's same-spec bracket percentile. Healers get overheal, mana curve and healing-cooldown usage;
tanks get active-mitigation-at-hit, mitigated share and a co-tank comparison. The raid lead gets the same numbers rolled up
("who needs help with what", prep compliance, cooldown and defensive usage, healer cooldown coverage) in the existing
`--callouts named` build. The public Discord build shows per-player cards only behind the Player filter and never a
ranked roster (the roster table is sorted by name).

**Recommended architecture in five sentences.** (1) Phase 1 computes every metric that the cache already holds — `activeTime`,
`overheal`, `itemLevel`, `specID`, gear, `bracketPercent`, per-spell damage, the `mitigated`/`hitType` fields and the `buffs` aura
string (on ≈ 86 % of damage-taken events, `04` §2: 20,032 of 23,184 sampled) — into a compact per-player-per-pull vector in the
payload, with **zero new API calls**. (2) Phase 2 adds one whole-fight Casts query per pull (estimated ≈ 0.6–1 MB and 1–2 pages per
pull, from a cast rate measured in pre-death windows — `04` §6; likely a low estimate), healer casts with `includeResources` for mana, and a filtered
Buffs query for a short list of tracked auras, all batched with aliases and cached per fight like today's bundles. (3) The
cooldown / GCD / charges knowledge that WCL does not expose comes from a **spell oracle** generated offline from
SimulationCraft's `SpellDataDump` into `data/spell_oracle.json` (no binary, no vendored data), which makes cast efficiency,
downtime and "defensive was available at death" work for all 40 specs including healers. (4) Per-spec hand-written knowledge is
limited to five small `config/*.json` files in Phases 1–3 (tank active-mitigation auras, raid cooldowns/externals, defensives by id,
tank busters per boss, gear checks; + `simc.json` in Phase 4) following the `avoidable.json` workflow. (5) SimC simulations (expected casts/min, buff uptime, sim-vs-actual
trend) are an **opt-in Phase 4** behind a `simc` binary, degrade gracefully, and are never required by tests.

**Phases.**

| Phase | What ships (user-visible) | New data | Effort (sub-agent-days) | Risk |
|---|---|---|---|---|
| 0 Hygiene | Correct externals (Buffs `targetID` leak fixed), pagination on every alias, filter as variable, `rateLimitData` logging + rate-limit wait/stop, spec table from `specID`, `wipeCalledTime` in the fight list, fixture recorder keeps gear/talents, one live-probe report | none (probe: ~10–15 calls) | 7.5–15 (7–14 without the optional P0.9) ¹ | low |
| 1 Mine the cache | Per-player card on the Players tab (KPI tiles with own-history deltas, consistency small multiples, deaths report card, prep streak, avoidable vs role median, active time, bracket %ile, ilvl + gear gaps, healer overheal, tank AM-at-hit / mitigated / co-tank), RL rollups in the named build | none | 17.5–33 ¹ | low–medium (payload ≈ +0.15 MB/month) |
| 2 Casts + oracle | Cooldown usage with mini-timelines, downtime / cancelled casts, defensive ready-or-used at **every** death, healer mana curve and healing-CD efficiency, tank defensive efficiency | Casts (≈ 1–2 pages/pull, estimated), healer casts, filtered Buffs; oracle JSON | 25–48 ¹ | medium (GCD model accuracy; point cost unknown until P0 measures; archived reports cannot be back-filled) |
| 3 Role depth + RL | Tank-buster check per boss, healer CD coverage vs raid damage intake, dispel latency, per-spell overheal, healer mana efficiency and non-healing time, externals given, tank self-healing, tracked-cooldown buff uptime, healing-gap team note, talent build vs roster, persistent per-player history, night digest | per-healer (and per-tank) Healing tables, filtered Debuffs, per-phase DamageDone (optional) | 21.5–43 (19.5–39 without the optional P3.5) ¹ | medium (per-boss curation) |
| 4 SimC (opt-in) | Sim-expected casts/min and buff uptime vs actual; sim-vs-actual DPS as own trend | `simc` binary, weekly batch | 7–14 ¹ | medium–high (Linux build, misleading numbers) |

¹ Totals are the sums of the task rows in §8 using S = 0.5–1, M = 2–4, L = 5–10, S/M = 1–2, M/L = 4–6; the low end assumes no
fable re-work. Phase 0 (11 rows): 9 S (P0.1–P0.3, P0.6–P0.9, P0.V, P0.D) = 4.5–9 + 1 M (P0.4) = 2–4 + 1 S/M (P0.5) = 1–2 → **7.5–15**;
without the optional P0.9 → 7–14. Phase 1 (12 rows): 5 M (P1.1, P1.2, P1.5a, P1.6, P1.8) = 10–20 + 5 S (P1.3, P1.4, P1.9, P1.V, P1.D)
= 2.5–5 + 1 S/M (P1.7) = 1–2 + 1 M/L (P1.5b) = 4–6 → **17.5–33**. Phase 2 (16 rows): 5 M (P2.1–P2.4, P2.8a) = 10–20 + 1 L (P2.5) = 5–10
+ 1 M/L (P2.6) = 4–6 + 3 S/M (P2.7, P2.8b, P2.8d) = 3–6 + 6 S (P2.8c, P2.9, P2.10, P2.11, P2.V, P2.D) = 3–6 → **25–48**. Phase 3
(13 rows): 10 M (P3.1–P3.10) = 20–40 + 3 S (P3.11, P3.V, P3.D) = 1.5–3 → **21.5–43**; without the optional P3.5 → 19.5–39. Phase 4
(5 rows): 3 M (P4.2–P4.4) = 6–12 + 2 S (P4.1, P4.5) = 1–2 → **7–14**. Phases 0–3 together: **71.5–139**; with Phase 4: 78.5–153.
Contingent, not included: +1 S if the fixture report turns out to be archived (Q7).

**Ten decisions for the user (details and alternatives in §9); the five from the brief first, five new ones (Q6–Q10) below.**

| # | Question | Recommendation |
|---|---|---|
| Q1 | How much SimC? | Spell-data **oracle only** in Phase 2; per-player sims as opt-in Phase 4; no APL comparison, no stat weights. |
| Q2 | Where does the per-player view live? | Expand the **Players tab** into the card, driven by the existing global Player filter; keep the boss-tab focus block as the per-boss drill-down; no new tab. |
| Q3 | Public vs private? | Public: card behind the filter, own-history + role-median comparisons, ≤ 3 Watch + ≥ 1 Good, no ranked roster (the roster table is sorted by name). Named build: RL rollups, sorted lists, same-spec comparison. |
| Q4 | Payload strategy? | **Precomputed per-player-per-pull vectors** (small ints, `PM_COLS` §6.10) + cooldown timelines for the tracked spells (§6.10) as timestamp lists; **no raw cast streams** (they would add 6–9 MB/month). Budget: ≤ +0.7 MB per month (Phases 1–3 estimate ≈ +0.6 MB, §7.4). |
| Q5 | Which per-spec knowledge do we maintain? | Five small configs in Phases 1–3 (tank AM auras, raid CDs/externals, defensives, tank busters per boss, gear checks; + `simc.json` in Phase 4) + two generated tables (spec table, spell oracle). No rotational lists, DoT rules or resource rules. |
| Q6 | Persist per-player history across builds? | **Yes**, `data/player_history.json` in Phase 3. |
| Q7 | Re-record the test fixtures once, after P0.6 and P0.8? | **Yes**, before Phase 1 (the user runs `make_fixtures.py`; network). |
| Q8 | Whole-fight casts for which pulls? | **All** pulls; revisit after P0.7 measures points and pages. |
| Q9 | How to get `simc` (only if Q1 includes sims)? | Build from source; Docker as fallback. |
| Q10 | May the named-build rollups be static (not follow the toolbar filters)? | **Yes** for Phases 1–3; they reuse the precomputed severities. |

---

## 1. Intent and assumptions

Condensed from `00-brief.md`. Rows marked **ASSUMPTION** are the orchestrator's reading (or, where noted, this designer's);
strike any that are wrong.

| # | What the user said (condensed) | What was assumed |
|---|---|---|
| 1 | "Plan the next phase of upgrades." "Tailor the feedback and combat analysis of each player down." | ASSUMPTION: from raid/boss aggregates to **individual** feedback a raider reads about themselves after a night. |
| 2 | Inspirations: SimulationCraft, WoWAnalyzer. | ASSUMPTION: the user wants the *kind* of insight those tools give (cooldown usage, downtime, defensives, preparation, sim baselines), not a port of either. |
| 3 | "Consider different possibilities on how to implement them in this dashboard." | ASSUMPTION: options must stay inside the current architecture (Python build → single HTML, WCL v2, per-fight cache); no server, no new runtime. |
| 4 | Audiences: RL and GM **and** DPS, healers, tanks. | ASSUMPTION: the RL/GM view is a roll-up of the player view, in the existing `named` build. |
| 5 | Deliverable now: analysis, feature sets, roadmap. No implementation. | — |
| 6 | (not said) | ASSUMPTION (brief): success = "that matched what I felt in the fight" and the RL reads WCL by hand less. |
| 7 | (not said) | ASSUMPTION (brief): no per-spec maintainer; prefer spec-agnostic → data-derived → small config, in that order. |
| 8 | (not said) | ASSUMPTION (brief): Heroic progression guild, ~20 raiders, 2 main nights; feedback helps a Heroic raider improve, not chase 99th-percentile parses. |
| 9 | (not said) | ASSUMPTION (brief): tone motivating, never shaming; the public artefact must not become a wall of shame; the `named` build carries sharper content. |
| 10 | (not said) | ASSUMPTION (brief): the user is a Havoc DH, so DPS is the natural first slice, but healers and tanks are first-class. |
| 11 | (not said) | ASSUMPTION (designer): "own history" = the earlier raid nights **inside the build's date range** (about a month). A persistent cross-build history file is proposed as an option (Q6), not assumed. |
| 12 | (not said) | ASSUMPTION (designer): the user can run `python tests/make_fixtures.py` once per phase that changes query text (needs network + `.env`; Claude Code cannot read `.env`). |
| 13 | (not said) | ASSUMPTION (designer): Docker is not installed; a `simc` binary would be built from source if Q1 includes sims. |

---

## 2. What exists today and what is already in the cache but unused

### 2.1 Per-player data in a pull dict today (`collect_data.py:1376-1406`)

| Field | Granularity | Source | Notes |
|---|---|---|---|
| `participants {label: class}` | per pull | FIGHTS_QUERY + `Labeller` (`598-622`) | label = bare name or `Name-Realm` |
| `deaths[i]` | every death | Deaths table (`698-712`) + damage-taken events (`1145-1171`) | `recap` (own damage in the 6 s window), `top_contributor`, `biggest_hit`, `one_shot`; **first death only** gets `casts`, `defensives`, `externals` (`940-979`) |
| `damage_taken[i]` | per (player, ability) per pull | DAMAGE_TAKEN_QUERY (`986-1036`, `1043-1109`) | `hits` (instances, 2.5 s gap), `ticks`, `amount`, `unmitigated`, `avoided`, `times`, `sources` |
| `damage_done[i]`, `healing_done[i]` | per player per pull | bundle tables (`715-744`) | `total`, `active_seconds`, `ilvl` (read at `740`, **not in the payload**, `dash/payload.py:146-147`), `spec` parsed from the `icon` string (`731-733`) |
| `parses {label: {dps, hps}}` | kills only | RANKINGS_QUERY (`1112-1135`) | only `rankPercent` kept |
| `interrupts`, `dispels` | per pull | bundle tables (`747-770`) | counts only |
| `consumables`, `consumable_use` | per pull | CombatantInfo auras (`773-790`) + filtered casts (`855-879`) | flask/food/rune/prepot booleans; potion/healthstone counts |

Players tab today: static Python table (`dash/players.py:8-59`: pulls, bosses, first death, wipe-starter %, avoidable hits/pull,
"what killed them") and a JS dynamic view under the global filters (`dash/static/dash.js:953-990`: per-boss rows for a
selected player). Boss-tab focus block (`dash.js:708-766`): KPI cards vs "regulars", hits-per-ability chart vs raid average,
the player's deaths table.

### 2.2 Already cached, not read (the free riches)

| Data | Where in the cache | Read today? | What it enables | Phase |
|---|---|---|---|---|
| `combatantinfo.specID` | bundle `cinfo` | no (spec comes from the table `icon`, `731-733`) | authoritative spec/role per pull; 93 of 5,121 player-pulls have no spec today | 0 |
| `combatantinfo.talentTree [{id, rank, nodeID}]` (~3.3 KB/player) | bundle `cinfo` | no | talent build vs roster majority; SimC profiles (ids = SimC TalentIDs, verified in `03` §2) | 3 / 4 |
| `combatantinfo.gear [{id, itemLevel, permanentEnchant, gems, bonusIDs}]` (~3.2 KB/player) | bundle `cinfo` | no | ilvl per slot, missing enchant/gem, low-ilvl slot; SimC profiles | 1 / 4 |
| `combatantinfo` stats (`hasteSpell/Melee/Ranged`, crit, mastery, vers, …) | bundle `cinfo` | no | GCD length from haste (Phase 2 downtime) | 2 |
| `combatantinfo.auras[].source/stacks` | bundle `cinfo` | name only | raid-buff coverage at pull (who cast Bloodlust/PI pre-pull) | 3 |
| table row `activeTime` | bundle `damage`/`healing` | yes, as `active_seconds` | **active time %** per player per pull (WCL's own definition) | 1 |
| table row `abilities [{guid, name, total}]` | bundle | no | per-spell damage/healing breakdown per player per pull | 1 |
| table row `targets [{name, total}]` | bundle | no | damage to adds vs boss (target selection) | 3 |
| table row `overheal` (Healing) | bundle | no | healer overheal % per pull | 1 |
| table row `itemLevel`, `gear` (with names) | bundle | ilvl only | ilvl column; enchant names for the gear check | 1 |
| table row `given`/`taken`, `totalRDPS*` | bundle | no | Augmentation support attribution (out of scope, noted); support specs get a `support` flag in the spec table and are excluded from role medians (§6.3) | — |
| Deaths table `killingBlow` present in 81 % of rows; `deathSaveAbility` | bundle `deaths` | `killingBlow.name` only | "death save" flag | 1 |
| damage event `buffs` ("157128.1235108.") | DAMAGE_TAKEN pages (all 337); present on ≈ 86 % of events (`04` §2: 20,032 of 23,184 sampled) | **no** (`1002-1033` read 10 keys) | **active mitigation up at the moment of each hit** — tank AM uptime-at-hit with zero new calls | 1 |
| damage event `mitigated`, `unmitigatedAmount`, `blocked`, `hitType` (0 miss · 1 hit · 2 crit · 4/5 blocked · 7 dodge · 8 parry · 10 immune) | DAMAGE_TAKEN pages | `unmitigatedAmount` only | mitigated share, block/dodge/parry counts | 1 |
| Interrupts table `spellsBegun / spellsCompleted / spellsInterrupted / missedCasts` per enemy spell | bundle `interrupts` | player `total` only | **interrupt share denominator** (interruptible casts) without enemy-cast events — **[unverified]**: the research shows the shape only (`01` §1.2, `04` §3); whether never-interrupted enemy spells are listed and `spellsBegun` = interruptible casts is checked by P0.7 | 1 |
| rankings `bracketPercent`, `spec`, `bracketData`; fight-level `speed`, `execution` | RANKINGS cache | `rankPercent` only | same-ilvl-bracket percentile ("gear or play?"), spec on kills | 1 |
| `masterData.abilities[].type` (school bitmask, inferred) | ABILITIES cache | no | physical/magic split of damage taken | 3 |

### 2.3 Not fetched at all

Whole-fight casts (only the dying player's 6 s window and the consumable ids), any player's buffs/debuffs over the fight, healing
events, damage-done events, resources (`includeResources`, `resourcechange`), summons, threat, enemy casts, `rateLimitData`
(`01` §1.2 "Not fetched at all today"). WCL exposes **no cooldown, GCD, charge or cast-time data anywhere in its schema** (`04` §7).

### 2.4 Budget baselines (measured, `01` §4 and §10)

- Newest build: 1.85 MB file; 16 boss payloads = 1.29 MB base64 (69.9 % of the file) = 0.97 MB gzip = 5.45 MB raw JSON; **5.9 KB
  base64 per pull**, ~253 B per player-pull; `dt` 46.8 % and `deaths` 33.2 % of raw JSON. Headroom to Discord's 10 MB: ~8.1 MB.
- Cache: 962 MB (632 MB current-version); per fight ≈ 573 KB bundle + 2.11 MB damage-taken pages. ~34 HTTP requests for a new
  15-pull report today.
- Roster in the build: 66 distinct players, 32 spec names, player-pulls dps 3,657 / healer 937 / tank 434.

---

## 3. What the reference tools teach us

### 3.1 WoWAnalyzer (`02`)

**Portable vs not.** WoWAnalyzer analyses one player × one fight through a module graph (normalizers → analyzers) —
https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/core/CombatLogParser.tsx. Its **Foundation layer**
(https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/interface/guide/foundation/FoundationGuide.tsx) is spec-agnostic
given an ability table: active time, cancelled casts, melee uptime, cast efficiency of cooldowns/defensives, healer mana curve,
preparation, death recap with defensive readiness. Everything spec-aware (rotation/APL checks, per-cast checklists such as Eye
Beam → Furious Gaze or Tranquility ramps, DoT snapshotting, per-item analyzers) is hand-written TypeScript per spec — Havoc alone
has ~60 spec modules and 8 normalizers — and is `MaintainedFull` for only 17 of 40 specs, 14 of them at patch 12.1 (`02` §6).
`[DECISION]` We re-implement the Foundation ideas in Python; we do not port spec modules.

**Thresholds we adopt** (all `[verified]` in `02` §1–§2; presented in the dashboard as Good / Watch / Note, never as "Fail"):

| Metric | Source module | Thresholds | Our use |
|---|---|---|---|
| Downtime % | `AlwaysBeCasting` https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/modules/AlwaysBeCasting.tsx | 5 / 10 / 15 % (Perfect ≤ 0 / Good ≤ 5 / Ok ≤ 10 / Fail); small gaps (100–2,250 ms) 6 / 8 / 10 per min | Note bands when own history is thin; role median first |
| Healer non-healing time / downtime | `AlwaysBeCastingHealing` | 30 / 40 / 45 % non-healing; downtime 20 / 35 % | Phase 3 (needs heal-spell classification) |
| Cast efficiency | `CastEfficiency` https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/modules/CastEfficiency.tsx | recommended 0.80; average issue −0.05; major −0.15; suppressed when `casts == maxCasts`; **time-based** (`timeUnavailable / fightDuration`) | Phase 2 cooldown engine uses the same formula |
| Cancelled casts | `CancelledCasts` | 2 / 5 / 15 % | Phase 2 |
| Mana left at end | `ManaValues` | 10 / 20 / 30 % | Phase 2 healer card |
| Melee uptime | `MeleeUptimeAnalyzer` | ≤ 0.98 / 0.90 / 0.80 | optional, Phase 3 |
| Debuff uptime | `DebuffUptime` | 0.85 / 0.80 / 0.75 | only for curated ids (Phase 3) |
| AoE efficiency | `AoESpellEfficiency` | 0.95 / 0.90 / 0.80 targets | not planned (needs per-spell targets) |
| Resource at cap | Havoc 15 / 20 / 25 %; Prot Paladin 10 / 15 / 20 % | per spec | **not planned** (deep spec logic) |
| Time dead | `DeathTracker` | any time dead = major | deaths card |
| GCD | `GlobalCooldown` | `max(min(base, 750), base/(1+haste))`; model "inaccurate" at ≥ 2 errors/min → statistic hidden | same guard in Phase 2; `base` = the spell's own GCD from the oracle (P2.6) |

`[CAVEAT]` `05` §2a quotes Havoc downtime thresholds of 15 / 25 / 35 % from the `master` branch's Havoc `AlwaysBeCasting.tsx`, while
`02` reads 5 / 10 / 15 % from the shared module on `midnight`. Different branches, different modules. We adopt the shared 5 / 10 / 15 %
as *Note* bands only; the primary comparison is the roster role median.

**Normalizer pitfalls we must handle** (`02` §3, all verified):

| # | Pitfall | Our handling |
|---|---|---|
| 1 | `cast` events include fake casts (WCL `fake: true` on 98 of 863 cached casts, `04` §2) and spell ticks/bolts; WoWA keeps a ~120-id `CASTS_THAT_ARENT_CASTS` list | drop `fake`, drop spell id 1 (Melee) except for melee uptime, drop casts whose oracle entry has no GCD and no cooldown (passives/procs) |
| 2 | buffs already up at the pull have no `applybuff`; unmatched `removebuff`/`refreshbuff`/`*stack` mean "up since start" | read `combatantinfo.auras` (already done for consumables) and treat unmatched removes as open-from-start |
| 3 | pre-pot = potion buff present in `combatantinfo.auras` at start; potion casts are in the event stream but not in the Casts table | already handled (`PREPOT_BEFORE_MS`); keep the filtered-casts approach |
| 4 | channels are delimited inconsistently (buff, next cast, empower); cancelled cast = `begincast` without `cast` | cast-time spells from `begincast→cast`; channels: oracle attribute "Is Channelled" + `Duration` gives an expected channel length; no per-spell table |
| 5 | haste changes during the fight (Bloodlust, procs) shift GCD and hasted cooldowns; WoWA hides downtime when its GCD model errs ≥ 2/min | pull haste from `combatantinfo`; apply the tracked Bloodlust-family buff only (Phase 2 `tbuffs`); suppress downtime when overlapping GCDs exceed 2/min |
| 6 | `classResources.amount` can be stale within 150 ms | take the last cast per 150 ms bucket for the mana curve |
| 7 | cooldown reductions and resets are not in the log or game files ("CDR is still manual and probably always will be", https://github.com/WoWAnalyzer/WoWAnalyzer/wiki/Abilities-Generator-(WIP)) | present cast efficiency with a tolerance band and mark abilities whose oracle entry lists modifiers as "≈" |
| 8 | WoWA tracks buffs only by/to the selected player | our raid-wide bookkeeping is per pull for all players anyway |
| 9 | friendly fire / self damage must be excluded from damage done | already excluded in damage taken (`1063-1064`); damage-done totals come from WCL tables |
| 10 | any cast/heal/damage after `death` = implicit resurrection | alive-time denominator: time to first death in Phase 1; Phase 2 detects resurrection from later casts |
| 11 | WoWA never aggregates across pulls or players | our medians/deltas across pulls, nights and the roster are our own problem (JS side, §7.3) |

### 3.2 SimulationCraft (`03`)

| Can give | Cannot give |
|---|---|
| **Spell-data oracle for every spec incl. healers**: `SpellDataDump/<class>.txt` (13 files ≈ 17.8 MB) + `nonclass.txt` with `Cooldown`, `Charges` (+ recharge), `Category` + `Category Cooldown` (shared cooldowns, with the list of modifying talents), `GCD`, `Cast Time`, `Duration`, `Attributes` (Is Channelled, Haste Affects Duration), `Category Flags` (Reset Cooldown on Encounter End), `Affecting Spells`, `Replaces` — https://github.com/simulationcraft/simc/tree/midnight/SpellDataDump | exact per-talent cooldown numbers (modifiers live in the talent's block), haste-scaled cooldowns as one number, proc-based resets |
| Talent names and tree index from `engine/dbc/generated/trait_data.inc` (3,435 rows); **WCL `talentTree[].id` = SimC TalentID**, verified on 7 sampled pairs | race, professions, crafted stats (not in WCL) |
| Sim baselines for **DPS and tanks**: `stats[].num_executes.mean` → expected casts/min, `buffs[].uptime`, `collected_data.dps.mean`, `waiting_time`, `action_sequence` (opener) via `json2=` — https://raw.githubusercontent.com/simulationcraft/simc/midnight/engine/report/json/report_json.cpp | **healers**: only `druid_restoration.simc` has an APL; no Holy/Disc/HPal/RSham/MW/Pres baseline |
| Patchwerk / CastingPatchwerk / LightMovement fight styles, `max_time` pinned to the pull length, `desired_targets` | movement, adds, deaths, intermissions, real raid buffs, externals; community reports 88–98 % of sim on single target and 65–75 % on mechanics-heavy bosses, no authoritative ratio (https://us.forums.blizzard.com/en/wow/t/how-you-sim-vs-your-actual-dps/1669898) |
| Profile from WCL data: gear lines `id=,bonus_id=,gem_id=,enchant_id=,ilevel=`; `class_talents=/spec_talents=/hero_talents=/omnium_talents=` by `tree_index` — https://raw.githubusercontent.com/wiki/simulationcraft/simc/Characters.md | APL comparison against real casts (needs SimC's expression engine over hidden state) — **infeasible**, `03` §5 |
| Linux: build from source (`cmake -DBUILD_GUI=OFF -DSC_NO_NETWORKING=ON`, https://github.com/simulationcraft/simc/wiki/HowToBuild) or Docker `simulationcraftorg/simc` (29.3 MB) — https://hub.docker.com/r/simulationcraftorg/simc | AUR packages are BfA-era / GUI-pinned; no release binaries for Linux |

`[DECISION]` The oracle is the spine of Phase 2 (covers all roles, no binary). Sims are Phase 4, opt-in, batch-weekly, per
(player, gear+talent hash, fight-length bucket), never per pull. Sim-vs-actual is shown only as the player's own trend.

### 3.3 The insight catalogue (`05`)

Role metrics and thresholds are folded into §4. The presentation patterns that fit a static single-file dashboard (`05` §4):
performance box row (one box per pull/death), stacked outcome bar, cast-efficiency panel with a minimal cast/CD timeline, uptime
bar, insight card with a headline number and expandable who/when, problem list sorted by severity, "vs baseline" bullet bar,
per-pull small multiples, heat strip. Not fitting: map/replay, full event timelines for 20 players.

**Three tone rules** (`05` §5, adopted verbatim as design constraints):
1. **Public = team and self; named comparison only in the private build.** Per-player cards only behind the Player filter, comparisons
   as *you vs your own history* and *you vs role median*; sorted rankings, parse-coloured rosters and "worst N" only in `--callouts named`.
2. **Positive, usage-centred wording with a "not a big deal" tier.** Good / Watch / Note; each item states the number, the baseline and
   one actionable sentence; good items are shown; nothing is red without text.
3. **Own history before peers, kills before wipes, one thing per night.** Order: this night vs last nights → role median → WCL bracket
   percentile (kills) → external aggregates (never named). Cap the public card at ~3 Watch items, always ≥ 1 Good.

Sources behind the rules: Wipefest's audit framing (https://hrothmar.com/guides/how-to-become-a-better-raider-using-wipefest-gg/),
WoWAnalyzer's `Perfect/Good/Ok/Fail` (https://github.com/WoWAnalyzer/WoWAnalyzer/blob/master/src/parser/ui/QualitativePerformance.ts),
raid-leadership advice ("praise in public, criticize in private", https://worldofmatticus.com/raid-leading-101-3-important-communication-tips/;
"judge median not peak", https://raider.io/fr/news/556-raiding-101-performance-management), and the counter-examples
(https://www.warcraftinsights.com/ public "cleanest raiders first" tables; https://www.carried.io/ "Does he kick or Netflix?").

**Traceability to the catalogue's 15-item shortlist** (`05` §6). Three deviations are deliberate and marked.

| Rank | Shortlist insight | Feature IDs here | Phase | Note |
|---|---|---|---|---|
| 1 | Personal card behind the Player filter (KPI tiles with own-history deltas) | §7.3 blocks 1–4; E1, E4–E7 | 1 | — |
| 2 | Consistency small multiples | E7 | 1 | — |
| 3 | Death report card; defensives/externals for all deaths | E1–E3, E10 | 1 → 2 | all deaths need the Phase 2 casts |
| 4 | Avoidable damage vs raid median + trend | E4, R3 | 1 | — |
| 5 | Preparation streaks | E5, R2 | 1 | — |
| 6 | Active time % vs role median | E6 | 1 (→ 2 GCD-based) | — |
| 7 | Bracket percentile alongside `rankPercent` | E8, H10 | 1 | — |
| 8 | Major-cooldown usage vs possible | E14, D2, D3, H3, T9 | 2 | `[DECISION]` the oracle replaces the shortlist's "cooldown inferred from minimum cast spacing" heuristic: spacing fails for charges, held cooldowns and short fights, and the oracle costs one script run |
| 9 | Interrupt share vs interruptible casts | E9, R7 | 1 | `[DECISION]` denominator from the cached Interrupts table (`spellsBegun/Completed/Interrupted`), so no enemy-cast query is needed (semantics **[unverified]**, P0.7) |
| 10 | Healer overheal per spell vs same-role median | H1 | 1 (total) → 3 (per spell) | per-spell shape **[unverified]** |
| 11 | Healing-CD coverage vs raid damage intake | H2, R6 | 3 | — |
| 12 | Dispel latency | H6 | 3 | — |
| 13 | Co-tank comparison | T2, T3, R8 | 1 | — |
| 14 | Tank-buster defensive check | T4 | 3 | — |
| 15 | Active-mitigation uptime | T1 | **1** | `[DECISION]` from the `buffs` string on cached damage events instead of the Buffs table — free, and "at hit" is the more useful denominator |

### 3.4 Licence notes

| Source | Licence | What we may do | What we must not do |
|---|---|---|---|
| WoWAnalyzer | AGPL-3.0 (`02` §5) | learn what is measured and which thresholds are used; re-implement in our own Python/JS | copy ability tables, spell lists, normalizer code or explanatory sentences verbatim (copyleft would attach to the tool; quoting text into the HTML copies expression) |
| SimulationCraft binary | GPL-3.0 (`03` §1) | run it as a subprocess and read `json2` output ("arm's length", https://www.gnu.org/licenses/gpl-faq.html) | ship the binary with the tool (moot: single user) |
| SimC `SpellDataDump/*.txt`, `*.inc` | generated from Blizzard CDN data inside a GPL repo (`03` §1) | generate `data/spell_oracle.json` **locally** from a shallow checkout; commit only the generator and a small test subset | vendor the dumps or the full oracle into the repo |
| Wipefest legacy code | AGPL | ideas only | — |

`[CAVEAT]` These are the research agents' readings of the licences (`02` §5 "inferred, not legal advice"; `03` §1 "Not legal advice"),
not legal advice.

---

## 4. Feature catalogue by audience

Column key — **Data**: cached-free (no new call) · new-cheap (≤ 1 KB-sized alias per fight) · new-moderate (~1 page per fight) ·
needs simc. **Spec**: none · generated (spec table / oracle) · config (one of the five small files of Phases 1–3, §6.5) · per-spec (rejected).
**Baseline**: own = own earlier nights/pulls · role = roster role median · spec = same spec in roster · bracket = WCL `bracketPercent`
(kills) · sim. **Build**: public = Discord build behind the Player filter · named = RL build only · both.
Voice column = what the card says, in the dashboard's Good/Watch/Note voice.

### 4.1 Everyone

| ID | What the player sees | Computation | Data | Spec | Baseline | Build | Effort | Phase |
|---|---|---|---|---|---|---|---|---|
| E1 | "Good — you were the first death in 0 of 12 pulls (raid median 1)." Deaths per pull attended. | first-death share and deaths/pull from `deaths[]` + `participants` (`player_stats`, `dash/common.py:384-404`); deaths after the wipe call are not counted (§6.10) | cached-free | none | own, role | public | S | 1 |
| E2 | "Watch — 2 of your 3 deaths were to avoidable damage (Rattler Slam)." | death is avoidable when the killing blow or ≥ 50 % of `recap` window damage comes from `avoidable.json` abilities (Warcraft Insights convention, https://www.warcraftinsights.com/) | cached-free | boss list (exists) | own | public | S | 1 |
| E3 | "Note — no defensive was cast in the 6 s before 3 of 5 deaths; Blur was available at 2 of them." | Phase 1: `defensives` on the first death (exists, `attach_casts` `940-979`); Phase 2: every death, plus *available* from the cooldown engine | cached-free → new-moderate | config (defensives ids) + generated | own, role share | public | S → M | 1 → 2 |
| E4 | "Good — 1.1 avoidable hits per minute alive, raid median 1.4; down from 1.8 last week." | `damage_taken[].hits` for avoidable abilities ÷ minutes alive (time to first death); hits after the wipe call excluded (§6.10); trend over nights | cached-free | boss list | role, own | public | S | 1 |
| E5 | "Watch — pre-pot missing on 5 of 12 pulls; flask/food/rune on every pull." Streak counter. | `consumables` + `consumable_use` per pull (`773-790`, `855-879`) | cached-free | none | expectation = every pull | public (own) / named (roster) | S | 1 |
| E6 | "Note — active 86 % of the fight; DPS median 91 %." | `active_seconds / duration` from the table `activeTime` (WCL's activity); Phase 2 adds GCD-based downtime and small gaps/min | cached-free → new-moderate | none → generated (GCD flags) | role, own; WoWA 5/10/15 % as Note | public | S → M | 1 → 2 |
| E7 | "Your active DPS on Ula'tek: median 1.62 M, best 1.81 M, spread ±6 %." Small multiples per boss with own median line and last-nights band. | per-pull `total / active_seconds`; median, best, IQR per boss and per night | cached-free | none | own | public | S | 1 |
| E8 | "Kills: parse 58, same-ilvl bracket 71 → play is ahead of gear." | `rankPercent` + `bracketPercent` + `spec` from the cached rankings JSON (`04` §4) | cached-free | none | bracket | public (small tiles) | S | 1 |
| E9 | "Good — you interrupted 4 of the 9 interruptible casts you could reach; the raid stopped 7 of 9." | player `total` ÷ `spellsBegun` (or `spellsCompleted + spellsInterrupted`) from the Interrupts table (`04` §3); semantics **[unverified]**, P0.7 | cached-free | none | raid share | public | S | 1 |
| E10 | "Externals received before deaths: Pain Suppression ×1 (Healer A)." Externals *given* appear in the healer/tank rollup. | first death: exists (`externals`, after the P0 leak fix); all deaths and whole fight: filtered Buffs for the externals list | cached-free → new-cheap | config (raid_cooldowns.json externals) | own | public (received) / named (given) | M | 1 → 2 |
| E11 | "Note — 4 % of your casts were cancelled (WoWA: 2 % good, 5 % watch)." | `begincast` without matching `cast` ÷ all cast starts, fake casts excluded | new-moderate | none | own, WoWA bands | public | S | 2 |
| E12 | "ilvl 289 (raid 285–294). Gear: cloak has no enchant; ring 2 has an empty socket." | `gear[]` from `combatantinfo` and table rows: min/avg ilvl, enchantable slots without `permanentEnchant`, gems missing where `bonusIDs`/sockets indicate one | cached-free | config (gear_checks.json: enchantable slots, socket rules) | own | public (own card) / named (roster list) | S | 1 |
| E13 | "Your talent build differs from the other 2 Havoc builds in 3 nodes." | `talentTree` ids grouped by spec within the roster; names from the oracle's trait table; later: vs top-100 aggregates via `characterRankings` (never named) | cached-free (roster) / new (top logs, later) | generated (trait table) | spec (roster) | named / opt-in | M | 3 (roster) · later (top logs) |
| E14 | "Cooldowns: Metamorphosis 2 of 3 possible (83 %), Eye Beam 9 of 10, The Hunt 3 of 3." with a mini-timeline per spell | casts per tracked spell vs possible casts from oracle cooldown/charges over the fight (WoWA time-based efficiency, D2); tracked spells chosen per player per build (§6.10) | new-moderate | generated (oracle) | own, WoWA 80 % | public | M | 2 |
| E15 | "Second potion used inside Bloodlust on 6 of 9 pulls." | potion casts (have) vs Bloodlust-family buff window from tracked Buffs | new-cheap | config (raid_cooldowns.json lust ids) | own, raid share | public | S | 2 |

### 4.2 DPS

| ID | What the player sees | Computation | Data | Spec | Baseline | Build | Effort | Phase |
|---|---|---|---|---|---|---|---|---|
| D1 | "Active DPS 1.62 M; DPS role median 1.48 M; the other Havoc: 1.70 M (named build only)." Bullet bar. | `total / active_seconds` vs role median per pull; same-spec only in named; support specs (Augmentation) get a Note instead ("support spec — WCL's rDPS is not in the payload", §6.3) | cached-free | none | role (public), spec (named) | both | S | 1 |
| D2 | Cast-efficiency panel: per tracked cooldown "% + n of m casts" and a minimal cast/CD timeline with "could have fit one more" segments | E14 engine; WoWA 0.80 / −0.05 / −0.15 thresholds; possible = `charges + floor((fight_s − t0)/cd_s)` with `t0` = pull start (pre-pull casts inferred from `combatantinfo.auras`, `02` §3 `PrePullCooldowns`), capped at the WoWA `floor(rawMaxCasts) + 1` (`02` §1); efficiency = WoWA time-based `timeUnavailable / fightDuration`; ±1 cast tolerance | new-moderate | generated | own, WoWA | public | M | 2 |
| D3 | "3 of 4 possible Metamorphosis; last one held for the final 62 s." | integer form of D2 for the tracked spells with cd ≥ 90 s (§6.10); "held at end" = available for > 0.8 × cd before fight end | new-moderate | generated | own | public | S (with D2) | 2 |
| D4 | "Downtime 9 % (median 6 %); 7 small gaps per minute." | GCD union from casts + oracle GCD flags + pull haste; small gaps 100–2,250 ms; suppressed when the GCD model overlaps > 2/min | new-moderate | generated | own, role; WoWA 5/10/15 | public | M | 2 |
| D5 | "Top spells this night: Chaos Strike 31 % (your median 29 %), Eye Beam 18 %, …" | `abilities[]` share per pull vs own median share | cached-free | none | own | public | S | 1 |
| D6 | "Phase 2: 1.2 M active DPS (role median 1.4 M); phases 1 and 3 on median." | per-phase `table(dataType: DamageDone, startTime, endTime)` per fight; or approximate from casts (Phase 2) | new-cheap (3–5 small aliases/fight) | none | role, own | public | M | 3 |
| D7 | "42 % of your damage on Sszorak went to adds (raid DPS 35 %)." | `targets[]` from the cached table rows; adds = NPC names ≠ boss | cached-free | none (NPC names automatic) | role | public | S/M | 3 |
| D8 | "Sim expects 2.9 Eye Beams/min at your gear; you cast 2.4 (Δ −0.5)." | SimC `stats[].num_executes.mean` ÷ fight minutes vs actual casts; top 6–8 abilities by `portion_aps` + cooldowns | needs simc | generated (profile) | sim | public (own only) | M | 4 |
| D9 | "You reached 81 % of your Patchwerk sim on Ula'tek kills (last month 76 %)." | `collected_data.dps.mean` vs WCL active DPS on kills; **own trend only**, Patchwerk caveat in the UI | needs simc | generated | sim (own trend) | public (own) | S (with D8) | 4 |
| D10 | "Metamorphosis buff uptime 27 % (sim 31 %)." | cast timestamps of the player's tracked cooldowns from the casts entry + oracle `Duration` of the triggered buff (oracle `Triggered By`/same id); no buff query, so the `tbuffs` key stays config-only (§6.1) | new-moderate (Phase 2 casts) | generated | own, sim (P4) | public | M | 3 |

Deferred (`[DECISION]`, `05` §6 "Deferred"): resource waste/capping (needs builder/spender semantics per spec), buff/proc uptime for
rotational buffs per spec, DoT clipping, APL/rotation checks.

### 4.3 Healer

| ID | What the player sees | Computation | Data | Spec | Baseline | Build | Effort | Phase |
|---|---|---|---|---|---|---|---|---|
| H1 | "Overheal 31 % (healer median 27 %; 15–25 % is typical, 35 %+ worth a look)." Phase 3: per spell. | table `overheal ÷ (total + overheal)` per pull; per spell needs `table(Healing, sourceID)` per healer **[unverified shape]** | cached-free → new-cheap (4–5 aliases/fight) | none | role, own; community bands (https://wowcoach.gg/blog/how-to-read-healer-logs-wow) | public | S → M | 1 → 3 |
| H2 | "Your Tranquility landed on the 2 biggest raid-damage spikes; the 3rd spike (4:12) had no raid CD." Damage-intake line with CD markers for a selected pull. | per-second raid damage taken (cached events) + raid-CD casts (Phase 2 casts) matched to spikes (top-N seconds) | cached-free + new-moderate | config (raid_cooldowns.json healing) | none (descriptive) | public (own CDs) / named (team) | M/L | 3 |
| H3 | "Revival 2 of 3 possible; Spirit Link 3 of 3." | E14 engine restricted to `raid_cooldowns.json` healing ids + the player's long cooldowns | new-moderate | config + generated | own, WoWA 80 % | public | M (shared with E14) | 2 |
| H4 | Mana heat strip per pull: "Ended kills at 8 % mana (WoWA: leave ≤ 10 %); dipped to 4 % at 3:40 on the wipe." | healer casts with `includeResources` → mana % over time (30 buckets), value at 25/50/75 %, end, minimum | new-moderate (healers only, ~0.3–0.5 MB/pull **[estimate]**) | none | own; WoWA 10/20/30 % left | public | M | 2 |
| H5 | "Healing per 1k mana: 12.4 (your median 11.9)." | effective healing ÷ mana spent (from H4 casts) | with H4 | none | own | public | S | 3 |
| H6 | "Dispels: 6, median 1.8 s after application (team 2.4 s)." | filtered Debuffs `applydebuff` for ids seen in the Dispels table, paired with dispel timestamps | new-cheap | none (ids from the Dispels table) | team, own; 2–3 s community line | public | M | 3 |
| H7 | Team note: "3 deaths this night were to sustained unavoidable damage with no external — a healing gap, not a player error." | recap window: ≥ 80 % non-avoidable, ≥ 3 hits, no external/defensive | cached-free | boss list | none | named (team) / public (team sentence) | M | 3 |
| H8 | "Externals given: Pain Suppression ×4, Power Infusion ×3 (to A, B)." Absorb healing share. | tracked Buffs with `sourceID` = healer; Healing table `abilities[]` for absorb spells | new-cheap | config (externals) | own | named | M | 3 |
| H9 | "Damage done 0.21 M active DPS — 14 % of a DPS's (a quarter is excellent, per community guides)." | `damage_done` for healers | cached-free | none | own | public (Note) | S | 1 |
| H10 | "HPS parse 62, bracket 70." | as E8 with `hps` | cached-free | none | bracket | public | S | 1 |
| H11 | "Non-healing time 38 % (WoWA: 30 % good, 45 % watch)." | GCD union split into heal-producing spells (spells appearing in the Healing table `abilities[]`) vs others | new-moderate | none (derived) | own; WoWA 30/40/45 | public | M | 3 |

### 4.4 Tank

| ID | What the player sees | Computation | Data | Spec | Baseline | Build | Effort | Phase |
|---|---|---|---|---|---|---|---|---|
| T1 | "Shield of the Righteous was up for 91 % of the melee hits you took (last week 84 %)." | share of non-tick, non-avoidable damage events on the tank whose `buffs` string contains an AM aura id for the tank's spec; weighted by `unmitigatedAmount` as a second number; events without a `buffs` key are excluded (§6.10 `am`) | cached-free | config (tank_mitigation.json: AM ids per tank spec) | own; community 80 % line | public | M | 1 |
| T2 | Paired bars per pull: "DTPS while alive: you 142 k, co-tank 118 k." | `damage_taken` totals ÷ alive time per tank per pull | cached-free | none | co-tank | public | S | 1 |
| T3 | "Mitigated 58 % of raw damage (absorbed 11 %, blocked 9 %)." | `(Σ mitigated + Σ absorbed) ÷ Σ unmitigatedAmount` over events (`amount` excludes absorbs and overkill, so `unmitigatedAmount − amount` would count overkill as mitigation, `04` §2); blocked/dodged/parried counts from `hitType` | cached-free | none | co-tank, own | public | S | 1 |
| T4 | Per tank-buster glyph row: "Ardent Defender or SotR active on 7 of 9 Rattler Slams; 2 taken bare (pulls 4, 11)." | tank-buster hits (config per boss) × `buffs` string ∋ AM or major CD ids; Phase 2 adds "was a CD available" | cached-free (+ casts for availability) | config (tankbusters.json per boss + tank_mitigation.json major ids) | own | public (own) / named (both tanks) | L | 3 |
| T5 | "Swaps at 2 stacks on 8 of 9 applications; one at 3." | boss debuff stack events (filtered Debuffs) + taunt casts | new-cheap | config (per-boss debuff, swap count) | rule | named / public | L | later |
| T6 | "Self-healing covered 22 % of damage taken; externals 3." | Healing table by target for the tank **[unverified shape]**; tracked Buffs | new-cheap | config (externals) | own | public | M | 3 |
| T7 | Tank death recap with AM/CD state at each of the last hits | E1–E3 + `buffs` string on the recap events | cached-free | config (AM ids) | own | public | S | 1 |
| T8 | "Tank DPS 0.9 M (other Vengeance in roster 1.0 M)." | `damage_done`; rankings for tanks exist | cached-free | none | spec | named | S | 1 |
| T9 | Major defensive cast efficiency with timeline (as D2 for defensives) | E14 engine on the tank's DEFENSIVE-category spells (oracle category / defensives config) | new-moderate | generated + config | own, WoWA 80 % | public | M (with E14) | 2 |

### 4.5 Raid lead / GM rollups (named build unless stated)

| ID | What the RL sees | Computation | Data | Spec | Baseline | Build | Effort | Phase |
|---|---|---|---|---|---|---|---|---|
| R1 | "Who needs help with what": one row per raider, their top Watch items this night with the number and the pull links, sorted by severity score (§7.3: deviation ÷ tolerance × share of pulls affected) | the per-player severity engine (§7.3) run for everyone, sorted by level then score; Python-rendered | cached-free (grows with phases) | — | own, role | named | M | 1 |
| R2 | Prep compliance: "flask 100 %, food 97 %, rune 88 %, pre-pot 71 % of player-pulls; misses: …" | `consumables` over player-pulls; names only in named | cached-free | none | 100 % | public (rates) / named (names) | S | 1 |
| R3 | Avoidable-hits trend per night (hits/min alive, raid) + top 5 abilities + who (named) | E4 aggregated; Home already has parts (`dash/home.py:124-212`) | cached-free | boss list | own nights | public (trend) / named (who) | S | 1 |
| R4 | Cooldown usage compliance: "14 of 17 DPS/healers ≥ 80 % on their major cooldowns; below: …" | E14 per player → share; names in named | new-moderate | generated | WoWA 80 % | public (share) / named (names) | M | 2 |
| R5 | Defensive usage: "First deaths with no defensive cast: 41 % (last week 55 %); all deaths (Phase 2): 37 %." | E3 aggregated | cached-free → new-moderate | config | own nights | public (share) / named (names) | S | 1 → 2 |
| R6 | Healer CD coverage map per pull: raid damage per second with every raid CD marker, gaps flagged | H2 team view | cached-free + new-moderate | config | — | named (public: team sentence) | M | 3 |
| R7 | Interrupt coverage: "Interruptible casts completed 3 of 27 this night; missed on pulls 5, 9." | Interrupts table `spellsCompleted` vs `spellsInterrupted` per pull | cached-free | none | 0 completed | public | S | 1 |
| R8 | Tank pair summary per night: T1–T3 side by side | T1–T3 | cached-free | config | co-tank | named (public: own) | S | 1 |
| R9 | Gear readiness: ilvl distribution, count of enchant/gem gaps; names in named | E12 aggregated | cached-free | config | roster | public (counts) / named (names) | S | 1 |
| R10 | Talent diversity per spec: majority build, outliers | E13 | cached-free | generated | roster | named | M | 3 |
| R11 | Night digest: one Good and one Watch per role, anonymous on Home, named in the RL build, and as `post_discord.py --summary` text (Roadmap 3.4) | severity engine → templates | cached-free | — | own nights | both | M | 3 |
| R12 | Cross-build trends per player (8 weeks): deaths/pull, avoidable/min, active %, prep, cooldown efficiency | `data/player_history.json` merged at build (like `mplus_history.json`) | none | — | own | both | M | 3 (Q6) |

---

## 5. Architecture options and recommendation

Three cumulative options. Numbers use `01` §4 (5.9 KB base64 per pull, 8.1 MB headroom) and `04` §6 (measured event volumes).

| | **A. Mine the cache** | **B. A + casts pipeline + spell oracle** | **C. B + SimC baselines** |
|---|---|---|---|
| What it is | Per-player metrics precomputed in Python from data already cached; new payload section; per-player card | Whole-fight casts per pull (batched aliases, paginated), filtered Buffs for tracked auras, healer casts with `includeResources`; `data/spell_oracle.json` from SimC dumps → generic cast efficiency, downtime, defensive readiness at every death, tank AM/defensive timelines | Optional `simc` binary (`SIMC_BIN` → `which` → Docker) generating profiles from `combatantinfo` (gear + talent ids, race from config) → expected casts/min and buff uptime per ability; sim-vs-actual as own trend; weekly batch |
| Value: everyone | E1–E2, E4–E9, E12: deaths, avoidable, prep, active %, consistency, bracket %ile, interrupts, gear | + E3 (all deaths), E11, E14, E15 | unchanged |
| Value: DPS | D1, D5 | + D2–D4 (the "why is my DPS low" set) | + D8–D10 (personalised expected numbers; the ceiling for DPS feedback without per-spec code) |
| Value: healer | H1 (total), H9, H10 | + H3, H4 (mana), later H2/H6/H11 | **none** (no healer APLs) |
| Value: tank | T1–T3, T7, T8 — already strong thanks to the `buffs` string | + T9, T4 availability | + expected casts for tank rotational/defensive spells (medium) |
| Value: RL | R1–R3, R5, R7–R9 | + R4, R5 (all deaths), R6 groundwork | + "is the raid near its sim ceiling" (low; misleading on mechanics bosses) |
| API cost per 15-pull report | **0** new requests (34 today) | ≈ +10 requests: casts `ceil(15/3)=5` + healer casts `ceil(15/5)=3` + tracked buffs `ceil(15/10)=2` (+ up to 15 single-fight follow-ups if casts need 2 pages, §6.2); points **[unverified]**, measured in Phase 0 | as B (sims are local) |
| API cost per month (200 pulls) | 0 | ≈ +130 requests; ~700 today for a full rebuild (`04` §6) | as B |
| Cache growth per month | 0 | raw ≈ 0.6–1 MB casts (estimate, `04` §6) + ~0.3–0.5 MB healer casts + ≤ 30 KB buffs per pull ≈ **200–300 MB raw**; stored compact (`[t, src, tgt, aid, type, fake]`) **≈ 65–90 MB** (§6.8) — versus ~640 MB/month today | + `data/sim/` ≈ 20–60 JSON files/week × ~0.5–2 MB |
| Payload growth per month | ≈ **+0.15 MB** (per-player vectors, severities, ilvl, bracket, avoidable-death flags; §7.4) | ≈ **+0.4 MB** (timelines for the tracked spells, downtime columns, per-death readiness, mana buckets; §7.4) → file ≈ 2.4 MB | ≈ +20 KB (per-player Δ tables) |
| Maintenance | two small new configs (`tank_mitigation.json`, `gear_checks.json`); the fixture recorder must keep gear/`buffs` | oracle regenerated per patch (one script run); the five small configs reviewed per tier/patch; GCD model needs a sanity guard | + simc rebuild per patch (5–25 min CI-equivalent), profile generator drift (bonus ids, omnium talents, hero-tree selection node **[unverified]**), race config per player |
| Risks | fixture re-record needs network (and a non-archived fixture report); `buffs` string is absent on ≈ 14 % of damage events and probably a subset of auras (inferred, `04` §2) → hits without it are excluded, validate against Phase 2 buff events | point cost unknown; filtered pagination surprises (`04` S18); haste buffs mis-time hasted cooldowns; talents that add charges/CDR make "possible casts" too high → tolerance band and "≈" marker; casts cannot be back-filled for archived reports (`04` §5) | misleading sim-vs-actual on movement bosses; Linux build burden; Devourer/experimental specs; crafted-stat decoding |
| Tests | offline, existing fixtures + slimmer update | offline: compact casts entries in fixtures; oracle subset fixture; synthetic tests for the cooldown/GCD engines | offline: committed trimmed `json2` fixture; never invoke `simc`; `skipif(not SIMC_BIN)` |

**Recommendation.** `[DECISION]` Target **B**, staged as Phase 1 (= A) then Phase 2, with **C as an opt-in Phase 4**. Reasons: (1) A alone
already delivers most of the everyone/tank/RL value at zero API cost and is the only phase startable next session; (2) B is what makes
the DPS and healer verticals real, and the oracle is the only route that helps healers (SimC cannot); (3) casts are the cheapest
**whole-fight** event type WCL has (≈ 1–2 pages per pull, estimated; `04` §6 classes them "moderate", behind tables and filtered
queries) while the expensive ones (unfiltered buffs, damage done, healing, `All`) are avoided by filtering server-side and reading tables; (4) C's value is concentrated on DPS, depends on a binary and a fight model that the community itself
treats as a ceiling, and its main output (expected casts/min) is a refinement of what B already shows from the oracle; it belongs behind
a switch. The evidence does not support skipping B for C: without the casts pipeline, C has nothing to compare against.

---

## 6. Data and pipeline design (recommended option B; C's additions in §8 Phase 4)

### 6.1 New query kinds

All follow the existing "separate batched per-fight entry" pattern (`01` §8(a) pattern 2; `get_consumable_casts` `812-852`):
aliased parts inside `query X($code: String!, $filter: String) { reportData { report(code: $code) { … } } }`, `get_entry(key, refresh=needs_refresh(f))`
/ `put_entry`, `pool.map` over batches, `count_api_call`, `_warn_once` + `{}` on `WCLError`, called from the per-report block after the
bundles (`1333-1354`). `BUNDLE_VERSION` stays **v3** (no re-download of 221 bundles; Phase 1 reads more of what v3 already stores).

| Entry (key) | Alias per fight | Args | Batch | Est. size / fight | Phase |
|---|---|---|---|---|---|
| `casts:v1:<code>:<fid>` | `casts_<fid>: events(dataType: Casts, fightIDs: [fid], hostilityType: Friendlies, startTime, endTime, filterExpression: $castFilter, limit: 10000) { data nextPageTimestamp }` with `$castFilter = "source.type = 'player' AND type IN ('cast','begincast')"` | whole fight | **3** fights/request (revisit after P0.7) (≈ 2–3 MB per response; keeps under `WCL_TIMEOUT_SECONDS`) | raw ≈ 0.6–1 MB, 5,000–8,500 events, 1–2 pages — **estimated** from a cast rate (0.72 casts/s/player) measured in 6.3 s pre-death windows (`04` §6; likely a low estimate); stored compact ≈ 0.25–0.4 MB | 2 |
| `hcasts:v1:<code>:<fid>` | `hcasts_<fid>: events(dataType: Casts, fightIDs, startTime, endTime, includeResources: true, filterExpression: $healerFilter, limit: 10000) { data nextPageTimestamp }` with `"source.role = 'healer' AND type = 'cast'"` | whole fight, healers only | 5 | ≈ 1,000 casts × ~400 B ≈ 0.3–0.5 MB **[estimate]**; stored as `[t, src, mana, maxmana]` ≈ 20 KB | 2 |
| `tbuffs:v1:<code>:<fid>:<idhash>` | `tbuffs_<fid>: events(dataType: Buffs, fightIDs, startTime, endTime, filterExpression: $buffFilter, limit: 10000) { data nextPageTimestamp }` with `"ability.id IN (…)"` — **no `targetID` argument** (the leak, `04` §1); filter `targetID` client-side | whole fight; the id list = **config ids only** (`raid_cooldowns.json`, `tank_mitigation.json`, `defensives.json`: Bloodlust family, Power Infusion, externals, tank AM + major CDs), so `<idhash>` does not churn with the roster; tracked-cooldown buff uptimes (D10) use the casts entry plus oracle `Duration` instead | 10 | ≤ 30 KB (AM auras re-apply every few seconds on two tanks) | 2 |
| `heal:v1:<code>:<fid>:<actor>` | `heal_<fid>_<aid>: table(dataType: Healing, fightIDs, sourceID: <aid>)` | per healer (+ the two tanks for T6, P3.10) | 5 fights (× 4–5 healers + 2 tanks = ≤ 35 aliases) | ≈ 20 KB each **[unverified shape]** | 3 |
| `debuffs:v1:<code>:<fid>:<idhash>` | `debuffs_<fid>: events(dataType: Debuffs, fightIDs, startTime, endTime, filterExpression: $debuffFilter, limit: 10000) { data nextPageTimestamp }` with ids = `guid`s of spells in the Dispels table + tank-swap debuffs from config | whole fight | 10 | 1–10 KB | 3 |
| `ddph:v1:<code>:<fid>:<phase>` (optional) | `dd_<fid>_<n>: table(dataType: DamageDone, fightIDs, startTime: <phase start>, endTime: <phase end>)` | per phase | 5 fights | ≈ 146 KB × phases | 3 (D6) |

Not added: unfiltered Buffs (3–5 pages/pull), DamageDone/Healing events (4–11 pages), `All` (13–26 pages) — `04` §6.

### 6.2 Mechanics: pagination, filters, rate limits

- **`nextPageTimestamp` on every alias** (fix for `01` §2 "silently truncated"). Rule: request it everywhere; if an alias returns a
  non-null value, run a single-fight follow-up loop for that fight (`startTime = nextPageTimestamp`) until null, concatenate, then cache.
  Log `page 2+ needed for <code>:<fid>` so the batch size can be tuned. Applies retroactively to `cinfo`, `cons`, `casts1` (no version
  bump: cached entries were far below their limits, `04` §1).
- **`filterExpression` as a GraphQL variable** (`$filter: String`) instead of the inlined double-quoted literal at `collect_data.py:829-833`,
  which breaks as soon as a name comparison adds quotes (`04` §6). Entry keys stay unchanged (they hash ids, not the query text).
- **Timestamps**: event `timestamp` is report-relative; inside a filter expression `timestamp` is fight-relative (`04` §1). Never put
  time bounds in the expression; use `startTime`/`endTime` arguments.
- **`rateLimitData`** (`04` §5): appended at **send time** in `wcl_client.run_query` (never in the query text handed to `cached_query`,
  or every sha1 key would change). Per request: log `kind, Δpoints, pointsSpentThisHour/limitPerHour`. Run end: "points this run: X of
  Y per hour; resets in Z s". **Wait-or-stop**: on HTTP 429 or a GraphQL "rate limit" error, keep the existing short backoff first (429s
  also arrive in bursts while points remain, `04` §5 S22); escalate to the `pointsResetIn` wait only when `pointsSpentThisHour ≥ 0.95 ×
  limitPerHour`: if `pointsResetIn` ≤ `WCL_RATE_WAIT_MAX` (default 900 s) sleep and retry once, else raise `WCLRateLimited` which `collect()` catches after saving `report_meta.json`: console
  "stopped: hourly points exhausted, resets in N s; finished fights are cached, re-run later", exit code 3. `--refresh` refuses to start
  when `pointsSpentThisHour > 0.8 × limitPerHour`. Log any `Retry-After` / `X-RateLimit-*` headers once **[unverified they exist]**.
  `WCL_RATE_WAIT_MAX` is a new `.env` key: the user adds it to `.env` and `.env.example` by hand (Claude Code cannot edit either,
  `CLAUDE.md` §3); the default applies when it is absent.
- **Point cost is unpublished** (`04` §5): the only documented clue is that `phases` does not double-charge fight data; wowsims claims
  "1 point per subquery"; a community measurement gives "a raid night about 3, a character about 6". Phase 0 measures Δpoints per query
  kind and decides the FIGHTS+PHASES merge (§6.7).

### 6.3 Spec table

`specs.py` (code, not config — it is game data): `SPECS = {specID: (class, spec, role, simc_token, support)}` for the 40 retail specs (incl.
Demon Hunter Devourer, `02` §6), e.g. `62: ("Mage", "Arcane", "dps", "arcane", False)`, `577: ("DemonHunter", "Havoc", "dps", "havoc", False)`
(specIDs seen in the cache: 62, 253, 262, 577 — `04` §2; tank and healer ids come from Blizzard's public list, **[unverified]** until
first seen). `support` is `True` for Augmentation (40 player-pulls in the newest build, `01` §4): `[DECISION]` support specs are excluded
from role medians; D1/E7 render for them as a Note ("support spec — WCL's rDPS is not in the payload").
`pull_specs()` (`dash/common.py:147-156`) prefers `cinfo.specID`, falls back to
the `icon` string. The JS `TANKS`/`HEALERS` sets (`dash.js:44-46`) are emitted from the same table as a small `<script id='cfg'>` JSON
(the pattern Roadmap 4.6 wants) so the two renderers cannot drift. Test: every spec name seen in the build (32) resolves; every
`specID` in the fixture cinfo resolves. `[CAVEAT]` specIDs verified in the cache only for those 32 names; the rest come from Blizzard's
public list and are checked when they first appear (console warning "unknown specID").

### 6.4 Spell oracle generator (`tools/build_spell_oracle.py`)

- **Source**: shallow sparse checkout of `simulationcraft/simc` branch `midnight` (`git clone --depth 1 --filter=blob:none --sparse` +
  `git sparse-checkout set SpellDataDump engine/dbc/generated`), path from `SIMC_SRC` in `.env` or `data/simc-src/` by default. No binary.
  `SIMC_SRC` is a new `.env` key the user adds by hand (and to `.env.example`); the default needs none.
- **Parse** `SpellDataDump/<class>.txt` (13) + `nonclass.txt` (consumables, trinkets, encounter spells) — block format `Label : value`
  (`03` §4) — and `engine/dbc/generated/trait_data.inc` (talent names, `tree_index`, `id_trait_node_entry`, `id_node`, `id_spell`) and
  `sc_scale_data.inc` (rating per 1 % for haste/crit/mastery/vers, the values WoWA also takes from SimC, `02` §1) and `item_scaling.inc`
  (the diminishing-return brackets for those ratings, `02` §1); both paths under `engine/dbc/generated/` are **[unverified]** (`02` cites
  the file names only).
- **Emit** `data/spell_oracle.json` restricted to ids that matter: every `abilityGameID` in the cached casts entries ∪ `data/abilities_seen.json`
  ∪ all ids in `config/*.json`. Per id: `name, class, cd_ms, charges, charge_cd_ms, category, category_cd_ms, gcd_ms, cast_ms, duration_ms,
  school, channelled (attr 34), haste_scales_duration (attr 273), reset_on_encounter_end (category flag 5), affecting [ids], replaces, triggered_by, talent {tree, row, col}`
  plus `traits {entry_id: {name, tree_index, node, spell}}` and `scale {haste_per_pct, …, dr_brackets}`. Expected size: well under 1 MB for the
  1–3k ids a raid casts (`03` §4). `data/` is git-ignored. The first oracle run can precede the first casts download (P2.1 and P2.4
  run in parallel), so the build warns "N cast ids missing from the oracle — rerun tools/build_spell_oracle.py" and treats those
  ids as untracked.
- **Consumers**: cooldown engine (D2/E14/H3/T9), GCD/downtime engine (D4/E6), defensive readiness (E3), talent names (E13/R10), potion
  and lust ids cross-check (E15), SimC profile splitter (Phase 4).
- **Without the oracle** (file missing): the casts pipeline still runs; cooldown/downtime sections render
  `empty_state("Cooldown usage", "no spell oracle found", "run tools/build_spell_oracle.py")`; everything else unaffected.
- **Tests**: committed `tests/fixtures/spell_oracle_subset.json` (the ids the fixture report casts, ~50–100 entries) + a 20-row
  `trait_data` slice + three raw dump blocks (a charge spell, a channelled spell, a category-shared spell) to test the parser.
  Licence: the subset is our own re-encoding of a few numbers, generated locally; the generator is what is committed (§3.4).

### 6.5 Config files (`config/*.json` + `*.example.json`, loaded like `consumables.json` via `_load_json`, `collect_data.py:472-477`)

| File | Content | Format | Used by | Maintenance |
|---|---|---|---|---|
| `tank_mitigation.json` | per tank spec: `am` aura ids (SotR, Ironfur, Shuffle/Stagger buff, Demon Spikes, Bone Shield, Ignore Pain/Shield Block) and `major` cooldown ids (Ardent Defender, Guardian of Ancient Kings, Barkskin, Survival Instincts, Fortifying Brew, Metamorphosis (Veng), Fiery Brand, Vampiric Blood, Dancing Rune Weapon, Icebound Fortitude, Shield Wall, Last Stand, …) | `{"Protection Paladin": {"am": [{"id": 132403, "name": "Shield of the Righteous"}], "major": [...]}, "_comment": ...}`; keyed by `"<Class> <Spec>"` from the spec table; ids preferred, `name` fallback | T1, T4, T7, T9 | 6 specs × ~5 ids; per patch; validated against the oracle (id exists, has a duration) and against `abilities_seen` |
| `raid_cooldowns.json` | `raid_healing` (Tranquility, Revival/Restoral, Spirit Link Totem, Healing Tide Totem, Power Word: Barrier, Aura Mastery, Divine Hymn, Rewind, Emerald Communion, Luminous Barrier, Apotheosis, …), `raid_defensive` (Rallying Cry, Darkness, Anti-Magic Zone, Devotion Aura), `externals` (Pain Suppression, Guardian Spirit, Ironbark, Life Cocoon, Blessing of Sacrifice, Blessing of Protection, Time Dilation, Power Infusion), `lust` (Bloodlust, Heroism, Time Warp, Primal Rage, Fury of the Aspects) | `{"raid_healing": [{"id", "name", "buff_id"?}], ...}` | H2, H3, H8, E10, E15, R6, `tbuffs` id list | ~35 ids; per expansion; `[CAVEAT]` names/ids are educated defaults for Midnight — verify against `abilities_seen` and one live buff query |
| `defensives.json` `[CHANGED]` | today: name substrings per class (`490-500`); new: `{"defensives": [{"id", "name", "class"}], "patterns": [...]}` — ids first, substring fallback kept | as today | E3, T9, readiness | migrate once; oracle validates ids |
| `tankbusters.json` | per boss: tank-buster ability names (same normalisation as `avoidable.json`, `dash/common.py:100-120`), optional `swap_debuff` + `swap_at` | `{"Ula'tek": ["Rattler Slam"], "_uncertain": [...], "_changelog": [...]}` | T4, T5 | same workflow as `avoidable.json`: `abilities_seen.json` gains a `tank_share` per ability (share of hits landing on tanks, from the existing "Who gets hit" tank pattern, `dash.js:658`) so candidates are obvious; `validate_config` warns on names that never hit anyone |
| `gear_checks.json` | enchantable slots for this expansion, slots that carry sockets (by `bonusIDs` rule or slot list), `min_ilvl_gap` for "low-ilvl slot" | `{"enchantable": ["back","chest","wrists","legs","feet","finger1","finger2","main_hand"], "socket_slots": [...], "low_slot_gap": 15}` | E12, R9 | per expansion; small |
| `simc.json` (Phase 4) | `bin` (or `.env` `SIMC_BIN`), `docker_image`, `fight_style`, `target_error`, per-player `race` overrides | `{"players": {"Omess": {"race": "blood_elf"}}, ...}` | Phase 4 | per roster change |

`validate_config` (`build_dashboard.py:59-93`) gains the new files: unknown keys, ids absent from the oracle, bosses without pulls.

### 6.6 Fixture changes (`tests/make_fixtures.py`)

- `slim()` (`55-80`) keeps, for **the first three `cinfo` players of each fight (one per role where possible)**: `gear`, `talentTree`, the stat
  block (`_CINFO_KEEP` `50` grows); for all players still `auras`, `specID`.
- Table rows keep `abilities` (top 8 by `total`), `targets`, `overheal`, `itemLevel`, `gear` (`_TABLE_DROP` `49` shrinks).
- Damage events keep `buffs`, `mitigated`, `hitType`, `blocked`, `unmitigatedAmount` (`_EVENT_KEEP` `51-52`).
- New entry shapes get a slimmer each: `casts` → `[t, src, tgt, aid, type, fake]`; `hcasts` → `[t, src, mana, maxmana]`; `tbuffs`/`debuffs`
  raw (tiny). `[DECISION]` the **production** cache stores the same compact form for casts/hcasts (cache diet, Roadmap 3.5) — one code path.
- Size budget: fixtures 4.3 MB → ≤ 6.5 MB (buffs strings ≈ +30 % on the 4 damage pages; gear/talents for 3 × 4 players ≈ +80 KB; compact
  casts ≈ +0.3 MB per pull × 4). Re-recording needs network (`01` §8(g)); the user runs it once per phase that changes query text.
- `FIGHTS_QUERY` gains `wipeCalledTime` (P0.8, §6.10) — a query-text change, recorded in the same single Phase 0 re-record.
- The fixture report must not be archived (`04` §5: events and tables of archived reports are inaccessible without a subscription);
  P0.7 checks `archiveStatus`, and if it is archived a new fixture report is picked (all fixture expectations change, +1 S task; Q7).
- `tests/conftest.py` `_no_network` (`23-25`) keeps failing loudly on any missing fixture; the offline test asserts the new keys.
- Oracle subset and SimC `json2` trimmed fixture as in §6.4 / Phase 4.

### 6.7 Phase-0 hygiene fixes (unblock everything)

| Fix | Where | Why |
|---|---|---|
| Buffs `targetID` leak: keep only `ev.targetID == actor_id` | `attach_casts`, `collect_data.py:940-979` | 19 % of the cached "buffs before first death" events have the dying player as **source**, so their own externals given to others appear as externals received (`04` §1) |
| `nextPageTimestamp` on every alias + follow-up loop | `_bundle_query` `633-643`, `get_consumable_casts` `812-852`, `get_first_death_casts` `890-937` | silent truncation; filtered queries may paginate early (`04` S18) |
| `filterExpression` via `$filter` variable | `829-833` | quoting breaks on names; needed by every new query |
| `rateLimitData` at send time + wait/stop + `--refresh` guard | `wcl_client.py:83-131`, `collect()` | client gives up after ~2 min while an exhausted budget needs up to 3,600 s (`04` §5) |
| FIGHTS + PHASES merge **if** measured Δpoints shows double charge | `85-107`, `110-126`, `cq()` | schema says phases do not double-charge when loaded with fights (`04` §5) — measure before touching; merging changes query text → fixture re-record; keep the phases fallback (`535-539`) |
| `wipeCalledTime` in `FIGHTS_QUERY`, carried into the pull dict | `85-107`, pull dict (`1376-1406`) | deaths and avoidable hits after the wipe call must not count against a player (`04` §7; Warcraft Insights excludes wipe-phase deaths, `05` E2); query-text change → part of the single fixture re-record (P0.8) |
| Spec table from `specID` | §6.3 | 1.8 % of player-pulls have no spec; per-spec configs need a stable key |
| Fixture recorder keeps gear/talents/`buffs`/abilities | §6.6 | every Phase 1 feature reads them |
| Live probe report `06-live-probe.md` | `tools/wcl_probe.py` (runs through `wcl_client`, which loads `.env` itself) | decides the **[unverified]** items: `table(Casts\|Buffs\|Summary)` shapes, `includeResources` raw key names, `playerDetails` fields, filtered pagination, 429 headers, Δpoints per query kind, whole-fight casts volume (events, bytes, pages), `archiveStatus` of the fixture and oldest reports, Interrupts-table semantics |
| `--prune-cache` (optional) | `cache.py` | 370 MB of orphaned old-version files today; Phase 2 adds ≈ 65–90 MB/month (§6.8) |

### 6.8 Per-fight byte and request estimates (Phase 2 steady state)

| Item | Per 6-min pull | Per 15-pull report | Per 200-pull month |
|---|---|---|---|
| Casts (raw / compact) | ≈ 0.6–1 MB **[estimate]** / ≈ 0.3–0.4 MB | 9–15 MB / 4.5–6 MB | 120–200 MB / 60–80 MB |
| Healer casts + resources (raw / compact) | 0.3–0.5 MB **[estimate]** / 20 KB | 4.5–7.5 MB / 0.3 MB | 60–100 MB / 4 MB |
| Tracked buffs | ≤ 30 KB | ≤ 0.45 MB | 1–6 MB |
| **Cache growth, compact (the one number used elsewhere)** | ≈ 0.32–0.45 MB | ≈ 5–7 MB | **≈ 65–90 MB** |
| Requests | — | +10 (5 casts, 3 healer casts, 2 buffs) on ~34 today; + up to 15 single-fight follow-ups if casts need 2 pages | ≈ +130 on ~450 (≈ +330 if every pull needs 2 cast pages) |
| Points | **[unverified]** | measured in Phase 0 | budget check: 3,600/h free tier |
| Follow-up pages | casts 1–2 pages **[estimate]**, P0.7 measures | logged | tune batch size if > 5 % |

### 6.9 Where computation lives

- **Python, build time** (`analysis/` package, new): `player_metrics.py` (per pull per player vector, Phase 1), `mitigation.py` (T1–T3),
  `gear.py` (E12), `cooldowns.py` (charge tracking, cast efficiency, readiness; Phase 2), `activity.py` (GCD union, downtime, cancelled;
  Phase 2), `mana.py` (H4), `severity.py` (the **only** Good/Watch/Note engine: per player × night × metric the value, baseline, level,
  score and template id → the `sev` payload block, §7.3/§7.4; the RL rollups read the same results), `oracle.py` (loader). Pure
  functions, tested with synthetic data in `tests/test_units.py` style.
- **JS, browser** (`dash.js`): aggregation across pulls/nights/bosses for the selected player under the global filters (medians and
  deltas for tiles and rows; ordering and filtering of the precomputed `sev` items, "one thing" selection — **no re-scoring in JS**),
  rendering. Pure helpers inside the quickjs marker blocks (`dash.js:49-64`, `76-139`).
- **Python, named build**: `dash/rollups.py` renders R1–R12 into the Players tab static part when `--callouts named`
  (`[CAVEAT]` static, does not follow the toolbar filters — like the Raid tab).

### 6.10 The per-player-per-pull metric vector (`PM_COLS`, the single source of truth)

`PM_COLS` is defined **here and only here**: `analysis/player_metrics.py` declares it in this order, `dash/payload.py` (P1.4) imports
it for the boss-level `pmcols`, the roundtrip test asserts equality with this list, and §7.4 refers to it. Adding a column appends,
never reorders.

```
PM_COLS (Phase 1, 24): act dps hps dth fd alv avh avm dtk dtps prep pot hs ir ds ish ilvl rp bp oh mit am amw gap
Phase 2 appends (6):   dtm sg cc ce mp hld
```

All values are small integers; percentages 0–100; trailing `null`s are popped as for `dt` rows (`dash/payload.py:129-130`), so
JS must tolerate short vectors (`01` §8(c)).

`[DECISION]` **Short pulls.** Pulls shorter than 60 s are excluded from `act/dps/hps/oh` medians, from cast efficiency and from
downtime (they still count for deaths, prep and avoidable hits); the card states the number of pulls used.

`[DECISION]` **Wipe call.** `dth`, `avh`, `avm`, `dtk` exclude events after `wipeCalledTime` when set; `fd` and `alv` are unaffected.
The card states the rule ("deaths after the wipe call are not counted"). `wipeCalledTime` is set only when the wipe was called in the
WCL Companion app (`04` §7); without it every event counts.

| Col | Meaning | Formula (from the pull dict / bundle rows / events) | Scale | `null` when |
|---|---|---|---|---|
| `act` | active time share | `active_seconds ÷ duration_seconds` | % | no table row |
| `dps` | active DPS | `damage_done.total ÷ active_seconds` | k | no damage row |
| `hps` | active HPS | `healing_done.total ÷ active_seconds` | k | no healing row |
| `dth` | deaths | count of `deaths[]` for the label, excluding deaths after `wipeCalledTime` | int | — |
| `fd` | first death | `1` if `deaths[0].player == label` | 0/1 | no deaths in the pull |
| `alv` | alive seconds | seconds to the player's first death, else `duration_seconds` (floor 1) | s | — |
| `avh` | avoidable hits | Σ `damage_taken[].hits` over `avoidable_set(boss)` minus `_ignore`, hits after `wipeCalledTime` excluded | int | boss has no avoidable list |
| `avm` | avoidable hits per minute alive | `avh ÷ (alv ÷ 60)` | ×10 | `alv` < 1 |
| `dtk` | damage taken | Σ `damage_taken[].amount` (self-inflicted excluded, as today; after `wipeCalledTime` excluded) | k | — |
| `dtps` | damage taken per second alive | `dtk ÷ alv` | ×10 k/s | — |
| `prep` | preparation bitmask | flask 1 · food 2 · rune 4 · prepot 8 · vantus 16 (+ extra aura cats × 32…) | int | `has_extras` false |
| `pot` | combat potions used | `consumable_use.combat_potion` | int | — |
| `hs` | healing potions + healthstones | `healing_potion + healthstone` | int | — |
| `ir`, `ds` | interrupts, dispels | counts | int | no extras |
| `ish` | interrupt share | `ir ÷ Σ spellsBegun` over the fight's interruptible spells (semantics **[unverified]**, P0.7) | % | no interruptible casts |
| `ilvl` | item level | table `itemLevel`, fallback mean of `cinfo.gear[].itemLevel` | int | neither |
| `rp`, `bp` | rank / bracket percentile | rankings `rankPercent`, `bracketPercent` | int | wipe, or character hidden |
| `oh` | overheal share | `overheal ÷ (total + overheal)` | % | not a healing row |
| `mit` | mitigated share | `(Σ mitigated + Σ absorbed) ÷ Σ unmitigatedAmount` over enemy hits (`amount` excludes absorbs and overkill, so `unmitigatedAmount − amount` would count overkill as mitigation, `04` §2) | % | role ≠ tank, or no events |
| `am` | AM-at-hit share | hits (non-tick, non-avoidable, enemy source) whose `buffs` ∋ an AM id ÷ such hits; events lacking the `buffs` key are excluded from numerator and denominator | % | role ≠ tank, or spec not in `tank_mitigation.json`; or events without `buffs` exceed 30 % of the tank's hits (card: "aura data incomplete") |
| `amw` | AM-at-hit, damage-weighted | same, weighted by `unmitigatedAmount` | % | as `am` |
| `gap` (P1) | gear gaps | count of missing enchants + empty sockets | int | no gear |
| `dtm` (P2) | downtime | 1 − GCD-union active share (P2.6) | % | GCD model suppressed (> 2 overlaps/min), or pull < 60 s |
| `sg` (P2) | small gaps per minute | 100–2,250 ms gaps ÷ minutes alive | ×10 | as `dtm` |
| `cc` (P2) | cancelled casts | `begincast` without `cast` ÷ cast starts, fake casts excluded | % | no cast starts |
| `ce` (P2) | cast efficiency per tracked spell | list, ×100, order = `cdt` keys (tracked spells below) | list | no tracked spell cast, or pull < 60 s |
| `mp` (P2) | mana at 25/50/75 %/end/min | from `hcasts` (P2.2) | list of 5 % | not a healer, or no resource data |
| `hld` (P2) | cooldowns held at end | count of tracked spells with cd ≥ 90 s available > 0.8 × cd before the end (D3) | int | no such spell |

Role for `mit`/`am`/`oh` comes from the spec table (§6.3), not from which table has a row, so a healer who also did damage gets `oh`
and no `mit`. `alv` is the denominator for every "per minute" metric; the card states "per minute alive" explicitly.

`[DECISION]` **Tracked spells.** Chosen **per player per build** in Python: spells the player cast in any pull, with oracle
`max(cd, category_cd) ≥ 45 s`, ranked by cooldown, top 6, plus every configured raid CD / defensive the player cast (typically 0–4 more);
stable across pulls, so `cdt`, `ce` and cross-pull aggregation use the same set everywhere; D3's integer view applies to those with
cd ≥ 90 s.

---

## 7. Per-player view and payload design

### 7.1 Where the view lives

| Option | For | Against |
|---|---|---|
| (i) Expand the **Players tab** into a per-player card driven by the existing Player filter | `renderPlayersTab` already switches to a per-player view when the filter is set and aggregates across **all** boss payloads (`dash.js:953-990`, `963`); the Player filter is global and persists across tabs, so one selection gives the card here and the focus block on every boss tab; the tab id `tabPlayers` is outside the `/^tab\d+$/` boss regex (`dash.js:893`); the Players tab is where a raider already looks for themselves; no new tab in a 21-button strip | the static roster table must give way (it becomes the "no player selected" state, and the team strip); the card is JS-rendered so it depends on all payloads being inflated |
| (ii) New "My raid" tab | a clean surface | duplicates (i); the tab strip already wraps into two rows at 1440 px (`CLAUDE.md` §7); the mobile `<select>` gets longer; deep links and filter wiring must be re-done |
| (iii) Extend the boss-tab focus block (`dash.js:708-766`) | per-boss depth is exactly where cooldown timelines and death recaps belong | it is per boss; the "how did I do this night" summary needs cross-boss aggregation; the boss tab is already ~13,000 px tall for a 2-pull fixture (`CLAUDE.md` §11) |

`[DECISION]` **(i)**, with (iii) kept and lightly extended: the Players-tab card is the summary and the per-boss rows link to the boss tab
(`gotab`), where the focus block shows the boss-specific depth (cooldown timelines per pull, tank-buster rows, death recaps). Nothing
new is added to the boss tab's default height; the depth appears only when a player is filtered (as today, `dash.js:803`). ui-ux-pro-max
guidance applied: "Deep Linking — URLs should reflect current state" (`ux-guidelines.csv`, Navigation), "Analytics Dashboard → Data-Dense
Dashboard, Drill-Down Analytics + Comparative" (`products.csv`), "Heading Hierarchy — sequential h1–h3", "Empty States — helpful message
and action", "Loading Indicators — preserve layout, `aria-busy`".

`[CAVEAT]` Roadmap 4.4 (per-tab lazy inflation) conflicts with the card's need for every boss payload. If 4.4 lands, opening the Players
tab with a player selected must trigger inflation of all boss payloads first (skeleton with `aria-busy`), or Python must precompute the
per-player aggregates into a small Players-tab payload (the `sev` block, §7.4, is already such a payload). The design keeps both doors open by putting the per-pull vectors in the boss payloads
(needed by the focus block anyway) and the aggregation in pure JS helpers that could be moved to Python.

### 7.2 Self-selection and deep links

- Primary: the toolbar **Player** `<select>` (exists, with role labels, `dash/page.py:128-131`). Add a `<datalist>`-backed text input on
  desktop for the 66-name list (ui-ux: "Autocomplete — help users find results faster").
- Secondary: every player name in the Players-tab roster table and in boss-tab tables is a `<button class='linklike' data-player>` that
  sets the filter ("click your name").
- Deep link `#tabPlayers?player=<label>` (Roadmap 4.7), updated when the filter changes (ui-ux Deep Linking), plus a "Copy my link"
  button on the card so a raider can bookmark the URL that Discord posts each week.
- Remember the last selected player in `localStorage` (like `wide`) and offer "Show my card" on the Players tab when nothing is selected.
- `Esc` clears (exists).

### 7.3 Information hierarchy of the card (top to bottom)

| Block | Content | Form (dataviz) | Phase |
|---|---|---|---|
| 1 Headline | "Omess — Havoc Demon Hunter · 3 nights · 41 pulls · **2 Good · 1 Watch · 3 Note**" with the night filter echoed | `h2` + counts as text badges (status palette + word) | 1 |
| 2 One thing to work on | the single highest-scoring Watch item of "this night" (definitions below) with its number, baseline and an actionable sentence; or "Nothing stands out — keep going" | `article.insight` markup (exists) with an `h3` (the Python helper renders an `h4`, which `dash.js` may not emit) | 1 |
| 3 KPI tiles | 6–8 stat tiles: deaths/pull, first-death share, avoidable hits/min, active %, median active DPS or HPS, prep streak, parse/bracket (kills), ilvl; each with **delta vs the player's earlier nights** ("−0.4 vs last 3 nights", same baseline as the `sev` item) and a sparkline of per-night values (up to 12 nights; omitted below 4 nights, the delta text stays) | stat-tile contract: label · value · signed delta vs a named period · sparkline in the de-emphasis hue with the current point in the accent (`dataviz/references/marks-and-anatomy.md` "Figures") | 1 |
| 4 Per-boss rows | one row per boss: pulls, deaths, first deaths, avoidable/min, active %, median/best active DPS or HPS, cooldown efficiency (P2), link to the boss tab | `tbl()` sortable; `.scroller` on mobile (ui-ux "Table Handling") | 1 |
| 5 Consistency | per boss with ≥ 4 pulls: active DPS/HPS per pull as dots, own median line, band = own median ± IQR of earlier nights; kills marked | small multiples, **emphasis** form (one series + grey references, `choosing-a-form.md`); inline SVG; skip rule: < 4 pulls → sentence | 1 |
| 6 Role section | DPS: cast-efficiency panel (the tracked spells, §6.10; mini-timelines), downtime bullet vs role median, top spells share. Healer: overheal bullet + per-spell table (P3), mana heat strip per pull, healing-CD efficiency, dispels. Tank: AM-at-hit uptime bar, mitigated share, co-tank paired bars, defensive efficiency, tank-buster glyph row (P3) | bullet bars vs baseline (`charts.csv` "Performance vs Target (Compact)": label every range and target with text), uptime bars, heat strip, box rows | 1 (cached parts) → 2/3 |
| 7 Deaths report card | one glyph box per death: first death? avoidable? defensive used / available / none; external received; expand → recap (exists) | performance box row: `<button>` per death with glyph + sr text, tooltip repeats the text; table twin under `details.table-view` | 1 (first-death data) → 2 (all deaths) |
| 8 Preparation streak | per pull glyph row for flask · food · rune · pre-pot · 2nd potion · healthstone; streak length; "missed on N of M" | `prepCell` glyphs (exist) in a row; stacked outcome bar with counts as text | 1 |
| 9 Gear | ilvl, gaps list | text list | 1 |

**Severity engine** `[DECISION]` — one engine, in Python (the single-renderer rule of `CLAUDE.md` §7 applied to scoring): Python
computes per player × night × metric the value, baseline, level, score and template id into a small `sev` payload block (§7.4); JS only
orders, filters and renders it (so the card follows the filters by re-selecting nights, not by re-scoring); the named rollups read the
same block. For each metric the baseline is the first available of: own history → role median → fixed Note bands (WoWA/community).
*Good* = at or better than the baseline, or worse by no more than the tolerance; *Watch* = worse than the baseline beyond the
tolerance on ≥ 3 pulls (or ≥ 25 % of pulls); *Note* = informational (thin history, kills-only metrics, bands). Public card: order by
level, then score; show ≤ 3 Watch and always ≥ 1 Good. Named build: no cap. Templates for the actionable sentence live in one `ADVICE`
map (metric → sentence with placeholders), plain language, no per-spec text.

`[DECISION]` Definitions used by the engine and the card:

| Term | Definition |
|---|---|
| Own history | baseline = median over the player's nights **before the latest selected night** (Python: before each night, same night type); needs ≥ 2 such nights; "this night" = the latest night in the selection. |
| Role median | median over the **other** players of the role in the same pull, then median over pulls; needs ≥ 3 others (tanks → co-tank baseline); players with < 25 % of the pulls excluded; support specs excluded (§6.3). |
| Score | `score = abs(value − baseline) / tolerance × pulls_affected / pulls`, where `pulls_affected` = pulls whose own value is beyond the tolerance in the scored direction. Ties are broken by tier (deaths > avoidable > defensives > preparation > active time > throughput > cooldowns). |
| One thing (block 2) | the Watch item of "this night" with the highest score (tier breaks ties). |
| Best Good | the item with the highest score in the good direction. |
| Multi-spec players | headline = spec with most pulls in the selection; role section per role played, as the focus block does today. |

`[DECISION]` Tolerance, direction and tier per metric. Values marked *default* were not given by the review; they are starting values
to tune on the first real builds (the user may strike them).

| Metric (`PM_COLS`) | Tolerance | Better when | Tier |
|---|---|---|---|
| Deaths per pull (`dth`) | ±0.15 absolute | lower | 1 deaths |
| First-death share (`fd`) | ±10 pts absolute (*default*) | lower | 1 deaths |
| Avoidable hits / min alive (`avm`) | ±25 % relative | lower | 2 avoidable |
| Deaths with no defensive cast (Phase 1: first deaths; Phase 2: every death with one available) | ±25 pts absolute on the share (*default*) | lower | 3 defensives |
| AM-at-hit (`am`, tanks) | ±5 pts absolute (*default*) | higher | 3 defensives |
| Preparation (`prep` flask/food/rune, pre-pot) | any miss (the score uses tolerance = 1 missed pull) | no miss | 4 preparation |
| Active time (`act`; Phase 2 `dtm`) | ±3 pts absolute | `act` higher, `dtm` lower | 5 active time |
| Active DPS / HPS (`dps`, `hps`) | ±8 % relative | higher | 6 throughput |
| Overheal (`oh`) | ±5 pts absolute (*default*) | lower | 6 throughput |
| Cast efficiency (`ce`, Phase 2) | −10 pts absolute | higher | 7 cooldowns |
| Interrupt share (`ish`), parses (`rp`, `bp`), gear gaps (`gap`) | Note only (assignment-dependent, kills-only, or a checklist) | — | — |

### 7.4 Payload strategy

`[DECISION]` **Precomputed vectors, no raw casts.**

| Payload addition | Shape | JSON per player-pull | Per pull (23 players) | Month (220 pulls), base64 after gzip 5.6:1 |
|---|---|---|---|---|
| `pm` (Phase 1) | boss-level `pmcols` = the §6.10 `PM_COLS` in the §6.10 order (single source of truth; P1.4 imports `PM_COLS` from `analysis/player_metrics.py` and the roundtrip test asserts equality); per pull `pm: {label: [ints]}` (scales per §6.10; trailing `null`s omitted) | ≈ 90–110 B (24 values incl. mid-vector `null`s for role-specific columns, + the label key) | ≈ 2.1–2.5 KB | ≈ **110–130 KB** |
| `sev` (Phase 1) | one Players-tab block (not per boss): `{label: {night: [[metric, value, baseline, level, score, tpl], …]}}` from `analysis/severity.py` (§7.3) | — (≈ 10 items × ~20 B per player-night) | — | ≈ 15 KB |
| `deaths[i].av`, `deaths[i].ds` (avoidable death, death save) | two flags | — | ≈ 100 B | ≈ 6 KB |
| `dd`/`hd` gain `ilvl`; `parses` gain `bp`, `spec` | small ints/strings | — | ≈ 250 B | ≈ 15 KB |
| `cdt` (Phase 2) | per pull `{label: {spellId: [deciseconds…]}}` for the tracked spells (§6.10; ≈ 6 on average) | ≈ 150–250 B | ≈ 4–6 KB | ≈ **290 KB** |
| `pm` columns (Phase 2) | the Phase 2 `PM_COLS` (`dtm sg cc ce mp hld`, §6.10) | ≈ +40 B | ≈ 1 KB | ≈ 60 KB |
| `deaths[i].rd` (Phase 2) | defensives **ready** at death `[[spellId, ready_s]]` for every death, `def/ext` for every death (today first only) | — | ≈ 1 KB (17.8 deaths) | ≈ 45 KB |
| `rdt` (Phase 3) | per pull raid damage taken per second, 300 ints | — | ≈ 1 KB | ≈ 60 KB |
| **Total Phases 1–3** | | | | ≈ **+0.6 MB** (601–621 KB: Phase 1 ≈ 146–166 KB, Phase 2 ≈ 395 KB, Phase 3 ≈ 60 KB) → file ≈ 2.5 MB (Discord limit 10 MB); budget Q4 ≤ +0.7 MB leaves ≈ 80 KB for Phase 3's other additions |
| Rejected: raw casts | 5,000–8,500 events × ~18 B compact | — | 90–150 KB | **6–9 MB** — breaks the budget on its own |

Load-time implication: today 0.97 MB gzip inflates to 5.4 MB JSON in `DecompressionStream`; ≈ +0.45 MB gzip adds ≈ 2.5 MB JSON and an
estimated 150–400 ms on a laptop; the skeleton + `inert` tab strip (exists) covers it. `tests/test_dashboard.py` gets a size guard
(baseline = the fixture's per-pull payload before Phase 1, recorded by P1.4): ≤ baseline + 0.8 KB base64 per pull after Phase 1
(≈ 0.69 KB estimated) and ≤ baseline + 2.6 KB after Phase 2 (≈ +1.8 KB more estimated).

### 7.5 Chart and tile forms (applying the `dataviz` skill)

| Element | Form | Renderer | Rules applied |
|---|---|---|---|
| KPI tiles with deltas + sparklines | stat tile (value · delta · sparkline of up to 12 nights; sparkline omitted below 4 nights, the delta text stays) | inline SVG sparkline inside `kpisHtml()` tiles | "a single current value + trend → stat tile, not a one-bar chart"; delta colour = direction × whether up is good, always with a sign and the period name; proportional figures on the value, `tabular-nums` only in table columns (`marks-and-anatomy.md`) |
| Consistency per boss | small multiples, emphasis form: own dots + own median line + grey band | inline SVG (`drawProgression` style, focusable points) | one series → no legend box, title names it; band and median get text labels; < 4 pulls → sentence (skip rule, `CLAUDE.md` §7); 2 px lines, ≥ 8 px markers with a 2 px surface ring |
| You vs baseline (DPS, active %, overheal, downtime, avoidable/min) | bullet bar: performance bar ≤ 24 px thick, target tick = role median, second tick = own median, qualitative ranges labelled in text | CSS/SVG `bulletBar()` | "label every qualitative range and target with text; colour is supplementary" (`charts.csv`); status tokens only where the colour *means* good/watch; text never wears the series colour |
| Uptime (AM at hit, buff uptime) | uptime bar; per selected pull: segments `[start, end]` on a fight axis | `.bar > i` (exists) / SVG segments | 2 px surface gap between segments; value as text at the end |
| Cast-efficiency mini-timeline | one row per tracked spell: fight axis, cast ticks, "cooling" segments in series-1, "available" in grey, "could fit another use" segments hatched (45°) + text count | inline SVG, one row per tracked spell (§6.10) per player per pull; focusable ticks; table twin in `details.table-view` | texture as the backup channel, ordered; tooltip never gates (values in the table twin); hit targets ≥ 24 px |
| Deaths / prep / tank-buster rows | performance box row: `<button>` per event, glyph + sr text, 3 status levels | HTML | status never by colour alone; ≤ 3 status colours + icon + label |
| Mana heat strip | 30 buckets per pull, one-hue sequential ramp of `--series-1` via `--series-1-rgb` alpha steps, text at 25/50/75 % and end | CSS grid | sequential = one hue light→dark; legend with scale breaks; table twin |
| Raid damage intake + CD markers (selected pull) | line + markers | **Plotly** (`chart()` with skip rule) | no dual axis: damage intake and HPS never share a plot; markers ≥ 8 px with a surface ring; hover crosshair |
| Existing box plots, histograms, heatmaps | unchanged | Plotly | — |
| Per-boss rows, per-spell tables, gaps lists | tables | `tbl()` | every chart has a table twin; captions visible |

Palette note: the six series tokens were contrast-checked (`tests/test_tokens.py`) but their adjacent-pair **CVD separation has not been
validated** with `dataviz/scripts/validate_palette.js` (needs `node`, which the machine lacks). `[TODO]` (user; **not** a Phase 1 exit
criterion — a sub-agent cannot drive a non-headless browser) run the validator once as a `<script type=module>` in a scratch page in a
non-headless Firefox and record the `console.table` result in the change log; if a pair fails, re-step that token (all series colours
are used with direct labels or legends, so the 6–8 floor with secondary encoding applies).

### 7.6 Accessibility and token rules (from `CLAUDE.md` §7/§10)

No hex outside `tokens.css` (`tests/test_dashboard.py:531-538`; new `dash/*.py` and `analysis/*.py` modules are added to that list);
status never carried by colour alone (glyph + sr word, visible tag); headings `h2`/`h3` only inside `dash.js` (`600-604`); tables via
`table()`/`tbl()` with visible captions and `<th><button aria-sort>`; charts via `chart()`/`fig_html()` with the small-data fallback;
KPI strips via `kpis()`/`kpisHtml()`; 12 px floor, 44 px targets, `prefers-reduced-motion`, focus rings; no `undefined` keys in
Plotly objects; every SVG element that carries a value is focusable and has a `<title>`; the card region gets `aria-live='polite'`
one-line status ("Card for Omess, 3 nights") rather than announcing the whole panel (Roadmap 4.5).

### 7.7 Tone and anonymity — what appears where

| Content | Public Discord build (`anonymous`) | `--callouts named` RL build |
|---|---|---|
| Per-player card | only behind the Player filter; nothing per-name is rendered until a name is chosen | same, plus the same-spec comparison line and no cap on Watch items |
| Comparisons on the card | own history, role median, bracket %ile (kills), fixed Note bands | + same-spec in roster, + rank among role ("3rd of 12") |
| Players tab with no player selected | team strip without names (prep compliance %, avoidable/min trend, interrupt coverage, share of first deaths without a defensive, "pick your name to see your card"), then the existing roster table **sorted by name (secondary: pulls)** with neutral counts, no severity colours; the first-death-rate sort is available only in the named build | + R1 "who needs help with what", R4/R5/R8/R9/R10 with names, sorted |
| Boss-tab focus block | as today + cooldown timelines / tank-buster rows for the filtered player | same |
| Home | unchanged anonymous callouts + one new: prep compliance trend; no names (`tests/test_dashboard.py:360`) | as today's named Home |
| Wording | Good / Watch / Note; number + baseline + one action; ≥ 1 Good | same words; more items |
| Never, in any build | red text without a label; "worst N"; parse-coloured rosters on Home; third-party names from top logs | "worst N" still avoided; sorted lists are neutral tables |

### 7.8 Mobile (≤ 700 px)

Card blocks stack in one column; KPI tiles 2-up; per-boss rows in `.scroller`; small multiples one per row with a fixed 120 px height;
mini-timelines keep one row per tracked spell and drop the tick labels to a tooltip + table twin; box rows wrap; the Player picker is the toolbar
`<select>` (the filters `<details>` is closed by default on phones, `CLAUDE.md` §7); all targets ≥ 44 px (ui-ux "Touch Friendly").
Verification: headless-Firefox capture of `copy.html#tabPlayers?player=<fixture name>` at 390 px with the delayed-`load` trick
(`docs/plans/2026-09-24-dashboard-redesign.md`, Audit `[CAVEAT]`).

### 7.9 Text mock of a Phase 1 card (public build, fictional player, Thu + Sun main nights)

```
Players ▸ Player A — Havoc Demon Hunter · 3 nights · 27 pulls · Good 3 · Watch 1 · Note 2         [Copy my link]

One thing to work on
  Watch  Pre-pot missing on 9 of 27 pulls (raid median 3 of 27 pulls). Pot at the pull timer, not after the first GCD.
         Pulls: Ula'tek H #3 #4 #7 · Twin Fangs H #2 …                                            [Open Ula'tek ->]

  Deaths / pull     First death        Avoidable hits / min alive   Active time        Median active DPS   Prep streak   Kills: parse · bracket   ilvl
  0.30  ▼ −0.15     1 of 27  ▼ −1     0.9  ▼ −0.4 (raid 1.3)       88 %  ▲ +2 (DPS 91 %)  1.62 M  ▲ +4 %    6 pulls       58 · 71                 289
  ~~~sparkline~~~   ~~~~~~~~~~~~~     ~~~~~~~~~~~~~~~~~~~~~~~~~     ~~~~~~~~~~~~~~~~~~~~   ~~~~~~~~~~~~~~~~   —             —                        —
  vs your 2 earlier nights in this build

Per boss                     Pulls  Deaths  First  Avoid/min  Active  Median DPS  Best DPS
  Ula'tek (Heroic)  ->        18      6      1       1.1       87 %    1.58 M      1.79 M
  The Twin Fangs (Heroic) ->   9      2      0       0.6       90 %    1.71 M      1.81 M

Consistency — Ula'tek (Heroic), 15 of 18 pulls (3 under 60 s left out)   [dots per pull · own median line · grey band = earlier nights ± IQR · ✓ kill]
  |·  ·   · ·  ·     ·  · ·  ·   ·  ·    ·  · ·✓|

Deaths (8)   [1 first death · ✓ defensive used] [2 ·] [3 ! avoidable: Rattler Slam] [4 ·] [5 ·] [6 ·] [7 ·] [8 ! avoidable]   Show as table ▸
             defensives shown for the first death only (every death, and "Blur available", arrive in Phase 2) · deaths after the wipe call not counted

Preparation  flask ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓  food ✓… rune ✓… pre-pot ✓✓·✓·✓✓·… 2nd potion 12 of 18 pulls ≥ 5 min  healthstone 3

Gear   ilvl 289 (raid 285–294) · cloak: no enchant · ring 2: empty socket
```

Phase 2 inserts the role section between "Consistency" and "Deaths": a cast-efficiency panel (Metamorphosis 2 of 3 · 83 % ▬▬▬░░ …),
a downtime bullet (9 % · DPS median 6 %) and, on the boss tab, the per-pull mini-timelines. Every glyph carries an sr-only word and a tooltip
with the same text; every chart has a table twin.

---

## 8. Roadmap

Each task is written to become one sub-agent task: inputs, files, acceptance criteria, effort, model. Verification is its own task
per phase (`CLAUDE.md` §0: raw command output in the report). Every phase ends with a tagged `docs/CHANGES_<date>.md` entry and a
`CLAUDE.md` update.

### Phase 0 — Hygiene and measurement (7.5–15 sub-agent-days, 7–14 without the optional P0.9; startable next session)

**Goal:** remove the four known pitfalls, make the spec authoritative, prepare fixtures, and measure what the research could not.
**Ships:** correct "externals received"; a run-end line "points this run: X of Y"; clean stop on rate limit; `wipeCalledTime` on every
fight; `06-live-probe.md`.
**New data / API cost:** none for builds; ~10–15 calls for the probe. **Payload delta:** 0.

| Task | Inputs | Files | Acceptance criteria | Effort | Model |
|---|---|---|---|---|---|
| `[DONE 2026-10-01]` P0.1 Buffs `targetID` leak | `04` §1; `attach_casts` `collect_data.py:940-979` | `collect_data.py`, `tests/test_units.py` | synthetic events with source = dying actor and target ≠ actor are excluded from `externals`; fixture build unchanged except externals | S | opus |
| `[DONE 2026-10-01]` P0.2 `nextPageTimestamp` everywhere | §6.2; `633-643`, `812-852`, `890-937` | `collect_data.py`, tests with a stub fetcher | every aliased events part requests `nextPageTimestamp`; a stub returning a page cursor triggers the single-fight follow-up loop and concatenation; no version bump; console line when a follow-up happened | S | opus |
| `[DONE 2026-10-01]` P0.3 `filterExpression` as variable | §6.2; `829-833` | `collect_data.py`, tests | built query text contains `$filter: String` and no inlined expression; cons entry keys unchanged (no re-download on the fixture) | S | opus |
| `[DONE 2026-10-01]` P0.4 `rateLimitData`, wait/stop, `--refresh` guard | §6.2; `wcl_client.py:83-131`; Roadmap 6.5 | `wcl_client.py`, `cache.py` (`count_api_call`), `collect_data.py`, `build_dashboard.py`, tests with a fake session | `rateLimitData` appended at send time only (cache keys unchanged: fixture build makes 0 network calls); per-request Δpoints log; run-end summary; on a 429 the existing short backoff runs first and the `pointsResetIn` wait only when `pointsSpentThisHour ≥ 0.95 × limitPerHour` (fake-session test for both paths); `WCLRateLimited` path saves meta and exits 3; guard message when > 80 % spent; `WCL_RATE_WAIT_MAX` documented as a user-added `.env` key | M | opus, fable review |
| `[DONE 2026-10-01]` P0.5 Spec table | §6.3; `dash/common.py:135-156`; `dash.js:44-46`; `dash/page.py:132` | `specs.py` (new), `collect_data.py` (lift `specID` from `cinfo` into the pull dict), `dash/common.py`, `dash/page.py`, `dash/static/dash.js`, tests | all 32 spec names of the newest build and all fixture `specID`s resolve; `specID` per player is in the pull dict; `support` flag set for Augmentation; JS role sets come from the emitted `cfg` JSON; player-pulls without spec drop to 0 on the fixture; unknown specID → console warning, role `''` | S/M | opus |
| `[DONE 2026-10-01]` (budget raised to 7.5 MB) P0.6 Fixture recorder update | §6.6; `tests/make_fixtures.py:49-80` | `tests/make_fixtures.py` | `slim()` keeps the listed fields; `--slim` on the existing fixtures runs without error; documented size budget ≤ 6.5 MB; the user re-records **once**, after P0.8 (network; see Ordering) | S | opus |
| `[DONE 2026-10-01]` P0.7 Live probe | `04` "Not verified" list; §6.7 | `tools/wcl_probe.py` (new), `docs/research/2026-09-25-player-analysis/06-live-probe.md` | one call each for: `table(Casts)`, `table(Buffs)`, `table(Summary)` shapes; `includeResources` key names on a healer cast; `playerDetails(fightIDs, includeCombatantInfo)` fields; a filtered Casts query with `limit: 100` to see early pagination; one whole-fight `casts` alias on the longest cached pull: record events, bytes, pages (sets the P2.1 batch size); `archiveStatus` for the fixture report and the oldest report of the current build; the Interrupts table of one pull: are never-interrupted enemy spells listed, and does `spellsBegun` equal the interruptible casts (E9/`ish`)?; Δpoints for FIGHTS, PHASES, a 5-fight bundle, a 10k DamageTaken page, RANKINGS, a casts alias; 429 headers if any. Report contains raw (redacted) JSON snippets and a decision for P0.8 | S | opus |
| `[PARTLY DONE 2026-10-01]` (`wipeCalledTime` yes; merge skipped, saves only 1 pt/report) P0.8 `FIGHTS_QUERY` changes: `wipeCalledTime` (always) + FIGHTS+PHASES merge (conditional) | P0.7 Δpoints; `04` §7; §6.7, §6.10 | `collect_data.py` (`FIGHTS_QUERY`, pull dict `wipe_called_s`), fixtures | `wipeCalledTime` requested and carried into the pull dict (`null` when no wipe was called); merge only if PHASES costs ≥ 50 % of FIGHTS; keep the phases fallback; both query-text changes land **before** the single fixture re-record | S | opus |
| `[SKIPPED 2026-10-01]` P0.9 `--prune-cache` (optional) | `01` §3; Roadmap 3.5 | `cache.py`, `build_dashboard.py`, tests | deletes files whose key is not producible by current query texts/version tags; dry-run lists MB; never touches `report_meta.json` | S | opus |
| P0.V Verification | — | — | `pytest -q` output (all pass), quickjs syntax check output, fixture build console showing 0 API calls on the re-recorded fixtures | S | opus |
| P0.D Docs | — | `docs/CHANGES_<date>.md`, `CLAUDE.md` §3/§4/§5/§6/§11 | tagged entries for P0.1–P0.9; `WCL_RATE_WAIT_MAX` listed in §4 as a key the user adds; spec table, `wipeCalledTime` and pagination described in §5 | S | opus |

**Tests to add:** stub-fetcher pagination test; fake-session rate-limit test (short backoff and points wait); spec-table coverage test; query-text assertions (incl. `wipeCalledTime`).
**Risks / fallbacks:** the probe needs credentials (runs through `wcl_client`, `.env` unread by Claude Code); if the probe cannot run,
Phase 1 proceeds (it needs none of the probe results) and Phase 2 keeps its **[unverified]** marks; if the fixture report is archived,
pick a new fixture report before the re-record (+1 S task; all fixture expectations change; Q7).
**Dependencies:** none. P0.6 and P0.8 must land before the user re-records the fixtures (once) for Phase 1.

### Phase 1 — Mine the cache: the per-player card (17.5–33 sub-agent-days)

**Goal:** everything in §4 marked cached-free, on the Players tab card and in the named rollups. **Zero new API calls.**
**Ships:** E1, E2, E3 (first death), E4–E9, E10 (first death), E12, D1, D5, H1 (total), H9, H10, T1–T3, T7, T8, R1–R3, R5, R7–R9; Home prep-compliance callout.
**New data:** none. **Payload delta:** ≈ +145–165 KB per month (§7.4: `pm` 110–130 KB, `sev` ≈ 15 KB, flags/ilvl ≈ 20 KB). **Cache:** unchanged.

| Task | Inputs | Files | Acceptance criteria | Effort | Model |
|---|---|---|---|---|---|
| `[DONE 2026-10-02]` (23 cols: `ish` dropped; death-cascade wipe cutoff since `wipeCalledTime` is never set) P1.1 Metric definitions + `player_metrics.py` | §4 formulas; `01` §1.1–1.2; re-recorded fixtures | `analysis/__init__.py`, `analysis/player_metrics.py`, `tests/test_player_metrics.py` | `PM_COLS` exactly as §6.10 (order, unit, scale and null rule per column); pure function `player_metrics(pull, bundle_rows, events) -> {label: vector}`; edge cases tested: player with no table row, multi-role player, death at 0 s (alive time floor 1 s), no kills (no parses), healer without healing row, deaths and hits after `wipeCalledTime` excluded from `dth/avh/avm/dtk` but not from `fd/alv` | M | fable |
| `[DONE 2026-10-02]` (block counts dropped: no block data cached; only Vengeance ids verified) P1.2 Tank mitigation | §6.5; `04` §8; DT events `buffs`, `mitigated`, `hitType` | `config/tank_mitigation.example.json` + `.json`, `analysis/mitigation.py`, tests | AM-at-hit share (count and `unmitigatedAmount`-weighted), hits without a `buffs` key excluded, `am` = `null` + "aura data incomplete" when they exceed 30 % of the tank's hits; mitigated share = `(Σ mitigated + Σ absorbed) ÷ Σ unmitigatedAmount`; block/dodge/parry counts, DTPS alive, co-tank pairing per pull; unknown tank spec → `null`s and one console note; ids validated as numeric | M | opus |
| `[DONE 2026-10-02]` (roster-majority slot rule) P1.3 Gear checks | §6.5; cinfo `gear[]`, table `gear[]` names | `config/gear_checks.example.json` + `.json`, `analysis/gear.py`, tests | ilvl min/avg/max per player per pull, missing enchant per enchantable slot, empty socket rule, low-ilvl slot; tested on the fixture's 3 full-gear players | S | opus |
| `[DONE 2026-10-02]` (`deaths[i].ds` and `kc` dropped; T7 tank recap AM flag pulled forward; +801 B/pull on the fixture) P1.4 Payload | §7.4; `dash/payload.py:135-160`; `tests/test_dashboard.py:35-55` | `dash/payload.py`, tests | boss-level `pmcols` = `PM_COLS` imported from `analysis/player_metrics.py` (roundtrip test asserts equality with the §6.10 list), `pm` per pull, `deaths[i].av/ds`, `dd/hd` ilvl, `parses` `bp`+`spec`; roundtrip test updated; baseline per-pull size recorded; size guard: fixture payload per pull ≤ baseline + 0.8 KB base64 | S | opus |
| `[DONE 2026-10-02]` P1.5a Severity engine + pure card helpers | §7.3 (severity definitions, tolerance table); §6.10; `dash.js:953-990` | `analysis/severity.py`, `dash/payload.py` (`sev` block), `dash/static/dash.js` (quickjs block), `tests/test_severity.py`, `tests/test_dashboard.py` (quickjs) | `severity()` returns value, baseline, level, score and template id per player × night × metric exactly as §7.3 (own history → role median → bands; tolerance/tier table; score; short-pull and wipe-call rules of §6.10); `sev` block emitted; pure JS helpers `playerSummary(payloads, sev, name, filters)`, `oneThing(items)`, `deltaText()` only order, filter and format the precomputed items (no re-scoring in JS) and are tested in quickjs | M | fable |
| `[DONE 2026-10-02]` (D5 top-spells share deferred to Phase 3; not yet checked in a browser) P1.5b Card renderer | §7.3; P1.5a helpers; P1.6 components; `dash.js:953-990`, `708-766`; `01` §8(c)(e) | `dash/static/dash.js`, `dash/players.py`, `dash/page.py`, `dash/static/dash.css`, `tests/test_dashboard.py` | `renderPlayerCard(name)` replaces the dynamic table; blocks 1–4, 7–9 of §7.3 render for the fixture player; block 2 uses the `article.insight` markup with an `h3`; no `h4`/`h5`; no hex; empty states for < 2 nights ("first nights — no trend yet") | M/L | opus, fable review |
| `[DONE 2026-10-02]` (no screenshot) P1.6 SVG components | §7.5 | `dash/static/dash.js`, `dash/static/dash.css`, tests | `sparkline(values)`, `bulletBar(value, target, own, ranges)`, `boxRow(items)`, `smallMultiples(series)` produce focusable SVG/HTML with text twins; skip rule for < 4 points (the sparkline is omitted below 4 nights, the delta text stays); token colours only; screenshot shows marks ≤ 24 px, 2 px lines | M | opus |
| `[DONE 2026-10-02]` P1.7 Self-selection + deep link | §7.2; Roadmap 4.7 | `dash/static/dash.js`, `dash/page.py`, `dash/players.py`, tests | names in tables are buttons that set the filter; `#tabPlayers?player=` read on load and written on change; it coexists with the `#tabN:section` parser (`dash.js:993-1001`: split the hash on `?` before the section parse) and labels are URL-encoded / decoded (`encodeURIComponent`; tested with a label containing an apostrophe and a `Name-Realm` label); `localStorage` last player; "Copy my link" | S/M | opus |
| `[DONE 2026-10-02]` (R7 reduced to interrupts per pull: `ish` dropped) P1.8 RL rollups (named) | §4.5 R1–R3, R5, R7–R9; `dash/home.py:117-118` gating; P1.5a | `dash/rollups.py` (new, reads the `analysis/severity.py` results), `dash/players.py`, tests | rendered only when `--callouts named`; anonymous build has no name in the Players-tab team strip (test); R1 sorted by level, then score (§7.3), from the same precomputed severities as the card; every table via `table()` | M | opus |
| `[DONE 2026-10-02]` P1.9 Home callout + team strip | `dash/home.py:107-292` | `dash/home.py`, `dash/players.py`, tests | one anonymous prep-compliance insight; team strip on the Players tab without names; anonymous build: roster table order is alphabetical (test), the first-death-rate sort only in the named build; existing `test_dashboard.py:360` still passes | S | opus |
| `[PARTLY DONE 2026-10-02]` (pytest 288 + quickjs + size table; headless-Firefox captures not possible in the agent sandbox) P1.V Verification | — | — | `pytest -q`, quickjs check, headless-Firefox captures of `#tabPlayers?player=<name>` at 1440 and 390 px (delayed-`load` copy), payload size table like `01` §4 — all raw output in the report | S | opus |
| `[DONE 2026-10-02]` P1.D Docs | — | `docs/CHANGES_<date>.md`, `CLAUDE.md` §2/§7/§10/§11 | tagged entries; new modules and configs listed; Players tab description updated | S | opus |

**Tests to add:** `test_player_metrics.py` (synthetic), `test_mitigation.py`, `test_gear.py`, quickjs helper tests, payload size guard,
anonymity test for the team strip, no-hex list extended.
**Verification:** as P1.V. **Risks / fallbacks:** fixture re-record not done → P1.1–P1.3 test only on synthetic data and the build skips
the metrics that need missing fields (nulls); `buffs` key absent on ≈ 14 % of damage events (`04` §2) → those hits are excluded, and
more than 30 % missing gives "aura data incomplete" (§6.10); the string may also be a subset of auras → T1 shown as "≥ X %" with a `[CAVEAT]` in
the change log until Phase 2 cross-checks it. **Dependencies:** P0.5 (spec table), P0.6 + P0.8 + the single user re-record (fixtures).

### Phase 2 — Casts pipeline and spell oracle (25–48 sub-agent-days)

**Goal:** the WoWAnalyzer Foundation layer for every spec: cooldown usage with timelines, downtime, cancelled casts, defensive
ready-or-used at every death, healer mana, healing-CD and tank-defensive efficiency; the tracked-buff data (lust windows, externals)
that E10/E15 use now and Phase 3's uptime views (P3.10) read later.
**Ships:** E3 (all deaths), E6 (GCD), E10, E11, E14, E15, D2–D4, H3, H4, T9, R4, R5 (all deaths).
**New data / API cost:** casts (≈ 1–2 pages/pull, estimated), healer casts, tracked buffs ≈ +10 requests per 15-pull report (§6.8); oracle JSON built
offline once per patch. **Payload delta:** ≈ +0.4 MB per month (§7.4). **Cache:** ≈ +65–90 MB per month compact (§6.8).

| Task | Inputs | Files | Acceptance criteria | Effort | Model |
|---|---|---|---|---|---|
| P2.1 Whole-fight casts entry | §6.1–6.2; pattern `812-852`; P0.2/P0.3 | `collect_data.py`, `tests/make_fixtures.py` (slimmer), tests | `get_fight_casts()` batches 3 fights (revisit with the P0.7 page count), follows pagination, drops `fake`, stores compact rows, key `casts:v1:<code>:<fid>`; `count_api_call` correct; on `WCLError` warns once and returns `{}`; an archived report (`archiveStatus`) is skipped with one console line and the card states "cooldown data from <first unarchived night>"; fixture replay offline | M | fable |
| P2.2 Healer casts with resources | §6.1; P0.7 key names | `collect_data.py`, `analysis/mana.py`, tests | `hcasts:v1` entry; mana series per healer per pull bucketed to 30 points + value at 25/50/75 %/end/min; 150 ms de-dup; healer detection from the spec table | M | opus |
| P2.3 Tracked buffs | §6.1; `04` §1 leak | `collect_data.py`, `analysis/buffs.py`, tests | `tbuffs:v1:<code>:<fid>:<idhash>` with ids from `raid_cooldowns.json` + `tank_mitigation.json` + `defensives.json` only (no oracle-derived or tracked-cooldown ids, so the key does not change with the roster, §6.1); client-side `targetID` filter; uptime segments per (target, id) with pre-pull auras from cinfo and unmatched removes handled | M | opus |
| P2.4 Spell oracle generator | §6.4; `03` §4 | `tools/build_spell_oracle.py`, `analysis/oracle.py`, `tests/fixtures/spell_oracle_subset.json`, `tests/fixtures/trait_slice.inc`, tests | parses the three committed dump blocks correctly (cooldown, charges + recharge, category + modifiers, GCD, cast time, channelled flag, reset flag); rating scale incl. the DR brackets from `item_scaling.inc`; emits only requested ids; `oracle.py` loads the subset in tests; missing file → `None` and the documented empty states; cast ids missing from the oracle → one build warning "N cast ids missing from the oracle — rerun tools/build_spell_oracle.py", those ids treated as untracked | M | fable |
| P2.5 Cooldown engine | `02` §1 `SpellUsable`/`CastEfficiency`; `03` §4 edge cases | `analysis/cooldowns.py`, tests | per player per pull: charge tracking (charges, recharge, category cooldown, encounter-end reset); **possible casts** = `charges + floor((fight_s − t0)/cd_s)` with `t0` = pull start (pre-pull casts inferred from `combatantinfo.auras`), capped at the WoWA `floor(rawMaxCasts) + 1`, and **efficiency** = WoWA time-based `timeUnavailable / fightDuration`, ±1 cast tolerance — both quantities tested (e.g. a 2-charge 30 s spell in a 60 s fight: `2 + floor(60/30)` = 4 = WoWA `maxCasts` (`rawMaxCasts` 3), not the 5 of the earlier `1 + floor(…) × charges` form); "could fit another" gaps, "held at end"; pulls < 60 s → `null`; tracked-spell selection per player per build as §6.10 (stable across pulls); readiness `is_available(spell, t)` used for every death; abilities with oracle modifiers flagged `approx`; tested on synthetic sequences incl. a cast while "on cooldown" (tolerance path, error counter) | L | fable |
| P2.6 Activity engine | `02` §1 `GlobalCooldown`/`AlwaysBeCasting`/`CancelledCasts`; §3.1 pitfalls 1, 4, 5 | `analysis/activity.py`, tests | per cast: base = oracle `gcd_ms` (0 → off-GCD, no segment); hasted unless the spell's attributes say otherwise; `gcd = max(750, base/(1+haste))`; haste % from cinfo rating via the oracle scale **with DR brackets from `item_scaling.inc`**, lust buff applied; 1500 only when the oracle lacks the id; pulls < 60 s → `null`; cast-time spells from `begincast→cast`; channels from the oracle flag + duration; active-time union; downtime %, small gaps/min, cancelled %; suppression when overlaps > 2/min (result `null` + reason) | M/L | fable |
| P2.7 Payload | §7.4 | `dash/payload.py`, tests | `cdt`, the Phase 2 `PM_COLS` (`dtm sg cc ce mp hld`, appended per §6.10), `deaths[i].rd`, `def/ext` for every death; size guard ≤ baseline + 2.6 KB base64 per pull (Phase 1 + 2, §7.4) | S/M | opus |
| P2.8a Cast-efficiency panel (DPS / tank) | §7.3 block 6; §7.5 timelines; P2.5 | `dash/static/dash.js`, `dash/static/dash.css`, tests | one row per tracked spell with a mini-timeline drawn by a pure `cdTimeline()` SVG helper + table twin; downtime bullet vs role median; tank defensive efficiency; `cdTimeline()` tested in quickjs; no hex; h2/h3 only | M | opus, fable review |
| P2.8b Healer strip | §7.3 block 6; §7.5 heat strip; P2.2; P2.8a | `dash/static/dash.js`, `dash/static/dash.css`, tests | mana heat strip per pull (30 buckets, text at 25/50/75 %/end, table twin); healing-CD efficiency rows via `cdTimeline()`; no hex; h2/h3 only | S/M | opus |
| P2.8c Deaths row completion | §7.3 block 7; `deaths[i].rd` | `dash/static/dash.js`, tests | deaths box row with used / available / none and externals received per death; sr-only word + tooltip + table twin | S | opus |
| P2.8d Focus-block timelines | §7.1; `dash.js:708-766`; P2.8a | `dash/static/dash.js`, tests | the boss-tab focus block shows the per-pull timelines for the filtered player via `cdTimeline()`; nothing added to the default boss-tab height | S/M | opus |
| P2.9 Rollups extension | R4, R5 | `dash/rollups.py`, tests | cooldown compliance share + names (named); defensive usage all deaths | S | opus |
| P2.10 Configs | §6.5 | `config/raid_cooldowns.example.json` + `.json`, `config/defensives.json` migration, `build_dashboard.py` (`validate_config`) | ids validated against the oracle; substring fallback still works; `validate_config` warns on unknown ids | S | opus (user reviews the ids) |
| P2.11 Cross-check `buffs` string vs buff events | T1 vs `tbuffs` | scratch script → `docs/CHANGES` note | on ≥ 10 cached pulls, AM-at-hit from the `buffs` string agrees with uptime-at-hit from `tbuffs` within 5 pts; the share of each tank's damage events without a `buffs` key (excluded from `am`) is recorded; otherwise the design switches T1 to `tbuffs` | S | opus |
| P2.V Verification | — | — | `pytest -q`, quickjs, Firefox captures (Players card with role sections; a boss tab with the filtered player's timelines), payload size table, one real build's console showing request counts and Δpoints | S | opus |
| P2.D Docs | — | `docs/CHANGES_<date>.md`, `CLAUDE.md` | oracle workflow documented (`tools/build_spell_oracle.py`, `SIMC_SRC`), configs listed, §5 data collection updated (casts v1, hcasts v1, tbuffs v1) | S | opus |

**Tests to add:** compact casts fixture entries; oracle parser tests; synthetic cooldown sequences (charges, category, reset, error path);
GCD/haste tests; mana bucket tests; payload guard; helper quickjs tests.
**Risks / fallbacks:** point cost too high → reduce to kills + the best N wipes per boss (`--casts kills|all`, default all if P0 shows
casts ≤ 2 points/page); early pagination → batch 2; GCD model wrong for a spec → suppressed with reason, cast efficiency unaffected;
oracle unavailable → empty states, everything else ships; casts cannot be back-filled for archived reports (`04` §5) — the card shows
"cooldown data from <first unarchived night>". **Dependencies:** Phase 0 (P0.2–P0.4, P0.7), Phase 1 (card, payload, severity).

### Phase 3 — Role depth and RL rollups (21.5–43 sub-agent-days; 19.5–39 without the optional P3.5)

**Goal:** the curated, per-boss and team-level insights, and history beyond one build.
**Ships:** T4 (tank busters), H2/R6 (healer CD coverage), H6 (dispel latency), H1 per spell, H5, H11, H7 (team note), H8 (externals given), T6 (self-healing), D6/D7, D10, E13/R10, R11 digest, R12 history (Q6).
**New data:** per-healer Healing tables (4–5 small aliases/fight; + the two tanks for T6), filtered Debuffs (KB), optional per-phase DamageDone tables.
**Payload delta:** ≈ +60–100 KB per month.

| Task | Inputs | Files | Acceptance criteria | Effort | Model |
|---|---|---|---|---|---|
| P3.1 Tank busters | §6.5 `tankbusters.json`; T4; `dash.js:658` tank pattern | config + example, `build_dashboard.py` (`abilities_seen` gains `tank_share`), `analysis/mitigation.py`, `dash.js`, tests | glyph row per buster hit: AM / major CD / bare (+ "available" from P2.5); `validate_config` warns on unknown names; `abilities_seen.json` lists tank-share so candidates are visible | M | opus |
| P3.2 Healer CD coverage | H2, R6; cached DT events; P2 casts; `raid_cooldowns.json` | `analysis/intake.py`, `dash/payload.py` (`rdt`), `dash.js` (Plotly line + markers in the single-pull view), `dash/rollups.py`, tests | per-second raid damage taken; top-N spike detection; CD markers with caster; "uncovered spike" list; skip rule; named team view | M | opus |
| P3.3 Dispel latency | H6; Dispels table `guid`s | `collect_data.py` (`debuffs:v1`), `analysis/dispels.py`, tests | median/percentile latency per healer per debuff; pairing apply→dispel per target; unmatched dispels counted | M | opus |
| P3.4 Per-spell overheal | H1 per spell; P0.7 shape | `collect_data.py` (`heal:v1`), `analysis/player_metrics.py`, `dash.js`, tests | per healer per pull top 6 spells with overheal %; wording bands as Note; reactive vs HoT/absorb judgement left to the reader (a sentence, not a verdict) | M | opus |
| P3.5 Damage by phase / target selection (optional) | D6, D7; `targets[]`; phase timeline | `collect_data.py` (`ddph:v1` optional), `analysis/player_metrics.py`, `dash.js`, tests | add share per pull from `targets[]`; per-phase active DPS when the tables were fetched; skip rule | M | opus |
| P3.6 Talent build vs roster | E13, R10; oracle traits | `analysis/talents.py`, `dash/rollups.py`, tests | builds grouped by spec; majority build; per-player diff as node names; named build only | M | opus |
| P3.7 Persistent history (Q6) | R12; `mplus.py` history pattern | `data/player_history.json` writer in `build_dashboard.py`, `analysis/history.py`, `dash/payload.py` (per-player 8-week medians), tests | merged snapshot per night per player per metric median; identity by (name, realm) label; card deltas use it when present; tests use a tmp file | M | opus |
| P3.8 Night digest | R11; Roadmap 3.4 | `analysis/severity.py`, `dash/home.py`, `post_discord.py --summary`, tests | one Good + one Watch per role, anonymous on Home, named in RL build; Discord text ≤ 1,800 chars | M | opus |
| P3.9 Healer efficiency | H5, H11; P2.2 mana series; P2.6 GCD union; Healing-table `abilities[]` | `analysis/mana.py`, `analysis/activity.py`, `dash/payload.py`, `dash.js`, tests | H5 healing per 1k mana from the P2.2 mana series; H11 non-healing time from the P2.6 GCD union split by the Healing-table `abilities[]`; WoWA 30 / 40 / 45 % as Note bands; skip rule | M | opus |
| P3.10 Tracked-buff views | D10, H8, T6; `tbuffs` (P2.3); casts + oracle `Duration` (P2.1, P2.4); `heal:v1` (P3.4) | `analysis/buffs.py`, `dash/rollups.py`, `dash/payload.py`, `dash.js`, tests | D10 buff uptime of the tracked cooldowns vs own history (from casts + oracle `Duration`, §6.1); H8 externals given (named build); T6 self-healing share + externals received from `tbuffs` + `heal:v1` with `sourceID` = the tank (shape per P0.7) | M | opus |
| P3.11 H7 team note | H7; recap windows (cached); `avoidable.json`; `def/ext` for every death (P2.7) | `analysis/severity.py`, `dash/home.py`, `dash/rollups.py`, tests | deaths whose recap window is ≥ 80 % non-avoidable, ≥ 3 hits and without an external/defensive are counted as healable-damage deaths; one anonymous team sentence on Home/Players, the list in the named build | S | opus |
| P3.V Verification | — | — | `pytest -q`, quickjs check, headless-Firefox captures (healer and tank role sections, a tank-buster row), payload size table — all raw output in the report | S | opus |
| P3.D Docs | — | `docs/CHANGES_<date>.md`, `CLAUDE.md` | tagged entries; `tankbusters.json`, `heal:v1`/`debuffs:v1`/`ddph:v1` and `data/player_history.json` documented | S | opus |

**Risks / fallbacks:** per-boss curation is the RL's ongoing work (same as `avoidable.json`); Healing-table-by-source shape unknown →
P0.7 decides, fallback = skip H1 per spell (and the T6 self-healing share); the digest's wording needs the user's review before the first public post.
**Dependencies:** Phase 2 for T4 availability, H2 markers, H6 pairing, P3.9 (P2.2, P2.6) and P3.10 (P2.1, P2.3, P2.4); P3.10 also needs P3.4's `heal:v1`; otherwise Phase 1.

### Phase 4 — SimC baselines (optional, opt-in; 7–14 sub-agent-days)

**Goal:** personalised expected numbers for DPS (and tank rotational/defensive casts) from the player's own gear and talents.
**Ships:** D8, D9, D10 (sim column), a "Sim" note on the card; nothing for healers.
**New data:** none from WCL; a `simc` binary at build time (`SIMC_BIN` → `shutil.which("simc")` → Docker); weekly batch. `SIMC_BIN`
is a new `.env` key the user adds by hand (and to `.env.example`, `CLAUDE.md` §3).
**Payload delta:** ≈ +20 KB per month. **Degradation:** binary missing → no sim section is rendered (the HTML is byte-identical to a
Phase 3 build apart from the footer); the "simc not found" hint goes to the console, not the public HTML; everything else unaffected;
tests never invoke `simc`.

| Task | Inputs | Files | Acceptance criteria | Effort | Model |
|---|---|---|---|---|---|
| P4.1 Locator + docs + `--doctor` check | `03` §1, §7 | `simc_runner.py` (new), `README`/`CLAUDE.md` | locates the binary; prints version and `dbc.live.build_level`; documents the cmake build and the Docker fallback | S | opus |
| P4.2 Profile generator | `03` §2, §6; cinfo gear/talents; oracle traits `tree_index` | `analysis/simc_profile.py`, `config/simc.example.json`, tests against the fixture's full-gear players | emits class/spec/role/level/race, gear lines with `id/bonus_id/gem_id/enchant_id/ilevel`, talents split by tree (1/2/3/6; SELECTION node handling decided by one live run **[unverified]**), fight options pinned to the pull length bucket; deterministic; cache key = sha1(profile + simc build) | M | fable |
| P4.3 Batch runner | `03` §6 run time | `simc_runner.py`, `systemd/`, `build_dashboard.py --sims` | one sim per (player, gear+talent hash, 30 s length bucket, target count); `target_error=1` or `iterations=2000`; results in `data/sim/<hash>.json` (trimmed to `options`, `players[0].collected_data.dps/fight_length`, `stats[]` id/num_executes/portion_aps, `buffs[]` spell/uptime); never per pull; skipped when the binary is missing | M | opus |
| P4.4 Comparison + UI | D8–D10; P2 casts and `tbuffs` | `analysis/sim_compare.py`, `dash/payload.py`, `dash.js`, tests with a committed trimmed `json2` fixture | table "Ability · you · sim expects · Δ" for the 6–8 top-`portion_aps` abilities + cooldowns, ±1 cast tolerance, only abilities with ≥ 3 expected casts; buff uptime vs sim; sim-vs-actual DPS **as own trend only** with the Patchwerk caveat sentence; ids normalised via oracle `Replaces` | M | opus |
| P4.5 Tests + verification + docs | — | — | fixture-only tests, `skipif(not SIMC_BIN)` for the single live smoke test; captures; docs | S | opus |

**Risks:** misleading numbers on movement bosses (mitigated by own-trend-only presentation and the caveat), build burden per patch,
experimental specs, crafted-stat decoding, race config drift. **Dependencies:** Phase 2 (casts, buffs, oracle traits).

### Phase exit criteria (the orchestrator checks these against the verification report before closing a phase)

| Phase | Exit criteria — all must hold, with raw output in the verification report |
|---|---|
| 0 | `pytest -q` green; fixture build console shows **0** API calls on the fixtures re-recorded once after P0.8 (they carry `wipeCalledTime`); the leak test passes; one real build's console shows the per-request Δpoints lines and the run-end "points this run" line; `06-live-probe.md` exists with a decision for P0.8, the casts page count and the `archiveStatus` results; `slim()` runs on the current fixtures; the tagged `docs/CHANGES_<date>.md` entry and the `CLAUDE.md` update exist (P0.D) |
| 1 | the card renders for every player in the fixture (quickjs test iterates all labels); anonymous build: no player name in the Players-tab team strip or on Home, roster table alphabetical (tests); payload per pull ≤ baseline + 0.8 KB base64; screenshots at 1440 and 390 px show blocks 1–4 and 7–9 without overflow; `CLAUDE.md` §7 describes the Players tab card |
| 2 | one real build fetches casts for a changed (live) report and re-downloads only its new fights (console `[changed since last run …]` + request counts); cast efficiency and downtime render for ≥ 3 specs including one healer and one tank on the fixture; every death in the fixture carries `rd`; payload per pull ≤ baseline + 2.6 KB base64; the `buffs`-string cross-check (P2.11) is recorded; the oracle-missing build renders the documented empty states |
| 3 | `tankbusters.json` for the current prog boss reviewed by the user; the digest text for one real night approved by the user before the first `--summary` post; `player_history.json` survives two consecutive builds (merge test) |
| 4 | with `simc` absent no sim section is rendered (the HTML is byte-identical to a Phase 3 build apart from the footer timestamp) and the "simc not found" hint is on the console only; with it present, sim rows appear for DPS/tanks only and the Patchwerk caveat sentence is on the card |

### Ordering (Gantt-like)

| Slot | Work | Depends on |
|---|---|---|
| 1 | P0.1 · P0.2 · P0.3 · P0.5 · P0.6 (parallel) | — |
| 2 | P0.4 · P0.7 · P0.9 (parallel) | slot 1 |
| 3 | P0.8 (`wipeCalledTime` always; FIGHTS+PHASES merge only if P0.7 says so) | P0.7 |
| 4 | the user re-records the fixtures **once** (every Phase 0 query-text change is in); then P0.V · P0.D | P0.6, P0.8 |
| 5 | P1.1 (fable) · P1.3 (parallel) | re-recorded fixtures |
| 6 | P1.2 · P1.4 · P1.6 (parallel) | P1.1 |
| 7 | P1.5a (fable) | P1.1, P1.4 |
| 8 | P1.5b · P1.8 (parallel) | P1.5a, P1.6 |
| 9 | P1.7 · P1.9 · P1.V · P1.D | P1.5b |
| 10 | P2.1 · P2.4 · P2.10 (parallel) | Phase 0; P2.10 needs the oracle for validation → runs after P2.4's loader |
| 11 | P2.2 · P2.3 · P2.5 · P2.6 (parallel) | P2.1, P2.4 |
| 12 | P2.7 · P2.11 | P2.2, P2.3, P2.5, P2.6 |
| 13 | P2.8a · P2.8c · P2.9 (parallel) | P2.7 |
| 14 | P2.8b · P2.8d (parallel) | P2.8a (`cdTimeline()`) |
| 15 | P2.V · P2.D | P2.8a–d |
| 16 | P3.1 · P3.3 · P3.4 · P3.6 · P3.7 · P3.9 · P3.11 (parallel) | Phase 2 |
| 17 | P3.2 · P3.5 · P3.8 · P3.10 | P3.7 (history for the digest), P3.1, P3.4 (`heal:v1` for P3.10) |
| 18 | P3.V · P3.D | — |
| 19+ | Phase 4 (only if Q1 says so): P4.1 → P4.2 → P4.3 → P4.4 → P4.5 | Phase 2 |

---

## 9. Decisions for the user

| # | Question | Options | Recommendation | If you choose otherwise |
|---|---|---|---|---|
| **Q1** | How much SimC? | (a) none · (b) spell-data oracle only · (c) + per-player baseline sims · (d) + sim-vs-actual | **(b) now (Phase 2), (c)+(d) as opt-in Phase 4**; never APL comparison or stat weights | (a): Phase 2 loses cast efficiency, downtime and readiness for all specs (they need cooldown/GCD data WCL lacks); a hand-written per-spec cooldown list would replace the oracle — the maintenance liability the brief rejects. (c)/(d) now: adds the Linux build and profile-generator work before the casts pipeline exists to compare against; healers gain nothing. |
| **Q2** | Where does the view live? | (i) Players tab card · (ii) new "My raid" tab · (iii) boss-tab focus block | **(i) + keep (iii) as per-boss drill-down** (§7.1) | (ii): + one tab button and mobile option, duplicate wiring (~2 extra sub-agent-days), no functional gain. (iii) only: no cross-boss "how did my night go", and the boss tab grows further. |
| **Q3** | Public vs private content | (a) everything public · (b) rules in §7.7 (card behind the filter, own/role baselines, ≤ 3 Watch; sorted lists and same-spec only in `named`) · (c) per-player content only in `named` | **(b)** | (a): the Discord build becomes the "wall of shame" surface the research warns about (`05` §5). (c): raiders cannot see their own card without the RL sending it; the motivating loop is lost. |
| **Q4** | Payload strategy | (a) precomputed per-player vectors (`PM_COLS`, §6.10) + tracked-spell timelines (≈ +0.6 MB/month for Phases 1–3, §7.4; budget ≤ +0.7 MB) · (b) raw casts in the HTML (+6–9 MB/month, client-side timelines for everything) | **(a)** | (b) exceeds Discord's 10 MB alone in a long month and doubles load time; only viable with hosting (Roadmap 3.6), and even then the JS would re-implement the cooldown engine. |
| **Q5** | Per-spec knowledge we maintain | (a) none (spec-agnostic only) · (b) the five small configs of Phases 1–3 (+ `simc.json` in Phase 4) + generated tables (§6.5) · (c) + per-spec rotational/buff lists | **(b)** | (a): no tank AM/T4, no healer CD list (H2/H3), no externals — the tank and healer verticals shrink to T2/T3/H1. (c): the WoWAnalyzer maintenance treadmill (`02` §6); reject unless a maintainer volunteers. |
| Q6 (new) | Persist per-player history across builds (`data/player_history.json`)? | yes (Phase 3) · no (own history = the build's date range) | **yes**, Phase 3 | no: trends are limited to ~4 nights; the card's deltas reset every build. |
| Q7 (new) | Re-record the test fixtures once, after P0.6 and P0.8? | yes (user runs `make_fixtures.py`, network) · no | **yes**, once, before Phase 1; if the fixture report is archived (P0.7 `archiveStatus`), pick a new one (all fixture expectations change, +1 S task) | no: Phase 1 features that read gear/`buffs`/`abilities` can only be unit-tested on synthetic data; the offline build test cannot cover them. |
| Q8 (new) | Whole-fight casts for which pulls? | all pulls · kills + best N wipes per boss | **all** (≈ 1–2 pages per pull, estimated) — revisit after P0.7 measures points and pages | kills-only: wipes (74 % of pulls) lose cooldown/downtime/readiness insight; prog feedback is mostly about wipes. |
| Q9 (new, only if Q1 includes sims) | How to get `simc`? | build from source (cmake, no Qt) · Docker image · both | build from source (`-DBUILD_GUI=OFF -DSC_NO_NETWORKING=ON`), Docker as fallback | Docker only: adds a runtime dependency to the systemd timer host. |
| Q10 (new) | Is it acceptable that the named-build rollups are static (do not follow the toolbar filters), like the Raid tab? | yes · no (JS-render them from the payload with a `named` flag) | **yes** for Phases 1–3, and the rollups reuse the precomputed severities (§7.3) | no: +2–3 sub-agent-days in Phase 1 and the rollup logic lives in JS. |

---

## 10. Honest limits and risks

**What WCL cannot give.** No cooldown, GCD, charges or cast time (`04` §7) — hence the oracle. No cooldown reductions or resets (an
Anger-Management-style CDR, proc resets) — every tool hand-codes them; we show a tolerance band and "≈". Positions only as `x/y` on the
actor's own events with `includeResources` (not fetched; no movement analysis). Wipes are never ranked; hidden-parse characters are absent
from rankings; only kills have `rankPercent`/`bracketPercent`. 19 % of cached deaths have no `killingBlow`. Deaths-table `events[]` hold at
most the last 3 hits (we use our own recap from damage-taken events). `dataType: Buffs` with `targetID` leaks the actor's outgoing buffs
(fixed in Phase 0). The `buffs` string is present on ≈ 86 % of damage events (`04` §2: 20,032 of 23,184 sampled) and probably a
**subset** of auras (inferred) → hits without it are excluded (§6.10), Phase 2 cross-checks it. `wipeCalledTime` exists only when the
wipe is called in the Companion app (`04` §7); other wipes count every death and hit until the fight ends.
Filtered event queries may paginate early (`04` S18). Point costs are unpublished; the free tier is 3,600 points/hour, and the client cannot
wait out an exhausted hour today (`04` §5). **Archived reports** are inaccessible without a subscription (`archiveStatus`, `04` §5): the disk
cache is the only copy of old nights — the pruning task must never delete current-version files, and the cache directory should be backed up.
Phase 2 casts cannot be back-filled for archived reports, and the fixture report may itself be archived (P0.7 checks `archiveStatus`).

**What SimC cannot give.** No healer APLs (only Restoration Druid); Patchwerk has no movement, adds, deaths, intermissions or externals;
reality sits anywhere between 65 % and 98 % of sim depending on the boss; race and crafted stats are not in WCL; Midnight/Devourer specs may
be experimental; Linux needs a source build (`03` §1, §5, §6).

**What needs per-spec knowledge and will drift each patch/tier.** Tank AM and major-CD ids (6 specs), raid CD / external / lust ids
(~35), defensive ids (~40), tank-buster names per boss (per tier, same as `avoidable.json`), consumable/rune names (already a `[TODO]`),
gear-check slots per expansion, the spec table when a spec is added, the oracle (regenerate per patch). Each is a small file with an
`.example.json`; `validate_config` and `abilities_seen.json` are the review tools.

**Modelling limits.** GCD downtime ignores haste procs except the lust family → a few % error; suppressed when the model overlaps
more than 2/min (WoWA's rule). Cast efficiency over-estimates "possible casts" for talents that add charges/CDR → band + marker. "Alive time" in Phase 1
= time to first death (resurrections detected only from Phase 2 casts). WCL's `activeTime` definition is WCL's, fine for relative use.
Identity is the `Labeller` label (name, realm): renames and transfers break own history (Q6 file needs a manual alias map, `[TODO]`).
Support specs (Augmentation): WCL's rDPS attribution is not read, so they are excluded from role medians and get a Note (§6.3).

**Operational risks.** API budget exposure grows with Phase 2 (+30 % requests; points unknown until measured). Cache grows ≈ 65–90 MB/month
compact (§6.8). Fixtures grow to ~6.5 MB and must be re-recorded per query change (network, user-run). The oracle needs a ~30 MB sparse checkout
of SimC per patch.

**The "wall of shame" risk.** A public file with names plus judgement is a step beyond WCL's own exposure (`05` §5). Mitigations are
structural, not tonal only: nothing per-name renders until a name is chosen; comparisons are own-history first; caps on Watch items; no
ranked roster in the public build (the roster table is alphabetical); the digest names nobody; the RL build is the only place for rankings and is not posted. The user should
announce the card to the raid before the first post (raider.io's "codify expectations so metrics never feel like a surprise").

---

## 11. Appendix

### 11.1 Research index (`docs/research/2026-09-25-player-analysis/`)

| File | One line |
|---|---|
| `00-brief.md` | The orchestrator's brief: user words, assumptions, hard/soft constraints, five open questions, success criteria. |
| `01-codebase-inventory.md` | Exact per-player data, verbatim queries, batching, cache keys/sizes (962 MB), payload budget (5.9 KB/pull), Players tab today, config conventions, extension points with `file:line`, fixture mechanics, helper index. |
| `02-wowanalyzer.md` | Architecture, spec-agnostic modules with thresholds, normalizer pitfalls, guide UI components, spell-data sources, AGPL implications, support matrix (17 Full / 16 Partial / 6 Foundation / 1 Unmaintained), feasibility table for a Python port. |
| `03-simulationcraft.md` | SimC state (midnight, 12.1.0), Linux build/Docker, WCL→SimC profile mapping (talent ids match), `json2` fields for baselines, `SpellDataDump` as an offline oracle, APL verdict (infeasible), integration options ranked (oracle → baselines → sim-vs-actual). |
| `04-wcl-api.md` | `events`/`table`/`playerDetails`/`rankings` capabilities, event shapes from the cache, measured volumes per pull, rate limits (3,600 points/h, cost unpublished), pitfalls (Buffs `targetID` leak, no `nextPageTimestamp` on aliases, quoting, fight-relative filter timestamps), cheap/moderate/expensive classification, "verify with one live call" list. |
| `05-insight-catalogue.md` | Landscape (WCL Problems tab, Wipefest, Archon, Raidbots, WoWAnalyzer, Warcraft Insights, Mr. Mythical, WowCoach, Carried.io), per-role metric catalogue with thresholds, baselines without spec knowledge, presentation patterns, the three tone rules, 15-item prioritised shortlist. |
| `06-live-probe.md` (Phase 0 output) | Results of the one-call verifications: table shapes, `includeResources` keys, `playerDetails` fields, pagination, Δpoints per query kind, whole-fight casts volume, `archiveStatus`, Interrupts-table semantics. |
| `docs/reviews/REVIEW_2026-09-25-player-analysis-design.md` (outside this folder) | Design review of this document (45 findings F1–F45: 1 blocker on effort totals, 17 major, 27 minor; 35-claim evidence spot-check); all findings applied on 2026-09-25. |

### 11.2 Glossary

| Term | Meaning here |
|---|---|
| Active time | WCL's per-player `activeTime` in the DamageDone/Healing tables ("percent of the time the player is using abilities"); Phase 2 adds the WoWAnalyzer-style GCD union. |
| Active DPS / HPS | `total ÷ active_seconds` (already in the dashboard), used for consistency and role comparisons because it neutralises assignment differences. |
| Alive time | Seconds from pull start to the player's first death (Phase 1) or until the last event before a death without a later cast (Phase 2). |
| AM (active mitigation) | The short, frequently re-applied tank buff that reduces or absorbs damage (Shield of the Righteous, Ironfur, Shuffle, Demon Spikes, Bone Shield, Ignore Pain/Shield Block); "AM at hit" = the aura id is in the `buffs` string of the damage event. |
| Bracket percentile | WCL `bracketPercent`: rank among same-spec parses in the same item-level bracket (≈ 3 ilvls wide), kills only; `rankPercent` is the all-bracket percentile. |
| Cast efficiency | WoWAnalyzer's `timeUnavailable ÷ fightDuration` for a cooldown (time on cooldown + casting + waiting on the GCD); 0.80 recommended; "possible casts" is the integer form: `charges + floor((fight_s − t0)/cd_s)`, capped at WoWA's `floor(rawMaxCasts) + 1` (D2). |
| Cooldown timeline (`cdt`) | Per pull, per tracked spell, the list of cast timestamps (deciseconds) from which the browser draws cast ticks, cooling segments and gaps. |
| Downtime / small gaps | 1 − active-time share from the GCD union; small gaps = 100–2,250 ms pauses between active segments, per minute. |
| External | A defensive buff cast on someone else (Pain Suppression, Ironbark, Blessing of Sacrifice, Life Cocoon, Guardian Spirit, Power Infusion for throughput). |
| Fake cast | WCL `fake: true` on a cast event: not a player action (procs, game-made casts); excluded from counts. |
| Good / Watch / Note | The card's three-level usage scale (WoWAnalyzer Perfect/Good/Ok/Fail collapsed; no "Fail"); Note = informational or thin history. |
| Named build | `--callouts named` / `HOME_CALLOUTS=named`: the private raid-lead build that may name players in rollups (`dash/home.py:117-118`). |
| Oracle (`spell_oracle.json`) | Locally generated table of cooldown, charges, GCD, cast time, channel flag, category cooldown and modifier pointers per spell id, parsed from SimC's `SpellDataDump`. |
| Own history | Median over the player's nights before the latest selected night (≥ 2 needed, §7.3); nights inside the build (and, with Q6, `data/player_history.json`). |
| Pre-pot | A combat potion used in the window 5 s before → 1.5 s after the pull (`PREPOT_BEFORE_MS/AFTER_MS`). |
| Readiness | Whether a defensive cooldown was available (per the cooldown engine) at the moment of a death. |
| Role median | Median over the other players of the same role (dps / healer / tank) in the same pull, then over pulls; ≥ 3 others (tanks → co-tank); players with < 25 % of the pulls and support specs excluded (§7.3). |
| Tank buster | A boss ability aimed at tanks that is expected to be taken with AM or a major cooldown; listed per boss in `tankbusters.json`. |
| Tracked spells | Chosen per player per build: the top 6 by cooldown of the spells the player cast with oracle `max(cd, category_cd) ≥ 45 s`, plus every configured raid CD / defensive the player cast; stable across pulls (§6.10). |
