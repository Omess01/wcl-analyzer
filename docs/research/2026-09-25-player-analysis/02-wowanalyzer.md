> Research input (2026-09-25) to `docs/plans/2026-09-25-player-analysis-design.md`; copied unchanged from the session scratchpad apart from this header line.

# WoWAnalyzer — what it does and how (catalogue for the per-player analysis design)

Research date: 2026-09-25. Everything marked **[verified]** was read in the WoWAnalyzer source at the
default branch `midnight`, commit `a23f33a32513cc2d643589a1e01d63e04f8571b3` (pushed 2026-09-25T15:12Z;
https://api.github.com/repos/WoWAnalyzer/WoWAnalyzer/branches/midnight). File links below use the short-SHA
permalink base `https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/`. Statements marked **[inferred]** are my
reading of the code or of WCL behaviour, not something the repo states. Repo: https://github.com/WoWAnalyzer/WoWAnalyzer
(599 stars, AGPL-3.0, "WoWAnalyzer is a tool to help you analyze and improve your World of Warcraft raiding
performance through various relevant metrics and gameplay suggestions."). Wiki index:
https://github.com/WoWAnalyzer/WoWAnalyzer/wiki (pages: Home, Abilities, Abilities Generator (WIP), APLCheck,
Combat Log Events, Core Tools Everyone Should Know, Death recap, EventLinkNormalizer, GCD Errors, Making a module,
Suggestions, Updating the Spellbook, …).

Fetch failures: none of the files I needed 404'd except two guesses (`warrior/fury/spell-list_*.retail.ts`,
`warrior/fury/gen.ts`) that simply do not exist (Fury uses a hand-written `modules/Abilities.ts`). The wiki "Core Tools"
and "Combat Log Events" pages loaded only partially through the fetch tool.

---

## 1. Architecture in one page

**Pipeline [verified]** (`src/interface/report/hooks/useEvents.ts`, `useEventParser.ts`, `src/parser/core/CombatLogParser.tsx`):

1. Events for *one player in one fight* are downloaded (see §3 for the request shape) and handed to a
   `CombatLogParser` constructed with `(config, report, selectedPlayer, selectedFight, playerCombatantInfo, characterProfile, playerDetails)`
   — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/core/CombatLogParser.tsx.
2. The constructor instantiates every module in `internalModules + defaultModules + specModules` through a small
   dependency-injection loop (`initializeModules`: a module is created only after all classes named in its
   `static dependencies` exist; up to 100 passes; `priority` = load order so dependencies always run first).
3. `parser.normalize(events)` runs every active module that `instanceof EventsNormalizer`, sorted by priority, each
   returning a new event array; the result is sorted by timestamp (`useEventParser.ts`).
4. `EventEmitter.triggerEvent(event)` is called for each normalized event in batches (~66 ms of work per idle
   callback); listeners are invoked in module-priority order; an exception in a listener disables that module and
   everything depending on it (`deepDisable`).
5. `generateResults()` collects `statistic()` / `tab()` output from every `Analyzer`; `buildGuide()` renders the
   spec's `static guide` React component with `{modules, info, events}`.

**Base classes [verified]**

| Class | File | Role |
|---|---|---|
| `Module` | `src/parser/core/Module.ts` | `static dependencies = {name: Class}`, `active`, `priority`, `owner` (the parser), `selectedCombatant` |
| `EventSubscriber` | `src/parser/core/EventSubscriber.ts` | `addEventListener(filter, listener)` forwarding to the parser's `EventEmitter` |
| `Analyzer` | `src/parser/core/Analyzer.ts` | adds `statistic()`, deprecated `tab()`, typed `deps`, `Analyzer.withDependencies({...})`; `SELECTED_PLAYER = 1`, `SELECTED_PLAYER_PET = 2` |
| `EventsNormalizer` | `src/parser/core/EventsNormalizer.ts` | abstract `normalize(events): events`; helper `getFightStartIndex` (first non-`combatantinfo` event) |
| `EventEmitter` | `src/parser/core/modules/EventEmitter.ts` | keeps listeners per event type; compiles `by/to/spell` filters into wrapper closures; `fabricateEvent()` |

**Events selector API [verified]** — `src/parser/core/Events.ts` exposes `Events.cast`, `Events.begincast`,
`Events.applybuff`, `Events.damage`, `Events.heal`, `Events.fightend`, `Events.GlobalCooldown`, `Events.EndChannel`,
`Events.UpdateSpellUsable`, `Events.any` … each returning an `EventFilter(eventType)`
(https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/core/EventFilter.ts) with three chainable
constraints: `.by(SELECTED_PLAYER | SELECTED_PLAYER_PET)` (sourceID is the player / one of the player's pets),
`.to(...)` (targetID likewise) and `.spell(SPELL | SPELL[])` (`ability.guid` equals one of the ids; passing a raw
number throws). `EventEmitter._prependFilters` wraps the listener in `by` → `to` → `spell` checks. The `EventType` enum
lists the real WCL types (`begincast, cast, damage, heal, absorbed, healabsorbed, applybuff, applydebuff,
applybuffstack, removebuffstack, refreshbuff, removebuff, summon, resourcechange, interrupt, death, resurrect,
combatantinfo, instakill, aurabroken, empowerstart/end, …`) and WoWA-fabricated ones (`fightend, globalcooldown,
beginchannel, endchannel, cancelchannel, updatespellusable, changehaste, changestats, phasestart/end, freecast,
maxchargesincreased/decreased, …`). Every event may carry `prepull`, `__fabricated`, `__modified`, `__reordered`,
`_linkedEvents`.

**`Abilities` / `Ability` [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/core/modules/Ability.ts
and `.../Abilities.ts`. A spec overrides `spellbook(): SpellbookAbility[]` (computed once, at construction, so anything
dynamic must be a function). Entry fields:

| Field | Meaning (from the doc-comments) |
|---|---|
| `spell: number \| number[]` | required; an array ties several cast/buff ids to one ability with a shared cooldown; first id is primary |
| `category` | required; `SPELL_CATEGORY.ROTATIONAL, ROTATIONAL_AOE, ITEMS, COOLDOWNS, DEFENSIVE, SEMI_DEFENSIVE, OTHERS, UTILITY, HEALER_DAMAGING_SPELL, CONSUMABLE, HIDDEN` (`src/parser/core/SPELL_CATEGORY.ts`) |
| `cooldown?: number \| (haste) => number` | **seconds**, evaluated at cast time with current haste (20 % haste is passed as 1.20 per the comment; code divides by `(1 + haste)` where haste is 0.20 — see Fury: `cooldown: (haste) => 8 / (1 + haste)`) |
| `charges?: number \| (combatant) => number` | default 1; "only 1 charge will recharge at a time" |
| `gcd` | `null` = off the GCD; `{ static }` fixed ms; `{ base, minimum? }` hasted (`base / (1+haste)`, floor `minimum` or 750 ms); or a function of the combatant |
| `castEfficiency` | `{ suggestion, recommendedEfficiency (default 0.8), averageIssueEfficiency, majorIssueEfficiency, extraSuggestion, casts (deprecated), maxCasts (deprecated), importance }` |
| `enabled` | hide talents the player does not have (`combatant.hasTalent(...)`) |
| `buffSpellId` | deprecated, replaced by the `Auras` module (`docs/Buffs.md`) |
| `timelineSortIndex`, `timelineHide`, `timelineCastableBuff` | timeline lane ordering / hiding |
| `damageSpellIds`, `healSpellIds`, `primaryCoefficient`, `range` | link cast id → damage/heal ids (used by pre-pull detection); coefficient / range metadata |
| `isDefensive`, `isEmpower`, `isUndetectable` | defensive flag (death recap), Evoker empowers, racials that cannot be detected from talents |

`Abilities.getExpectedCooldownDuration(id)` = `round(ability.getCooldown(haste.current) * 1000)` ms;
`getMaxCharges(id)`; `increaseMaxCharges/decreaseMaxCharges` fabricate `MaxChargesIncreased/Decreased` and inform `SpellUsable`.

**`SpellUsable` — cooldown tracking [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/modules/SpellUsable.tsx.
Listens to `Events.cast.by(SELECTED_PLAYER)` (and `prefiltercd`), `Events.any`, `ChangeHaste`, `fightend`. Per
canonical spell id it keeps `CooldownInfo {overallStart, chargeStart, currentRechargeDuration, expectedEnd,
chargesAvailable, maxCharges}`:

* `beginCooldown(castEvent)`: no entry → create one with `expectedEnd = t + expectedCooldown`, `chargesAvailable = max-1`,
  fabricate `UpdateSpellUsable(BeginCooldown)`; entry with charges left → `chargesAvailable -= 1`, `UseCharge`; entry with
  no charges (cast while "on cooldown" = tracking error) → end the old cooldown and start a new one (counted in
  `cooldownErrorCount`, exported as `serverMetrics.cooldownErrorRate`).
* `onEvent` (every event): any `expectedEnd <= now` → `endCooldown(id, expectedEnd, resetCooldown=true)` which restores a
  charge (`RestoreCharge`) or deletes the entry (`EndCooldown`).
* `onChangeHaste`: for hasted cooldowns the remaining time is rescaled keeping the **percentage** of progress
  (`_handleChangeRate`, worked example in the comment); `applyCooldownRateChange` handles "modRate" effects the same way;
  `reduceCooldown(id, ms)` applies flat CDR (divided by modRate, not by haste), carrying overflow into later charges.
* `onFightEnd` closes every open cooldown at its expected end. Spells with no `Abilities` entry or no cooldown are ignored
  (`unknownAbilityErrorCount`).

**`CastEfficiency` [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/modules/CastEfficiency.tsx.
Depends on `SpellHistory` (per-spell list of cast/begincast/UpdateSpellUsable events). For each active ability:

* `casts` = number of `cast` events (or `empowerend` for empowers); `cpm = casts / minutes`.
* `completedRechargeTime` = sum of (BeginCooldown → EndCooldown/RestoreCharge) durations; `recharges` = their count;
  `averageCooldown = completedRechargeTime / recharges` (observed, so haste/CDR are already baked in).
* `rawMaxCasts = fightDuration / (averageCooldown + averageTimeSpentCasting + averageTimeWaitingOnGCD) + charges - 1`
  (fallback `fightDuration / cooldownMs + charges - 1` when the spell never recharged); `maxCasts = floor(raw) + 1`.
* **`efficiency` is time-based, not casts/maxCasts**: `timeUnavailable = timeOnCooldown (completed + current) + timeSpentCasting + timeWaitingOnGCD`;
  `efficiency = timeUnavailable / fightDuration` (`casts / rawMaxCasts` is only used when a spec supplies the deprecated `maxCasts`).
* Thresholds: `recommendedEfficiency` default `0.8`; `averageIssueEfficiency = recommended - 0.05`; `majorIssueEfficiency = recommended - 0.15`;
  `gotMaxCasts = casts === maxCasts` suppresses the complaint; `canBeImproved = suggestion && efficiency < recommended && !gotMaxCasts`.
* `_getTimeWaitingOnGCD` comes from `UpdateSpellUsable.timeWaitingOnGCD` filled by the enhancer
  `src/parser/shared/enhancers/SpellTimeWaitingOnGlobalCooldown.ts` (time after a cooldown ends that the player was still locked by a GCD).

**`GlobalCooldown` [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/modules/GlobalCooldown.tsx.
`calculateGlobalCooldown(haste, baseGcd = 1500, minGcd = 750) = max(min(base, min), base / (1 + haste))` (classic floor 1000 ms).
A `globalcooldown` event is fabricated on `cast` for instants (ignoring `CASTS_THAT_ARENT_CASTS` and casts that finish a
channel of the same spell) and on `beginchannel` for cast-time spells (not if the cast was cancelled); it is attached to
the cast as `event.globalCooldown`. `_verifyAccuracy`: a GCD starting while the previous one still had > 150 ms left is an
error; `isAccurate = errorsPerMinute < 2` — `AlwaysBeCasting.statistic()` returns nothing when the GCD model is inaccurate.

**`Channeling` normalizer [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/normalizers/Channeling.ts.
Fabricates `BeginChannel`/`EndChannel` for cast-time spells (from `begincast` → `cast`; a `begincast` without matching
`cast` gets `isCancelled`) and for channels, which "are handled inconsistently in the events": a hard-coded `CHANNEL_SPECS`
table says per spell whether the channel is delimited by its buff (`buffChannelSpec`: Eye Beam, Evocation, Divine Hymn,
Mind Flay, Fists of Fury, Rapid Fire, Bladestorm, Convoke…), by the next cast (`nextCastChannelSpec`: Arcane Missiles,
Penance), both, or by empower events.

**`AlwaysBeCasting` [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/modules/AlwaysBeCasting.tsx.
Active time = union of intervals `[gcd.timestamp, gcd.timestamp + gcd.duration]` (from `globalcooldown` events) and
`[channel.start, channel.end]` (from `endchannel` events), built with a sweep over sorted edges. `activeTimePercentage =
activeTime / fightDuration`; `downtimePercentage = 1 - active`. Thresholds: downtime `isGreaterThan {minor 0.05, average 0.10, major 0.15}`
→ `DowntimePerformance` Perfect (0 %) / Good (≤ 5 %) / Ok (≤ 10 %) / Fail; "small gaps" (100–2250 ms between active
segments) `isGreaterThan {6, 8, 10}` per minute. Healer subclass `AlwaysBeCastingHealing.tsx`: non-healing time
`isGreaterThan {0.30, 0.40, 0.45}`, downtime `{0.20, 0.35, 1}`; `isHealingAbility()` is overridden per spec. Statistic text:
"Downtime is available time not used to cast anything (including not having your GCD rolling). This can be caused by
delays between casting spells, latency, cast interrupting or just simply not casting anything (e.g. due to movement/stunned)."

**`Haste` [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/shared/modules/Haste.ts.
Starting haste comes from `CombatantInfo` via `Combatant.buildPullStats` (`haste = max(hasteSpell, hasteMelee, hasteRanged)`,
`src/parser/core/Combatant.ts` l.103-129) converted with `StatTracker.statBaselineRatingPerPercent` (crit 46, haste 44,
mastery 46, versatility 54 rating per 1 % at level cap, "Values taken from simulationcraft … sc_scale_data.inc", plus
diminishing-return brackets from `item_scaling.inc`; `src/parser/shared/modules/StatTracker.ts` l.163-200). During the
fight a hard-coded table `DEFAULT_HASTE_BUFFS` (Bloodlust family, Berserking 10 %, Metamorphosis 25 %, Furious Gaze 10 %,
Power Infusion 20 %, Bone Shield 10 %, stacking buffs …) applies on `applybuff/removebuff/changebuffstack`, fabricating
`changehaste` events that `SpellUsable` and `GlobalCooldown` consume. `[inferred]` A Python port that ignores haste buffs
will mis-time hasted cooldowns and GCDs by up to the buff percentage; WCL's own `hasteSpell` etc. in `combatantinfo` is the
pull value only.

---

## 2. Spec-agnostic (shared/core) analyzers

Legend for "needs": **(a)** nothing spec-specific · **(b)** a per-spec ability list (cooldowns / GCD / categories) ·
**(c)** deep spec logic or per-boss config. All rows **[verified]** from the files under
https://github.com/WoWAnalyzer/WoWAnalyzer/tree/a23f33a/src/parser/shared and `/src/parser/core` unless noted. The
default module list is `CombatLogParser.defaultModules` (normalizers, enhancers, analyzers, "tabs", racials, items).

| Module (file) | What it computes | WCL events it needs | Needs |
|---|---|---|---|
| `Abilities` (core/modules/Abilities.ts) | the spellbook: cooldown, charges, GCD, category per ability | none (config) | (b) — it *is* the spec knowledge |
| `Auras` (core/modules/Auras.ts, docs/Buffs.md) | which buffs to track/show; `triggeredBySpellId` feeds pre-pull detection | applybuff/removebuff/applydebuff/removedebuff | (b) |
| `SpellUsable` (shared/modules/SpellUsable.tsx) | cooldown state, charges, `UpdateSpellUsable` events, CDR/modRate | cast (+ fabricated changehaste) | (b) |
| `SpellHistory`, `CooldownHistory` | per-spell event history; query "was X on cooldown at t" | cast/begincast/UpdateSpellUsable | (b) |
| `CastEfficiency` (shared/modules/CastEfficiency.tsx) | casts, max possible casts, time-based efficiency, thresholds | cast/begincast + SpellUsable | (b) |
| `GlobalCooldown` | fabricates GCD events from haste and per-ability gcd config; accuracy check | cast, beginchannel | (b) (which spells are off-GCD) |
| `Channeling` (normalizer) | BeginChannel/EndChannel, cancelled casts flag | begincast/cast/applybuff/removebuff | (a) + a global special-case table |
| `AlwaysBeCasting` / `AlwaysBeCastingHealing` | active time %, downtime %, small gaps/min; healing vs non-healing time | GCD + channel events | (b) via GCD; healing split needs a heal-spell list |
| `CancelledCasts` (shared/modules/CancelledCasts.tsx) | `castsCancelled / (cancelled + finished)`; thresholds `isGreaterThan {0.02, 0.05, 0.15}`; `cancelGaps` for the timeline | begincast, cast, empowerstart/end | (a) (+ `CASTS_THAT_ARENT_CASTS`, `CASTABLE_WHILE_CASTING_SPELLS` lists) |
| `Haste`, `StatTracker` | current haste; all stats over time from CombatantInfo + buff table + rating→% tables | combatantinfo, applybuff/removebuff/changebuffstack | (a) for pull stats, (b/c) for buff values |
| `Combatants`, `Enemies`, `Pets`, `Entities`, `Entity`, `Combatant` | per-actor buff/debuff tracking (`hasBuff(id, t, bufferMs)`, `getBuffUptime`), gear/talent/trinket accessors (`getGear`, `hasTalent`, `has2PieceByTier`, `ilvl`) | applybuff…removedebuffstack **by or to the player/pets only** (`Entities.applyBuff` early-returns otherwise); combatantinfo | (a) |
| `DeathTracker` (shared/modules/DeathTracker.tsx) | deaths, resurrections, `timeDeadPercent`; threshold `isGreaterThan {major: 0}` (any time dead is major) | death/resurrect to player; cast/heal/damage after death = resurrected | (a) |
| `DeathRecapTracker` / `DeathRecap` (.jsx) | last damage/heal events before each death with HP, which defensive cooldowns were **ready** (`SpellUsable.isAvailable` for `DEFENSIVE`/`SEMI_DEFENSIVE`/`isDefensive` abilities) and which defensive buffs were active (`DEFENSIVE_BUFFS` externals list + Auras) | damage/heal/instakill/death to player | (b) for "cooldown was available" |
| `DeathDowntime`, `TotalDowntime` (downtime/*.jsx) | ms spent dead; `fightDuration` can exclude it (`adjustForDowntime`) | death/resurrect/cast | (a) |
| `DispelTracker` | dispel counts | dispel | (a) |
| Interrupts | **no shared module**; interrupts are per-spec analyzers only [verified: no file under shared matches] | interrupt | — |
| `DamageDone`, `HealingDone`, `DamageTaken`, `ThroughputStatisticGroup` (throughput/*) | totals by ability/second; `HealingValue {effective, overheal, absorbed}` — heal events, `absorbed` events and leftover shield on `removebuff.absorb` (counted as overheal); `DamageDone` also fetches WCL's `report/tables/damage-done` to compare | heal/absorbed/removebuff by player+pets; damage by / to player | (a) |
| `HealingEfficiencyTracker` + `ManaTracker` (core/healingEfficiency) | per spell: casts, healing, overhealing %, mana spent, HPM, DPM, time casting, HPET | heal/damage/cast (classResources) | (b) (which spells to list) |
| `ManaValues` (shared/modules/ManaValues.tsx) | mana over time from `cast.classResources` (amount − cost), lowest/ending mana; `manaLeftPercentage` `isGreaterThan {0.10, 0.20, 0.30}`; healers only | cast with classResources | (a) |
| `ManaLevelChart`, `ManaUsageChart` (resources/mana) | mana curve vs boss HP (boss HP fetched from WCL `report/graph/resources`) and mana-spent-vs-healing | cast classResources + WCL graph | (a) |
| `ResourceTracker`, `RegenResourceCapTracker`, `ResourceGraph`, `ResourceUsage` (resources/resourcetracker) | builders/spenders, generated, **wasted (overcap)** using `resourcechange.waste` and cast costs, time at cap, regen rate; 150 ms multi-update buffer because `classResources.amount` can be stale | resourcechange, drain, cast (classResources), damage (refund on miss/dodge/parry) | (b) (resource type, cap/regen rules per spec) |
| `SpellResourceCost`, `SpellManaCost` | attaches (talent-adjusted) resource cost to cast events | cast | (b) |
| `AbilityTracker` | per-spell casts / hits / damage / healing / mana | cast/damage/heal/absorbed | (a) |
| `EventHistory` | ring buffer of past events, `last(n, ms, filter)` | any | (a) |
| `FilteredActiveTime` | active time restricted to a spell whitelist | GCD events | (b) |
| `CooldownThroughputTracker` | damage/healing/mana done inside a cooldown window (`start`, `end`, summary types HEALING/OVERHEALING/ABSORBED/MANA/DAMAGE); built-in retail entry: Power Infusion | cast/applybuff/removebuff + damage/heal/absorbed | (b) (which cooldowns) |
| `BuffStackTracker`, `BuffCountGraph`, `BuffStackGraph`, `DebuffUptime` (`isLessThan {0.85, 0.80, 0.75}`), `HotTracker` (pandemic 1.3× rules) | buff stacks / counts over time; debuff uptime; HoT durations & refresh quality | applybuff/refreshbuff/removebuff(+stack) | (b) (which buff) |
| `EarlyDotRefreshes`, `EarlyDotRefreshesInstants` (earlydotrefreshes/) | refreshes with too much duration left ("clipping"); thresholds per spell via `makeSuggestionThresholds(spell, minor, avg, major)` | cast/applydebuff/refreshdebuff (+ movement for instants) | (c) (DoT durations) |
| `DotSnapshots` (core/DotSnapshots.ts) | which snapshot buffs were up when a DoT was applied (200 ms buffer, 30 % pandemic default) | applydebuff/refreshdebuff/removedebuff | (c) |
| `MitigationCheck` (shared/modules/MitigationCheck.jsx) | for boss abilities listed in the **encounter config** (`boss.fight.softMitigationChecks.physical/magical`) whether a mitigation buff/debuff was active when hit | damage to player | (c) per-boss + per-spec buff lists |
| `DistanceMoved` | distance travelled from `x/y` on the player's own events | cast/damage/heal/resourcechange with x,y | (a) |
| `EnemiesHealth`, `ExecuteHelper` | enemy HP tracking / execute windows | damage | (a) / (b) |
| `AoESpellEfficiency` | targets hit per AoE cast (`isLessThan {0.95, 0.90, 0.80}`) | cast + damage | (b) |
| `HitCountAoE` (core) | hits per cast for AoE abilities | cast/damage | (b) |
| `BaseHealerStatValues`, `CritEffectBonus` | healer stat weights | heal/absorbed/damage + StatTracker | (c) |
| `LowHealthHealing`, `RaidHealthTab` (features/) | healing on low-HP targets; raid HP graph (`RaidHealthTab` reads WCL tables) | heal with hitPoints/maxHitPoints | (a) |
| `VantusRune` | value of the Vantus rune buff | combatantinfo/applybuff | (a) |
| Preparation checkers — shared `FlaskChecker`, `FoodChecker` (tiered id lists, need `applybuff` with `prepull`), `EnchantChecker` / `GemChecker` / `WeaponEnhancementChecker` (read **`CombatantInfo.gear[].permanentEnchant`, gems, sockets**), retail `PotionChecker` (pre-pot = combat-potion `applybuff` with `prepull && timestamp <= fight.start - offset`, potions used vs `maxPotions`, weak vs strong list), `Potion`/`CombatPotion`/`HealthPotion`/`Healthstone` (5-min shared cooldown via `SpellUsable`; "Tracks Healthstone cooldown"), `AugmentRuneChecker` (`VOID_TOUCHED` buff, uptime %) | did the player start with flask/food/rune, potion count, enchants missing/not-max, gems, weapon enhancements | combatantinfo (auras + gear), applybuff, cast | (a) + per-expansion consumable/enchant id lists (`src/common/SPELLS/midnight/*`, `src/common/ITEMS/midnight/*`) |
| Item / trinket / embellishment analyzers (`src/parser/retail/modules/items/**`) | per-item damage/proc value (e.g. `SpymastersWeb`, `SignetOfThePriory`, enchants `AuthorityOfRadiantPower`) | damage/heal/applybuff | (c) per item |
| Racials (`shared/modules/racials/*`) | add racial abilities to the spellbook / cast efficiency | cast | (a) |
| `MeleeUptimeAnalyzer` (interface/guide/foundation/analyzers) | gaps between auto-attacks (`Melee` id 1; expected swing 800–4000 ms) for melee/tank/melee-healer specs; `isLessThanOrEqual {0.98, 0.90, 0.80}` | cast of spell id 1, endchannel | (a) |
| `DowntimeDebuffAnalyzer` (same folder) | segments where a **boss debuff from the encounter config** justifies downtime | applydebuff/removedebuff to player | (c) per boss |
| Functional metrics (`shared/metrics/*.ts`): `buffUptimeTotal`, `buffUptimeDistinct`, `buffApplications`, `castCount`, `resourceGained`, `resourceWasted` | pure `(events, info) => value` helpers | applybuff/removebuff, cast, resourcechange | (a) given a spell id |
| APL engine (`shared/metrics/apl/*`, `interface/guide/components/Apl`) | checks each cast against a priority list with conditions (`buffPresent`, `spellAvailable`, `hasResource`, `debuffMissing`, `spellCharges` …), reports dropped rules / over-cast fillers | all | (c) per spec APL |

Normalizers in `defaultModules`: `ApplyBuff`, `CancelledCasts`, `PrePullCooldowns`, `PhaseChanges`, `MissingCasts`,
`EmpowerNormalizer`, `Channeling`; internal: `FightEnd`, `FriendlyCompatNormalizer` (see §3).

---

## 3. Normalizers and pitfalls

**How events are requested [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/common/fetchWclApi.ts,
`src/common/makeWclApiUrl.ts`, `src/common/makeApiUrl.ts`, `src/interface/report/hooks/useEvents.ts`:

* WoWAnalyzer does **not** use the v2 GraphQL API in the client. It calls its own backend
  (`${VITE_SERVER_BASE}${VITE_API_BASE}v1/<endpoint>`) which proxies WCL **v1 REST**: `report/fights/<code>`,
  `report/events/<code>?start=<fightStart>&end=<fightEnd>&actorid=<playerId>&translate=true`, `report/tables/<table>/<code>`,
  `report/graph/resources/<code>`. Players for a fight come from its backend's `v2/report/<code>/fight/<id>/players`.
* `useEvents` loads **all events where the selected player is source or target** (that is what `actorid` does — `[inferred]`
  from WCL v1 semantics) with no `filter`, following `nextPageTimestamp` until it is absent. `fetchEvents(code, start, end, actorId?, filter?, maxPages = 3)`
  is the filtered variant used for combatant info (`filter: 'type="combatantinfo"'`), boss-phase detection (`makeWclBossPhaseFilter`)
  and guide side-queries (`useReportEvents(code, start, end, 'ability.id = 1 and source.type = "Player" and type = "cast"')`
  to estimate raid-wide melee uptime).
* Boss phases: preferred source is WCL's `fight.phases` metadata (`useBossPhaseEvents.tsx` → fabricated `phasestart/phaseend`),
  falling back to encounter-config filter expressions; `PhaseChanges` normalizer re-sorts the fabricated phase events.
* `[inferred]` WCL v2 `report.events(fightIDs, sourceID/targetID, dataType: All, includeResources: true)` returns the same
  event objects; the WoWA code base never references `useAbilityIDs` or `includeResources` (those are v2 GraphQL arguments).
  `translate: true` is used "to have 1 consistent language".

**Normalizers [verified]**

| Normalizer | File | What it fixes |
|---|---|---|
| `FightEnd` | shared/normalizers/FightEnd.ts | appends a fabricated `fightend` at `fight.end_time` so analyzers can flush state |
| `FriendlyCompatNormalizer` (priority −1000) | core/FriendlyCompatNormalizer.ts | fills missing `sourceIsFriendly` / `targetIsFriendly` / `attackerIsFriendly` from the `Enemies` list |
| `ApplyBuff` | shared/normalizers/ApplyBuff.ts | (1) for every `combatantinfo` event, each entry of `auras[]` that involves the player becomes a fabricated `applybuff` at `fight.start_time` with `prepull: true, __fromCombatantinfo: true`; (2) a `removebuff`, `applybuffstack`, `removebuffstack`, `refreshbuff` (or `FilterBuffInfo`) for a buff never seen applied also fabricates an `applybuff` at fight start (and an `applybuffstack` with the previous stack count). Doc-comment: "Some buffs like Bloodlust and Holy Avenger when they are applied pre-combat it doesn't show up as an `applybuff` event nor in the `combatantinfo` buffs array." |
| `PrePullCooldowns` | shared/normalizers/PrePullCooldowns.jsx | fabricates `cast` events **before** the pull for cooldowns detected from (a) pre-pull `applybuff`s whose `Auras` entry has `triggeredBySpellId`, (b) damage events whose id is in an ability's `damageSpellIds` without a preceding cast; timestamps are stacked backwards by GCD; class resources copied from the first real cast ("not pretty or 100% accurate"). Known limitation quoted in code: a long-duration buff cast well before the pull is assumed cast right before it, so the next real cast may look "still on cooldown". |
| `MissingCasts` | shared/normalizers/MissingCasts.ts | on-use items whose `applybuff` has no `cast` → fabricate a `cast` at the same timestamp (`static missingCastBuffs` list) |
| `MissingDotApplyDebuffPrePull` | shared/normalizers/MissingDotApplyDebuffPrePull.ts | a DoT ticking in the first 5 s without an `applydebuff` gets a fabricated `applydebuff` at fight start (otherwise "uptime calculations … was doing crazy things") |
| `CancelledCasts` | shared/normalizers/CancelledCasts.ts | marks each `begincast` with `isCancelled` and `castEvent` by pairing with the next `cast` of the same id; ignores `CASTS_THAT_ARENT_CASTS` and `CASTABLE_WHILE_CASTING_SPELLS` |
| `Channeling` | shared/normalizers/Channeling.ts | see §1 |
| `EmpowerNormalizer` | shared/normalizers/EmpowerNormalizer.ts | Evoker empower start/end pairing |
| `BuffRefreshNormalizer` | core/BuffRefreshNormalizer.ts | merges `removebuff` + `applybuff` within 50 ms into one `refreshbuff` |
| `EventOrderNormalizer` (deprecated) / `EventLinkNormalizer` | core/EventOrderNormalizer.ts, core/EventLinkNormalizer.ts | spec-defined `EventLink {linkRelation, linkingEventId/Type, referencedEventId/Type, forwardBufferMs, backwardBufferMs, anySource, anyTarget, reverseLinkRelation, maximumLinks, additionalCondition}`; matched events are attached to each other's `_linkedEvents` ("By default, the linked events must have the same timestamp, source, and target"). This is what specs call `CastLinkNormalizer` (e.g. `druid/balance/normalizers/CastLinkNormalizer.ts`). Wiki: https://github.com/WoWAnalyzer/WoWAnalyzer/wiki/EventLinkNormalizer |
| `CASTS_THAT_ARENT_CASTS` | core/CASTS_THAT_ARENT_CASTS.ts | ~120 spell ids that appear as `cast` but are auto-attacks, weapon off-hand hits, procs, toys, boss mechanics (Melee, Mutilate off-hand, Rampage 1-4, Soul Fragment, Fracture MH/OH, Charge damage, …) |

**Things that will trip a naive Python implementation [verified unless noted]**

1. `cast` is "also sometimes used … for mechanics and spell ticks or bolts. This can even occur in between a begincast and cast finish!" (Events.ts doc). Filter with a `CASTS_THAT_ARENT_CASTS`-style list and only count real spells.
2. Buffs already up at the pull have no `applybuff`; **read `combatantinfo.auras`** and treat unmatched `removebuff`/`refreshbuff`/`*stack` as "was up since fight start". Flask/food/rune/pre-pot checks in WoWA only work because of this fabrication (`event.prepull`).
3. Pre-pot detection uses `timestamp <= fight.start_time - fight.offset_time` on the fabricated buff, i.e. the potion buff must be present in `combatantinfo.auras`; casts of potions are not in WCL's Casts *table* (the project already knows this) but potion `cast` events are in the event stream — WoWA's `PotionChecker` listens to `cast` and `applybuff`.
4. Channels: no uniform begin/end events — WoWA needs a per-spell table (`CHANNEL_SPECS`). Cancelled casts: a `begincast` with no matching `cast`.
5. GCD/haste: WCL gives haste ratings only at pull (`combatantinfo.hasteSpell/Melee/Ranged`); haste buffs must be modelled or the GCD/hasted cooldown estimate drifts. WoWA hides the downtime statistic when its own GCD model errs ≥ 2 times/min.
6. `classResources.amount` can be stale when several updates share a timestamp (`ResourceTracker` doc example: Ferocious Bite cast/drain/energize); WoWA merges updates within 150 ms.
7. Cooldown reductions/resets are not in the log; every spec hand-codes them (`SpellUsable.reduceCooldown/endCooldown`), and the Abilities Generator wiki says "CDR is _still manual_ and probably always will be because most CDR effects are not in the game files" (https://github.com/WoWAnalyzer/WoWAnalyzer/wiki/Abilities-Generator-(WIP)).
8. Buff tracking in `Entities` deliberately ignores buffs that are neither by nor to the player/pets — a raid-wide view needs its own bookkeeping.
9. `sourceIsFriendly`/`targetIsFriendly` may be missing (hence `FriendlyCompatNormalizer`); self-damage and friendly fire ("Aura of Sacrifice") must be excluded from damage-done stats (Events.ts doc).
10. Death-resurrection: WoWA treats any cast/begincast/heal/damage after a `death` as an implicit resurrection (`DeathTracker`).
11. WoWA analyses **one player × one fight**; nothing in the parser aggregates across pulls or players — cross-pull aggregation is the project's own problem.

---

## 4. The player-facing layer

**Legacy Checklist / Suggestions — removed at this commit [verified]**. `ParseResults` contains only `tabs` and `statistics`
(https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/parser/core/ParseResults.tsx); `Analyzer` has no
`suggestions()` hook and its functional `suggestion()` builder is marked `@deprecated`; `ISSUE_IMPORTANCE = MAJOR | REGULAR | MINOR`
still exists (`src/parser/core/ISSUE_IMPORTANCE.ts`) and is referenced by `Ability.castEfficiency.importance`, but no
file in the tree matches `Checklist` outside `src/interface/icons/`, and none of the ~500 files I downloaded uses
`when(...).addSuggestion(...)`. The wiki "Suggestions" page (https://github.com/WoWAnalyzer/WoWAnalyzer/wiki/Suggestions)
now only gives writing guidance ("consistent, fight-length-independent metrics (per-minute or percentage-based)").
What survives from that era is the **threshold object** used everywhere:
`{ actual, isLessThan | isGreaterThan | isLessThanOrEqual | isGreaterThanOrEqual | isEqual: number | {minor, average, major}, style: ThresholdStyle.PERCENTAGE|NUMBER|SECONDS|BOOLEAN|… }`.

**Guide system [verified]** — https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/interface/guide/index.tsx: "a guide
is just a React component that takes a certain set of props (see `GuideProps` …) and returns JSX. There is no magic."
`GuideProps<T> = { modules: ModulesOf<T>, events: AnyEvent[], info: Info }`; a spec sets `static guide = Guide` on its
`CombatLogParser`; the Overview route renders `parser.buildGuide()` and shows "There is no frontmatter configured for this
spec." when there is none (`src/interface/routes/report/overview.tsx`, `src/interface/report/Results/Overview.tsx`).
Building blocks (`src/interface/guide/components/*`, `src/parser/ui/*`, `src/parser/core/SpellUsage`, `src/parser/core/MajorCooldowns`):

* `Section` / `SubSection` / `GuideSection({spell|title, explanation, children, verticalLayout, explanationPercent=40})` and
  `explanationAndDataSubsection(explanation, data, pct)` — explanation on the left, data panel on the right.
* `QualitativePerformance` = `Perfect | Good | Ok | Fail` (`src/parser/ui/QualitativePerformance.ts`: "'perfect' - the player did
  the mechanic perfectly, 'good' - … correctly, 'ok' - suboptimally, but it's not a big deal, 'fail' - incorrectly"); helpers
  `getAveragePerf`, `getLowestPerf`, `evaluateQualitativePerformanceByThreshold({actual, isGreaterThanOrEqual: {perfect, good, ok, fail}})`,
  and `combineQualitativePerformances` (lowest wins; `src/common/combineQualitativePerformances.ts`).
* `PerformanceBoxRow(values: {value, tooltip}[])` — one coloured box per cast; `CastSummaryAndBreakdown` = gradiated bar
  (perfect/good/ok/bad counts) that expands into the box row; `PerformanceStrong`, `PerformancePercentage`, `PassFailCheckmark`.
* `SpellUsageSubSection` + `SpellUse {event, checklistItems: ChecklistUsageInfo[] {check, timestamp, performance, summary, details}, performance}`
  (`src/parser/core/SpellUsage/core.tsx`) and `MajorCooldown<Cast>` (abstract: `explainPerformance(cast) => SpellUse`,
  `description()`; `CooldownUsage analyzer={…}` also adds "Potential cast went unused" (Fail) / "… may have been intentionally
  saved to handle a mechanic" (Ok) boxes from `CastEfficiency.maxCasts`).
* `CooldownGraphSubsection({cooldowns: [{spell, isActive}]})` → one `CastEfficiencyBar` per cooldown; default text:
  "Grey segments show when the spell was available, yellow segments show when the spell was cooling down. Red segments
  highlight times when you could have fit a whole extra use of the cooldown." `GapHighlight.None | FullCooldown | All`
  (`src/parser/ui/CooldownBar.tsx`); `CastEfficiencyPanel` colours the % by `majorIssue < average < recommended`.
* `MajorDefensives` (`src/interface/guide/components/MajorDefensives/*`): `MajorDefensive<Apply, Remove>` analyzer with
  `buff(spell)` / `debuff(spell)` triggers, `recordMitigation({event, mitigatedAmount})`, `absoluteMitigation(event, pct) =
  (amount+absorbed+overkill) * (1/(1-pct)) − actual`, `mitigationSegments()`; UI = `Timeline` (damage-taken point chart with
  buff bars; spikes covered by a defensive highlighted green), `AllCooldownUsagesList` (per-cast boxes + `BreakdownByTalent`,
  `BreakdownByDamageSource`), `MitigationSegments`, `DamageMitigationChart`.
* Report-wide `Timeline` tab (`src/interface/report/Results/Timeline/*`): `Casts` lane (cast icons, GCD bars, channel bars,
  movement, inefficient-cast highlights via `event.meta.isInefficientCast`), `Cooldowns` lanes per ability using
  `UpdateSpellUsable` events, `Auras` lanes, enemy casts.
* `Statistic` boxes (`src/parser/ui/Statistic.tsx`, `StatisticBox`), `TalentAggregateStatisticContainer` (stacked bar of talent
  contributions), `UptimeBar`, `ActiveTimeGraph`.
* `PreparationSection` = `EnchantmentSubSection`, `EnhancementSubSection`, `GemSubSection`, `ConsumablesSubSection`
  (Food / Potion / Flask / Augment Rune panels; "Using consumables appropriately is an easy way to improve your throughput.").
* **Foundation guide** (`src/interface/guide/foundation/FoundationGuide.tsx`) — the spec-agnostic default:
  `Section "Core Skills"` → `FoundationDowntimeSection` (Ability Uptime with `abc.DowntimePerformance`; Melee Uptime for
  melee/tank; Healing Uptime for healers, Good when ≥ 0.7 × active time; Cancelled Casts for healers/ranged; a red/blue
  uptime diagram with tooltips per gap; text "The foundation of good play in WoW is having good uptime. There should be no
  gaps between the end of one GCD and the start of the next." … "doing something is better than doing nothing"),
  `FoundationCooldownSection` (every enabled ability with `category === COOLDOWNS`, sorted by cooldown, as `CastEfficiencyBar`s:
  "90% of the time you can get 90% of those results by making sure to use every cooldown available to you … you can use a
  2-minute cooldown at most 3 times in a 2m 30s boss fight."), `FoundationHealerManaSection` (healers: "Spend all of your mana
  by the end of the fight. Don't run out of mana before the end of the fight … the percent of mana you have left should match
  the percent of the fight you have left", mana-level chart vs boss HP), then `PreparationSection`.

**Concrete spec examples [verified]**

*DPS — Havoc Demon Hunter* (`src/analysis/retail/demonhunter/havoc/Guide.tsx`, `modules/resourcetracker/FuryTracker.tsx`,
`modules/talents/EyeBeam/analyzer.tsx`, `modules/spells/Blur.tsx`; support `MaintainedPartial`, patch 12.1.0):
* Core → Fury: "You should avoid capping Fury - lost Fury generation is lost DPS." Percent of fight at Fury cap:
  `PERFECT ≤ 0.15`, `GOOD ≤ 0.20`, `OK ≤ 0.25`, else Fail; plus the fury graph.
* Core → Active Time: "Continuously casting throughout an encounter is the single most important thing for achieving good
  DPS." with `alwaysBeCasting.DowntimePerformance` (5/10/15 %) and `ActiveTimeGraph`.
* Cooldowns → `CooldownGraphSubsection` + `CooldownUsage analyzer={modules.eyeBeam}`: per Eye Beam cast, checklist items
  "Trigger Furious Gaze" (Good: "You triggered Furious Gaze by fully channeling your Eye Beam cast. Good job!" / Fail: "…
  Always try to fully channel so that you get the Haste buff.") and Inertia window (Good "Fully channeled during Inertia",
  Ok "Started during Inertia", Fail "Cast outside Inertia"); overall = lowest.
* Defensives → `Blur` is a `MajorDefensiveBuff` with 25 % DR (`absoluteMitigation(event, 0.25)`); text "Because Blur has a
  relatively short cooldown, it should usually be used proactively for meaningful incoming damage rather than held too long
  waiting for a perfect emergency." plus `Timeline` and `AllCooldownUsageList`.

*Healer — Restoration Druid* (`src/analysis/retail/druid/restoration/Guide.tsx`, `modules/spells/Lifebloom.tsx`,
`Efflorescence.tsx`, `Tranquility.tsx`; `MaintainedFull`, 12.1.0):
* "Always Be Casting" → `FoundationDowntimeSectionV2` (+ Master Shapeshifter Wrath advice).
* Core Spells → Lifebloom: "belongs on yourself. Aim for 100% uptime"; per cast boxes: Good "Refreshed in pandemic window
  (x s remaining)" / Good "Fresh cast" / Ok "Refreshed earlier than pandemic" / Fail "Moved Lifebloom to a new target" /
  Fail "Reapplied Lifebloom after it faded". Efflorescence: "is very mana efficient when placed under the raid … try to keep
  it active" with plain and target-weighted uptime (`weightedUptime = Σ duration × targets / EFFLO_TARGETS`).
* Healing Cooldowns → HoT-count graph with cooldown rule lines ("Did you have a Wild Growth out before every cooldown?"),
  `CastEfficiencyBar`s for Convoke / Tree of Life / Tranquility / Innervate (`GapHighlight.FullCooldown`), and a per-cast
  Tranquility checklist: Wild Growth ramp (`wgsOnCast > 0`), Rejuvenation ramp (`≥ 5`), Regrowth ramp (`≥ REGROWTH_RAMP_THRESHOLD`),
  full channel (`channeledTicks === MAX_TRANQ_TICKS`); Good only if WG ∧ Regrowth ∧ full channel. Text: "Start the ramp about
  15–20 seconds before Tranquility is assigned …".

*Tank — Protection Paladin* (`src/analysis/retail/paladin/protection/Guide.tsx`, `modules/core/Defensives/*`; **`Unmaintained`**, 12.0.7):
* Core Skills = Foundation downtime + cooldown sections; Resource Use → Holy Power at cap `PERFECT ≤ 0.10`, `GOOD ≤ 0.15`,
  `OK ≤ 0.20` ("Never use a builder at max Holy Power…"); Rotation → `AplSectionData` (APL check).
* Defensive Cooldowns → `MajorDefensives`: "There are two things you should look for … 1. You should cover as many damage
  spikes as possible … 2. You should *use* your cooldowns. This may seem silly—but not using major defensives is a common
  problem! For Protection Paladins, it is also likely to be fatal." `ArdentDefender` = `MajorDefensiveBuff`, DR
  `0.20 + 0.10 × rank(Improved Ardent Defender)`, ignores friendly-source damage. Active Mitigation section (Shield of the
  Righteous / Consecration uptime vs damage intake) is marked "WIP!".

*Tank — Brewmaster Monk* (`src/analysis/retail/monk/brewmaster/Guide.tsx`, `modules/core/StaggerPool/StaggerPoolSection.tsx`; `MaintainedFull`, 12.1.0):
Stagger pool over time with Purifying Brew casts highlighted, totals absorbed / taken as DoT / purified, damage-added-by-source
table; "Cooldowns like Invoke Niuzao and Exploding Keg are a major contributor to your overall damage … holding them too
long can hurt your damage significantly—especially if you outright skip a cast (shown in red)"; `MajorDefensivesSection`
(Fortifying Brew, Diffuse Magic, Zen Meditation, Celestial Brew).

---

## 5. Spell data

* **`src/common/SPELLS/*.ts` [verified]** — hand-maintained `Spell {id, name, icon, <resource>Cost?, lowRanks?, enchantId?}`
  objects per class (`src/common/SPELLS/Spell.ts`, e.g. `demonhunter.ts`: "You need to do this manually, usually an easy way to
  do this is by opening a WCL report and clicking the icons of spells to open the relevant Wowhead pages"). Expansion folders
  (`src/common/SPELLS/midnight/{potions,flasks,food,enchants,embellishments,raids}.ts`, `src/common/ITEMS/midnight/*`) hold the
  consumable / enchant / gem / trinket ids used by the preparation checkers. **No cooldown, GCD or charge data here.**
* **`src/common/TALENTS/<class>.ts` [verified]** — "Generated file" via `scripts/talents/generate-talents.ts` (from Blizzard talent
  JSON, `LIVE_WOW_BUILD_NUMBER`), entries `Talent {id, name, icon, maxRanks, entryIds, definitionIds:[{id, specId}]}` plus resource
  costs from the SpellPower DBC. Again no cooldowns.
* **Cooldown data lives in code**: for 38 of 40 retail specs in a hand-written `modules/Abilities.ts` (e.g. Fury:
  `cooldown: (haste) => 8 / (1 + haste), charges: 1 + (hasTalent(IMPROVED_RAGING_BLOW) ? 1 : 0), gcd: {base: 1500}`) —
  https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/analysis/retail/warrior/fury/modules/Abilities.ts.
* **Machine-readable spell lists (new, 2 retail specs) [verified]** — `spell-list_<Class>_<Spec>.retail.ts` exist for Brewmaster
  and Devourer only (10 classic specs also); generated by `scripts/spell-lists/generate-list.ts` from the **`wow-dbc`** package
  (`github:RPGLogs/wow-dbc#main`, MIT, "Extract data from the DBC files for World of Warcraft. This is built on the CSV exports of
  said files from wago.tools" — https://github.com/RPGLogs/wow-dbc) for game build `12.1.0.69299`
  (`scripts/spell-lists/internal.ts`). Each entry has `id, type ('baseline'|'talent'|'learned'|'temporary'|'passive'), gcd {duration,
  hasted}, cooldown {duration, hasted, modifiers: [{duration, requiredSpells}]}, charges {max}, overrides, taughtBy, icon` —
  https://github.com/WoWAnalyzer/WoWAnalyzer/blob/a23f33a/src/analysis/retail/monk/brewmaster/spell-list_Monk_Brewmaster.retail.ts.
  `genAbilities({allSpells, rotational, cooldowns, defensives, overrides, omit})` (`src/parser/core/modules/genAbilities.ts`) turns
  such a list into an `Abilities` class, computing `cooldown`/`gcd`/`charges` from the DBC fields and `enabled` from talents.
  `[inferred]` This is the only reusable machine-readable cooldown source in the repo, and it is generated (a Python tool could
  regenerate its own lists from wago.tools CSVs the same way: `Spell`, `SpellCooldowns`, `SpellCategories`/charges,
  `SpellMisc`/GCD, `TraitDefinition`/talents); WoWA itself notes CDR effects are not in game files.
* **Icons**: `spell.icon` names map to `https://render.worldofwarcraft.com/…` / WCL's `abilityIcon` (`SpellIcon`, `SpellLink` components); WCL events carry `ability.abilityIcon` already.
* **License [verified]**: `LICENSE` = GNU Affero General Public License v3; `package.json` `"license": "AGPL-3.0-or-later"`;
  GitHub API `license.spdx_id = AGPL-3.0`. `AI_POLICY.md`: "WoWAnalyzer does not accept AI-generated code from unknown
  contributors" (relevant only if you plan to contribute back). What this means — `[inferred, not legal advice]`:
  (a) **Reading the repo to learn what is measured and which thresholds are used** copies ideas and facts, not expression;
  re-implementing "downtime > 15 % is major" in your own Python is not conveying WoWA code. (b) **Copying ability tables /
  spell lists / normalizer code verbatim** into the Python tool makes that tool a derivative work under the AGPL: as long as
  it stays private (run on the user's machine, not offered to others "through a computer network" — AGPL §13, and not
  distributed), the licence imposes no obligation; the moment you distribute it or run it as a service for others you must
  release the whole tool's source under AGPL-3.0. The generated `spell-list_*.ts` files are data derived from Blizzard game
  files via an MIT tool, but the files themselves are checked into an AGPL repo — regenerating from wago.tools is the clean
  route. (c) **Publishing the dashboard HTML** is publishing *output*; copyleft attaches to the program, not to what it
  produces, unless the output embeds WoWA code (e.g. copied JS/CSS/text). Quoting WoWA's explanatory sentences verbatim in the
  dashboard would be copying expression — paraphrase.

---

## 6. Coverage (retail specs, `src/analysis/retail/*/*/CONFIG.tsx`, current game version `12.1.0` per `src/game/VERSIONS.ts`) [verified]

`SupportLevel` (`src/parser/Config.ts`): `Unmaintained` ("may have no analysis or broken analysis"), `Foundation` ("core
support for ability & cooldown tracking. It may use the Foundation guide … Specs with this level of support **do not have
dedicated maintainers**"), `MaintainedPartial`, `MaintainedFull`. `isLatestPatch()` flags a spec "out of date" when
`patchCompatibility` < `12.1.0` on any of major/minor/patch (`src/game/isLatestPatch.ts`, `SupportChecker.tsx`). Note the
repo has a **new spec `demonhunter/devourer`** and 40 retail CONFIGs.

| Support level | Count | Specs (patchCompatibility) |
|---|---|---|
| MaintainedFull | 17 | Resto Druid 12.1.0 · Augmentation 12.1.0 · Devastation 12.1.0 · Preservation 12.1.0 · Survival 12.0.7 · Arcane 12.1 · Fire 12.0.7 · Frost Mage 12.0.7 · Brewmaster 12.1.0 · Mistweaver 12.1 · Shadow 12.1 · Subtlety 12.1.0 · Elemental 12.1.0 · Enhancement 12.1.0 · Resto Shaman 12.1.0 · Demonology 12.1.0 · Destruction 12.1.0 |
| MaintainedPartial | 16 | Blood DK 12.0.1 · Frost DK 12.0.7 · Unholy 12.0.7 · Devourer 12.0.0 · **Havoc 12.1.0** · Vengeance 12.0.7 · Feral 12.0.7 · Beast Mastery 12.0.7 · Marksmanship **11.0.5** · Windwalker 12.1.0 · Holy Paladin 12.0 · Retribution 12.0.7 · Holy Priest 12.0.1 · Assassination 12.0.0 · Outlaw 12.0.7 · Affliction 12.1.0 |
| Foundation | 6 | Balance 12.0.1 · Guardian 12.0.1 · Discipline 12.0.1 · Arms 12.1 · Fury 12.1 · Protection Warrior 12.0.7 |
| Unmaintained | 1 | Protection Paladin 12.0.7 |

Exact per-spec rows (from the CONFIG scan): `deathknight/blood MaintainedPartial 12.0.1`, `deathknight/frost MaintainedPartial 12.0.7`,
`deathknight/unholy MaintainedPartial 12.0.7`, `demonhunter/devourer MaintainedPartial 12.0.0`, `demonhunter/havoc MaintainedPartial 12.1.0`,
`demonhunter/vengeance MaintainedPartial 12.0.7`, `druid/balance Foundation 12.0.1`, `druid/feral MaintainedPartial 12.0.7`,
`druid/guardian Foundation 12.0.1`, `druid/restoration MaintainedFull 12.1.0`, `evoker/augmentation MaintainedFull 12.1.0`,
`evoker/devastation MaintainedFull 12.1.0`, `evoker/preservation MaintainedFull 12.1.0`, `hunter/beastmastery MaintainedPartial 12.0.7`,
`hunter/marksmanship MaintainedPartial 11.0.5`, `hunter/survival MaintainedFull 12.0.7`, `mage/arcane MaintainedFull 12.1`,
`mage/fire MaintainedFull 12.0.7`, `mage/frost MaintainedFull 12.0.7`, `monk/brewmaster MaintainedFull 12.1.0`,
`monk/mistweaver MaintainedFull 12.1`, `monk/windwalker MaintainedPartial 12.1.0`, `paladin/holy MaintainedPartial 12.0`,
`paladin/protection Unmaintained 12.0.7`, `paladin/retribution MaintainedPartial 12.0.7`, `priest/discipline Foundation 12.0.1`,
`priest/holy MaintainedPartial 12.0.1`, `priest/shadow MaintainedFull 12.1`, `rogue/assassination MaintainedPartial 12.0.0`,
`rogue/outlaw MaintainedPartial 12.0.7`, `rogue/subtlety MaintainedFull 12.1.0`, `shaman/elemental MaintainedFull 12.1.0`,
`shaman/enhancement MaintainedFull 12.1.0`, `shaman/restoration MaintainedFull 12.1.0`, `warlock/affliction MaintainedPartial 12.1.0`,
`warlock/demonology MaintainedFull 12.1.0`, `warlock/destruction MaintainedFull 12.1.0`, `warrior/arms Foundation 12.1`,
`warrior/fury Foundation 12.1`, `warrior/protection Foundation 12.0.7`. (Counts: 17 Full, 16 Partial, 6 Foundation, 1 Unmaintained
= 40.) Only 19 of 40 declare `12.1.0`/`12.1` (14 Full, 3 Partial, 2 Foundation); the other 21 show the "spec out of date" banner. Guide files exist for every retail spec except `hunter/marksmanship` and `warrior/protection`
(tree scan for `/guide/i`); Protection Warrior's parser sets no `static guide`, so its overview is empty.

**Implication for "just port WoWAnalyzer's spec module" [inferred]**: every spec's analysis is a different, hand-written
TypeScript module set (Havoc alone has ~60 spec modules and 8 normalizers) built on spec-specific spell ids, talent checks
and cooldown-reset rules; porting even one spec faithfully is weeks of work and must be redone each patch. What *is*
portable for a 20-person roster is the **Foundation layer**: active time, cancelled casts, melee uptime, cast efficiency of
`COOLDOWNS`/`DEFENSIVE` abilities, healer mana curve, preparation checks, death recap with defensive readiness — all of
which need only an `Abilities`-style cooldown table per spec (which can be generated from DBC data, see §5) rather than
per-spec logic.

---

## 7. Feasibility per analysis for a Python, offline-cached, single-HTML dashboard fed by WCL events

Effort: S ≈ 1 day, M ≈ 2–4 days, L ≈ 1–2 weeks (Python + JS rendering + tests). "Spec knowledge" uses the (a)/(b)/(c) legend.
Events are per fight; multi-pull/roster aggregation is extra but uniform. `[inferred]` throughout unless a WoWA source is named.

| Analysis | Events needed (WCL v2 `events`) | Spec knowledge | Value (RL / DPS / healer / tank) | Effort | Notes |
|---|---|---|---|---|---|
| Active time / downtime % per player per pull (WoWA `AlwaysBeCasting`) | `cast`, `begincast` by player; `combatantinfo` (haste); ideally `applybuff/removebuff` to player for haste buffs | (b): which spells are on the GCD / off-GCD, base GCD 1500 vs 1000 ms, channel table | high / high / high / high — the single most requested "why is my DPS low" metric | M | Approximation without an ability table: every non-blacklisted `cast` starts a `1500/(1+haste)` GCD (750 floor); cast-time spells = `begincast→cast`; channels need WoWA's `CHANNEL_SPECS`-like list. Expect a few % error; WoWA hides the number if GCD errors ≥ 2/min. Thresholds 5/10/15 % downtime, 6/8/10 small gaps/min reusable. |
| Cancelled casts % (ranged/healers) | `begincast`, `cast` | (a) + blacklist of fake casts / castable-while-casting | med / med / high / low | S | WoWA thresholds 2/5/15 %. |
| Melee uptime (melee/tanks) | `cast` with `ability.guid == 1` (Melee) by player | (a) | low / med / – / med | S–M | WoWA infers swing timer from consecutive melees (800–4000 ms) and excludes channel time. |
| Cooldown cast efficiency (casts vs possible, time-on-cooldown %) + cooldown timeline bars | `cast` by player, `combatantinfo` (talents → charges/enabled) | **(b) required**: cooldown seconds (hasted?), charges, GCD per spell, per spec/talent | very high / very high / high / high | M code + L data | Generate the table from wago.tools DBC CSVs (`SpellCooldowns`, `SpellCategories` charges, `TraitDefinition`) like WoWA's `spell-lists`, then hand-curate 5–10 cooldowns per spec. CDR/resets (e.g. Anger Management) are not in the log or DBC — accept error or hand-code. Reuse WoWA's efficiency formula (time-based) and 80 % / −5 / −15 thresholds; "could have fit one more cast" gap highlighting (`GapHighlight.FullCooldown`). |
| Major defensive usage: casts, coverage of damage spikes, damage mitigated | `applybuff`/`removebuff` of the defensive on the player, `damage` to player | (b): defensive buff ids + DR % per spell/talent rank | high (RL) / med / med / very high | M | WoWA's `MajorDefensive` model: window = buff up; mitigated = `taken × (1/(1−pct)) − taken`; spike chart. Extends the existing "defensives before first death". Without DR % you still get coverage/usage boxes. |
| Death recap + "defensive was available" | `damage`/`heal` to player, `death`, `cast` by player | (b) cooldown table for readiness; DEFENSIVE_BUFFS externals list (Pain Suppression, Ironbark, BoP, Sac, Guardian Spirit, Life Cocoon, Rallying Cry, …) | very high / med / med / high | S–M | Existing recap + SpellUsable-style readiness per defensive at time of death. |
| Preparation: flask, food tier, augment rune, pre-pot, potions used vs max, Healthstone use | `combatantinfo.auras` (buffs up at pull!), `applybuff` to player, `cast` by player | per-expansion id lists (a) | med / med / med / med | S | Project already does most; add `combatantinfo.auras` as the source (WoWA's `ApplyBuff` normalizer) and WoWA's tier lists (`src/common/SPELLS/midnight/{flasks,food,potions}.ts`). |
| Enchants / gems / weapon enhancements | `combatantinfo.gear[]` (`permanentEnchant`, `gems`, `itemLevel`), `talentTree` | per-expansion enchant/gem ids (a); best-enchant lists are opinion | med (RL: "who is under-prepared") / low / low / low | S–M | Purely CombatantInfo; WoWA `EnchantChecker`, `GemChecker`, `WeaponEnhancementChecker`. Also gives the ilvl column the plan wants. |
| Healer mana curve, mana left at end, "mana % ≈ fight % left" guideline | `cast` by player with `classResources` (mana) | (a) | low / – / very high / – | S | WoWA `ManaValues` thresholds 10/20/30 % left; WCL `graph/resources` not needed (boss HP already known from fight %). |
| Healing active time vs non-healing time; overheal %; HPM per spell | `heal`/`absorbed` by player+pets (amount, overheal, absorbed), `cast` classResources | light (b): classify heal spells (derivable: spells that produce `heal` events) | low / – / high / – | M | WoWA `AlwaysBeCastingHealing` (30/40/45 % non-healing), `HealingEfficiencyTracker`. Overheal alone is (a). |
| Resource waste (fury/rage/holy power/energy at cap) | `resourcechange` by/to player (`waste` field, `resourceChange`), `cast` classResources | (a) for wasted totals & % of fight at cap; (b) for builder/spender semantics | low / med / – / med | M | WoWA `ResourceTracker`; thresholds from specs (Havoc 15/20/25 % at cap, Prot Pal 10/15/20 %). |
| Buff/debuff uptime for a curated list (own DoTs, Lifebloom-type maintenance buffs, raid CDs like Power Infusion received) | `applybuff/refreshbuff/removebuff`, `applydebuff/…` by player | (b): which ids matter per spec | med / med / high / med | S–M | Uptime maths is trivial (WoWA `buffUptimeTotal`); value depends on the curated list. Handle pre-pull via `combatantinfo.auras` + unmatched `removebuff`. |
| Early DoT refresh / pandemic clipping | `applydebuff/refreshdebuff` + DoT durations | (c) | – / med / low / – | M–L | Needs per-DoT duration & pandemic rules (`EarlyDotRefreshes`, `HotTracker` 1.3×). Skip initially. |
| Rotation / APL correctness | everything | (c) per spec APL + conditions | – / high / – / med | XL | Not feasible generically; this is WoWA's per-spec core. |
| Interrupts / dispels counts | `interrupt`, `dispel` | (a) | med | done | already in the project. |
| Cooldown throughput windows (damage inside Metamorphosis, healing inside Tranquility) | `cast/applybuff/removebuff` + `damage/heal` by player | (b) | low / med / med / – | S–M | WoWA `CooldownThroughputTracker`; nice-to-have. |
| Dynamic stat tracking (haste/crit over time) | `combatantinfo` + buff table | (b/c) | low | M | Only worth it as an input to GCD/cooldown accuracy. |
| Boss-config "soft mitigation checks" (was a mitigation buff up for hit X) | `damage` to player | (c) per boss ability + per spec buffs | high for tanks/RL | M | Fits the existing `avoidable.json` workflow: add a `mitigatable` list per boss and check tank buffs at hit time. |

**Bottom line [inferred]**: the parts of WoWAnalyzer that generalise across 39 specs are exactly the ones a Python tool can
reproduce from WCL events plus one generated cooldown table: active time, cancelled casts, cooldown efficiency with a
timeline, major-defensive coverage, death recap with readiness, healer mana curve, preparation/gear checks, resource waste
and curated buff uptimes. Everything that makes WoWA "spec-aware" (rotation checks, per-cast checklists like Eye Beam/Inertia
or Tranquility ramps, DoT snapshotting, per-item analyzers) is hand-written TypeScript per spec that is not portable and is
only `MaintainedFull` for 17 of 40 specs (14 of those at patch 12.1).
