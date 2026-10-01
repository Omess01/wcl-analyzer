> Research input (2026-09-25) to `docs/plans/2026-09-25-player-analysis-design.md`; copied unchanged from the session scratchpad apart from this header line.

# 04 — What the WCL v2 API can deliver for per-player analysis (cost, shapes, pitfalls)

Research agent report, 2026-09-25. Read-only on the repo; `.env` not read; no live API calls were made (no credentials).

## How to read this
- **verified [Sx]** = read in a primary or community source, listed at the end with full URLs.
- **verified (cache)** = seen in real WCL responses already on disk in `data/cache/` (2,298 files, 962 MB), analysed with
  throwaway scripts in the scratchpad. These are the strongest evidence for response shapes.
- **verified (code)** = read in this repo (`collect_data.py`, `wcl_client.py`, `cache.py`, `docs/`).
- **inferred** = reasoning, older API versions (v1), sister sites (FF Logs), or my own knowledge. Test it with one live
  call before building on it.
- Access problems: `https://www.warcraftlogs.com/v2-api-docs/warcraft/*.doc.html` now returns **404**, `archon.gg` returns a
  **"Human Verification"** page to WebFetch and curl, and `github.com/kihra/warcraftlogs-api` **does not exist** (GitHub API 404).
  Schema pages were read from Wayback Machine snapshots (dates in the source list). The newest `Report` page is from
  2025-08-28; `ReportFight` only from 2022-11-28. The WCL **Scripting API** docs (`/scripting-api-docs/`) are still live.

**Main findings, short version**
1. Much of the per-player picture is **already cached, with no new API calls**: `activeTime` and `overheal` per player,
   item level, gear with enchant and gem names, `specID`, the full talent tree, stats and pre-pull auras. For tanks, every
   damage-taken event the repo fetches carries a **`buffs` string listing the auras on the target at that hit**
   (active mitigation), plus `mitigated`, `unmitigatedAmount`, `absorbed` and `hitType`.
2. Casts for all players come to about **1 page of events per pull** (~0.7 MB). That is cheap. Buff events on friendlies
   are **~5 pages per pull**, and full damage-done or healing events are 4-11 pages per pull; both are expensive. Rule:
   filter server-side with `filterExpression` (tracked spell ids), or use `table(...)` aggregates.
3. WCL exposes **no cooldown, GCD or charge data** for abilities. "Cast efficiency" needs an outside spell-data source.
4. **Pitfalls in the current code:**
   - `events(dataType: Buffs, targetID: X)` also returns buffs that X put on others (19 % of the cached events).
   - The aliased event queries never read `nextPageTimestamp`.
   - Neither issue has visibly broken anything yet, but both will matter at a larger scale.
5. **Rate limit:** 3,600 points/hour free, 9,000 for Gold, 18,000 for Platinum. The point cost of a query is not
   published, so it has to be measured with `rateLimitData` deltas. The client's backoff (at most ~30 s per retry) cannot
   wait out an exhausted hourly budget.

---

## 1. `Report.events`: arguments, semantics, pagination, and what the repo uses

**Full argument list** (verified [S1], Report schema snapshot 2025-08-28):
`events(abilityID: Float, dataType: EventDataType, death: Int, difficulty: Int, encounterID: Int, endTime: Float,
fightIDs: [Int], filterExpression: String, hostilityType: HostilityType, includeResources: Boolean, killType: KillType,
limit: Int, sourceAurasAbsent: String, sourceAurasPresent: String, sourceClass: String, sourceID: Int, sourceInstanceID: Int,
startTime: Float, targetAurasAbsent: String, targetAurasPresent: String, targetClass: String, targetID: Int,
targetInstanceID: Int, translate: Boolean, useAbilityIDs: Boolean, useActorIDs: Boolean, viewOptions: Int, wipeCutoff: Int):
ReportEventPaginator`

Semantics, quoting the schema comments (verified [S1]):
- The data "is not considered frozen, and it can change without notice. Use at your own risk".
- `limit`: "Allowed value ranges are 100-10000. The default value is 300."
- `includeResources`: "Whether or not to include detailed unit resources for actors. Adds substantially to bandwidth, so defaults to off."
- `hostilityType`: "A hostility of 0 indicates a friendlies view. A hostility of 1 represents enemies." Enum values are
  `Friendlies` and `Enemies` (verified [S5]).
- `killType`: `All | Encounters | Kills | Trash | Wipes` (verified [S6]).
- `sourceAurasPresent/Absent` and `targetAurasPresent/Absent`: "A comma-separated list of auras that must be present / absent
  on the source / target for the event to be included". This is a server-side "was the buff up?" filter.
- `sourceClass` / `targetClass`: class slug. `sourceInstanceID` / `targetInstanceID`: a specific instance of an NPC.
- `death`: "If viewing death events, a specific death to obtain information for."
- `wipeCutoff`: "The number of deaths after which all subsequent events should be ignored."
- `translate`: defaults to true; set it to false when names do not matter.
- `useAbilityIDs` / `useActorIDs`: default **true**, so events carry `abilityGameID` / `sourceID` / `targetID`, and names come
  from `masterData`. The schema wording ("Whether or not to include detailed ability information ... defaults to true") reads
  backwards. The cache confirms that the default gives ids only (verified (cache)). Kihra: "set useActorIDs to false if you
  just want to get the detailed actor info without having to fetch the master data" (verified [S23]).
- `viewOptions`: "A bitfield set of options used in the site UI." The values are not documented.

**`EventDataType`** (verified [S2], snapshot 2025-08-26): `All, Buffs, Casts, CombatantInfo, DamageDone, DamageTaken, Deaths,
Debuffs, Dispels, Healing, Interrupts, Resources, Summons, Threat`.

**Response and pagination.** `ReportEventPaginator { data: JSON, nextPageTimestamp: Float }` — "A timestamp to pass in as the
start time when fetching the next page of data" (verified [S4]). How to page:
- Loop with `startTime = nextPageTimestamp` until it is null.
- A page can hold slightly more than `limit`: cached pages hold 10,002 / 10,003 / 10,004 events for `limit: 10000`, because
  the page finishes the last timestamp (verified (cache)).
- Filtered queries can come back paginated even when the result is small. A forum user saw this with `filterExpression`
  (verified [S18]). Always follow `nextPageTimestamp`; never assume "fewer than limit = complete" (inferred from [S18]).
- WoWAnalyzer's `fetchEvents` loops on `nextPageTimestamp` with `maxPages = 3` and throws beyond that (verified [S25]). It
  uses WCL **v1** events through its own proxy (`makeWclApiUrl` → `v1/...`), so its page sizes do not carry over.
- Timestamps in event JSON are **relative to the report start**. `ReportFight.startTime/endTime` are "relative to the start
  of the report" (verified [S7]; cache values like `8016501`). But inside a **filter expression** `timestamp` is "relative to
  the start of the fight" (verified [S16]). This is a pitfall when writing time filters.
- Argument pitfall: a forum user passed `abilityID` + `sourceID` **without `dataType`** and got "an assortment of abilities
  and sources". The same query as a `filterExpression` returned exactly the web UI's result (verified [S18]). The repo always
  sets `dataType`, and its `sourceID` filter on Casts was exact in all 210 cached windows (verified (cache)).
- **`targetID` on `dataType: Buffs` is not exact** (verified (cache)). Across the 210 cached "buffs before first death"
  windows: 6,232 events have target = the dying player, **1,451 (19 %) have source = the dying player and a different
  target**, and 0 are neither. So `targetID` behaves like "actor involved" for Buffs.
  - Consequence: `attach_casts()` (collect_data.py:940-) only drops `sourceID == targetID`. A dying player's own
    externals on others (e.g. Power Infusion or Blessing of Sacrifice given out) can be listed as "externals received",
    with themselves as the caster.
  - Fix: keep only `ev.targetID == actor_id` (inferred fix).

**What the repo uses today** (verified (code), `collect_data.py`):

| Query | Arguments used | Line |
|---|---|---|
| `DAMAGE_TAKEN_QUERY` | `dataType: DamageTaken, fightIDs, startTime, endTime, limit: 10000` + `data nextPageTimestamp` | 159, loop 995-1034 |
| bundle `cinfo_<fid>` | `dataType: CombatantInfo, fightIDs, startTime, endTime, limit: 200` `{ data }` | 641-642 |
| `cons_<fid>` | `dataType: Casts, fightIDs, startTime: start-5000, endTime, filterExpression: "ability.id in (...)", limit: 2000` `{ data }` | 832-833 |
| `casts_<fid>` / `buffs_<fid>` | `dataType: Casts, sourceID` / `dataType: Buffs, targetID`, `startTime, endTime, limit: 300` `{ data }` | 914-917 |
| bundle tables | `table(dataType: DamageDone/Healing/Deaths/Interrupts/Dispels, fightIDs)` | 639 |
| `RANKINGS_QUERY` | `rankings(fightIDs, playerMetric: dps / hps)` | 173-174 |

- **Never used:** `hostilityType` (so the default, Friendlies, applies), `includeResources`, `translate`, `useAbilityIDs`,
  `useActorIDs`, `killType`, `abilityID`, `*AurasPresent/Absent`, `sourceClass`/`targetClass`, `wipeCutoff`, `viewOptions`,
  `death`, `difficulty`, `encounterID`.
- **Pitfall:** the aliased queries (`cinfo`, `cons`, `casts`, `buffs`) request only `{ data }` and never `nextPageTimestamp`.
  - The cached results are far below their limits: max 58 consumable casts per fight, 18 casts and 121 buff events per
    window, 27 combatantinfo per fight (verified (cache)).
  - But [S18] reports early pagination on filtered queries, so a truncated page would go unnoticed.
  - Request `nextPageTimestamp` too, and warn (or follow up) when it is non-null (inferred).

## 2. Event payload shapes

Raw GraphQL event JSON uses `abilityGameID` / `sourceID` / `targetID` / `fight` (verified (cache)). The WCL Scripting API
([S17]) and WoWAnalyzer's `Events.ts` ([S26], built on v1 JSON) describe the same events with partly different names. Treat
them as **semantics**, and check the raw key names with one live call.

**`cast` / `begincast`** (verified (cache), 957 events):
- Keys: `timestamp, type, sourceID, targetID (-1 = no target), abilityGameID, fight`.
- Optional: `sourceMarker`/`targetMarker` (raid markers), `targetInstance`, and **`fake: true`** on 98 of 863 casts.
  The Scripting API defines `isFake`: "not the result of a user action, but just made up by the game" (verified [S17]).
  **Exclude fake casts from cast counts.**
- Also seen: `empowerstart` / `empowerend` with `empowermentLevel` (Evoker) (verified (cache)).
- **No resources without `includeResources`:** no cached cast carries `hitPoints` or `classResources` (verified (cache)).
- With `includeResources: true`, WoWAnalyzer's cast type has `classResources: [{amount, max, type, cost}]`, `hitPoints,
  maxHitPoints, attackPower, spellPower, armor, absorb, x, y, facing, mapID, itemLevel, resourceActor` (verified [S26];
  raw v2 names inferred). The Scripting API `ResourceData` lists `hitPoints, maxHitPoints, attackPower, spellPower, armor,
  absorb, x, y, facing, mapId, itemLevel, resourceAmount/Cap/Cost/Type, additionalResources, versatility, avoidance`
  (verified [S17]).
- **"Blizzard only logs resources for one actor per event, so damage/healing events logs the resources for the target, and
  casts/swings for the source"** (verified [S20], WCL forum staff reply). So mana at a cast is the caster's mana, a good fit
  for "healer mana over time".

**Buff events** (verified (cache), 8,301 events):
- `applybuff, removebuff, refreshbuff, applybuffstack, removebuffstack` with `timestamp, type, sourceID, targetID,
  abilityGameID, fight`.
- `stack` on the stack events. `absorb` (shield size) on 328 applybuff and 385 removebuff events. Optional markers.
- Debuffs mirror these types (`applydebuff`, ... per the expression docs' type list, verified [S16]). No debuff events are
  cached.
- Pre-pull state is not in the event stream. It comes from `combatantinfo.auras` (below).

**`damage`** (verified (cache), 2,029,072 damage-taken events):
- Keys: `timestamp, type, sourceID, targetID, abilityGameID, fight, hitType, amount, mitigated, unmitigatedAmount,
  absorbed (when > 0), isAoE, tick (when periodic)`, **`buffs`**, and `overkill` when present.
- **`buffs`** is a dot-separated list of aura ids on the target at the moment of the hit, e.g.
  `"379017.462568.461867.188370.31850.389539.132403."`, which includes 132403 Shield of the Righteous and 31850 Ardent
  Defender. It is present on 20,032 of 23,184 sampled events, with 1-10 auras. It looks like a subset of all auras
  (inferred).
- This gives **tank active-mitigation uptime at the moment of each hit, from data the repo already downloads**.
- `hitType` codes seen: 1 (22,874), 4 (117), 10 (82), 7 (60), 8 (34), 0 (14), 2 (3). WoWAnalyzer maps MISS 0, NORMAL 1,
  CRIT 2, ABSORB 3, BLOCKED_NORMAL 4, BLOCKED_CRIT 5, DODGE 7, PARRY 8, IMMUNE 10 (verified [S26] HIT_TYPES.ts).
- Semantics (verified [S17] DamageEvent): `amount` "excluding absorbs and overkill"; `mitigated` "Excludes absorbs, but does
  include mitigation from blocking, armor and damage reductions"; `unmitigatedAmount` "raw unmitigated damage"; `blocked`;
  `resisted`; `isTick`.
- Damage **done** by players was not sampled. The same keys are inferred; whether `buffs` appears there is unknown.

**`heal`** (verified [S17] HealingEvent; raw keys inferred from [S26]): `amount` ("excluding absorbs and overheal"), `overheal`,
`absorbed` (healing absorbed by a heal-absorb debuff), `hitType`, `tick`. **`absorbed`** events (shield consumption):
- Scripting API `AbsorbedEvent`: `amount`, `attacker`, `attackerAbility` (verified [S17]).
- WoWAnalyzer: `sourceID` (shield caster), `targetID`, `attackerID`, `extraAbility` (verified [S26]).
- Raw v2 key names (`extraAbilityGameID`?) are inferred.
- Healer throughput must add `absorbed` events to `heal` events. The expression helper `inCategory("healing")` bundles them
  (verified [S16]).

**`resourcechange`**:
- Fields: `resourceChange`, `resourceChangeType`, `otherResourceChange`, `maxResourceAmount`, `waste` ("wasted resource gain
  (overcapped)") (verified [S17] AbstractResourceChangeEvent and [S26]).
- `drain` is its negative twin (verified [S16] type list, [S26]).
- `energize` is not in WCL's event-type list (verified [S16]). It is the combat-log name that WCL maps to `resourcechange`
  (inferred).
- Resource type ids: MANA 0, RAGE 1, FOCUS 2, ENERGY 3, COMBO_POINTS 4, RUNES 5, RUNIC_POWER 6, SOUL_SHARDS 7,
  ASTRAL_POWER 8, HOLY_POWER 9, MAELSTROM 11, CHI 12, INSANITY 13, ARCANE_CHARGES 16, FURY 17, PAIN 18, ESSENCE 19
  (verified [S26] RESOURCE_TYPES.ts). "Wasted Fury" etc. comes straight from `waste`.

**`death`**:
- Scripting API: `killer`, `killingAbility`, `deathSaveAbility`, `deathSaveTime`, `isFeign` (verified [S17]).
- The Deaths **table** entries carry `killingBlow {name, guid, type, abilityIcon}`, `deathSaveAbility`, `deathSaveTime`
  (verified (cache), §8).
- Raw event keys are inferred. The combat log also produces `instakill` (verified (cache): 222 in Deaths-table events).

**`interrupt` / `dispel`**:
- Interrupted or dispelled spell = `extraAbility` (v1 / WoWAnalyzer). `DispelEvent.isBuff` (verified [S26]). Scripting API
  `DispelEvent.stacks` (verified [S17]).
- The raw v2 key is probably `extraAbilityGameID` (inferred). The repo uses the tables instead (§3).

**`summon`**: `sourceID` (owner), `targetID` (pet), `abilityGameID` (verified [S26]; raw names inferred). Use it for pet
attribution. `masterData.actors.petOwner` also gives the owner (verified [S9]).

**`combatantinfo`** (verified (cache), one per player per fight, 9 KB each; the median bundle has 23 of them / 211 KB):
- Keys: `timestamp, type, fight, sourceID, specID, expansion ("dragonflight"), faction, strength, agility, stamina,
  intellect, armor, dodge, parry, block, critMelee/critRanged/critSpell, hasteMelee/hasteRanged/hasteSpell, mastery,
  versatilityDamageDone/HealingDone/DamageReduction, leech, avoidance, speed, gear[], auras[], talentTree[], talents[],
  pvpTalents[], customPowerSet[], secondaryCustomPowerSet[], tertiaryCustomPowerSet[]`.
- `gear[]` item: `{id, quality, icon, itemLevel, permanentEnchant?, temporaryEnchant?, onUseEnchant?, bonusIDs[], gems[{id,
  itemLevel, icon}], setID?}`. There are **no item names in the event**. The DamageDone/Healing table `gear` adds `slot,
  name, permanentEnchantName, temporaryEnchantName, onUseEnchantName` (verified (cache)).
- `auras[]` = auras present at the pull: `{source, ability, stacks, icon, name}` (flask, food, raid buffs; the repo already
  uses these for Preparation). "A set of auras that are present on the player when combat begins" (verified [S17]).
- **Talents come as id/rank pairs, not a loadout string:** `talentTree: [{id, rank, nodeID}]`, 73-82 entries per player. For
  retail, `talents` is an empty list (verified (cache)). Mapping ids to names or icons needs Blizzard / SimC talent-tree data
  (inferred). The Scripting API documents `talentTree` "For Dragonflight only" (still true for this expansion's logs, which
  report `expansion: "dragonflight"`) (verified [S17] + cache).
- **Spec** = numeric Blizzard `specID` (e.g. 62 Arcane, 253 Beast Mastery, 262 Elemental, 577 Havoc) (verified (cache)). The
  repo currently takes spec from the tables' `icon` "Class-Spec" string (collect_data.py:731-733).

## 3. `Report.table`: data types and what each returns

- `table(...)` accepts the same filters as `events` minus `limit/includeResources/useAbilityIDs/useActorIDs`, plus `viewBy:
  ViewType` (`Default | Ability | Source | Target`), and returns `JSON` (verified [S1], [S6]).
- **`TableDataType`**: `Summary, Buffs, Casts, DamageDone, DamageTaken, Deaths, Debuffs, Dispels, Healing, Interrupts,
  Resources, Summons, Survivability ("death info across multiple pulls"), Threat` (verified [S3]).
- `GraphDataType` has the same values (verified [S6]). The response is wrapped as `{data: {...}}` (verified (cache)).

**DamageDone** (verified (cache), median 146 KB per fight):
- `data: {entries[], totalTime, logVersion, gameVersion, exploitDetails}`.
- Each entry: `name, id, guid, type (class), icon ("Warlock-Affliction" = class-spec), itemLevel, total, totalReduced,
  activeTime, activeTimeReduced (ms), abilities[{guid, name, total, type, icon}], damageAbilities[], targets[{name, total,
  totalReduced, type}], talents[] (empty on retail), gear[] (with names), pets[], totalRDPSTaken, totalRDPSGiven, given[],
  taken[]` (support-spec attribution, e.g. Augmentation "Bombardments").
- **There are no hit, cast or crit counts per ability.**
- `activeTime` gives **"active %" = activeTime / fight duration**. The repo already parses it as `active_seconds` and
  `itemLevel` as `ilvl` (collect_data.py:740-741).

**Healing** (verified (cache), median 150 KB): same entry shape plus **`overheal` per player**. `abilities[]` has `total /
totalReduced` but **no per-ability overheal** at this level (verified (cache)). Per-ability overheal needs `table(dataType:
Healing, sourceID: X)` (shape inferred) or heal events.

**Deaths**: §8. **Interrupts / Dispels** (verified (cache)): `data.entries[0].entries[]` per spell `{name, guid, type,
abilityIcon, spellsBegun, spellsCompleted, spellsInterrupted, spellChannelsInterrupted, timestamp, details[{name, id, guid,
type, icon, total, actors[], abilities[]}], missedCasts[]}`. That is per enemy spell, broken down by player.

**Casts**:
- The **repo found that this table omits item uses**. For the longest Ula'tek pull, the raw cast events held 16 Healthstones,
  12 health potions, 6 combat potions and 2 mana potions; the Casts table held none (verified (code), docs/CHANGES_2026-09-23.md:122-127).
- Shape (not cached): wowsims reads `table(dataType: Casts).data.entries[]` as `{name, id, guid, type, icon ("Paladin-Justicar"),
  itemLevel, total, activeTime, abilities[], damageAbilities[], targets[], talents[], gear[]}` (verified [S27]).
- The FF Logs Go client types `CastsAbility {name, total, type}` (verified [S28]).
- So per-player **per-ability cast counts** are available cheaply (one alias per fight), but only as totals (inferred for WoW v2).

**Buffs / Debuffs** (not cached):
- `{auras[{name, guid, type, abilityIcon, totalUptime, totalUses, bands[{startTime, endTime}]}], useTargets, totalTime,
  startTime, endTime, logVersion}` (verified [S28] for FF Logs v1; the same aura shape is typed in wowsims `_wclAura`
  [S27]; inferred for WoW v2).
- This gives **uptime and use counts per aura** for the selected source/target. For per-player uptime you need
  `sourceID`/`targetID` per player (one alias each), or one alias per tracked `abilityID` with `viewBy: Target` (inferred;
  test).

**Resources**:
- The shape is not documented anywhere I could reach. go-fflogs marks it TODO (verified [S28]).
- A 2025 forum user got **no data** from `table`/`graph` with `dataType: Resources`, and staff redirected them to Discord
  (verified [S21]).
- The v1 API selected the resource via `abilityid` (inferred). Treat `Resources` tables as unproven, and use
  `resourcechange` events (filtered) instead.

**Summary**:
- FF Logs v1 Summary = `{totalTime, itemLevel, composition[{name, id, guid, type, specs[{spec, role}]}], damageDone[],
  healingDone[], damageTaken[], deathEvents[]}` (verified [S28], FF Logs).
- Whether WoW v2 Summary also embeds `playerDetails` (with talents/gear) is **not verified** (inferred "probably"). One test
  call decides it. `Report.playerDetails` (§4) is the documented route.

**Threat**: v1 shape `{threat[{name, id, guid, type, icon, targets[{..., totalUptime, bands[{startTime, endTime, startEvent,
endEvent}]}]}]}`, which includes active tanking time (verified [S26] WCL_TYPES.ts, used by WoWAnalyzer for "active tanking
time"; inferred for v2).

**Survivability / Summons**: exist (verified [S3]). Shapes: go-fflogs gives Survivability as `{players, fights, actortotals,
abilitytotals}` (verified [S28], FF Logs).

## 4. `Report.playerDetails`, `Report.rankings`, character rankings

**`playerDetails(difficulty, encounterID, endTime, fightIDs, killType, startTime, translate, includeCombatantInfo): JSON`**
— "A table of information for the players of a report, including their specs, talents, gear, etc." (verified [S1]).
- **Wrapping:** the JSON is nested as `{data: {playerDetails: {tanks[], healers[], dps[]}}}`. Community code unwraps it
  recursively "until we see one of the role keys (tanks / healers / dps)" (verified [S29]).
- **Entry fields:** community code reads `specs`, `combatantInfo`, `potionUse`, `healthstoneUse` and `minItemLevel` per
  player (verified [S29] README). The full list `{name, id, guid, type, server, icon, specs[{spec, count}], minItemLevel,
  maxItemLevel, potionUse, healthstoneUse, combatantInfo{stats, talents, gear}}` is inferred.
- **combatantInfo pitfall:** "playerDetails.combatantInfo is often empty — secondary stats come from events(dataType:
  CombatantInfo)" (verified [S30]). Pass `includeCombatantInfo: true` (verified [S1], used in [S29]). The repo's CombatantInfo
  events already carry everything.
- **Spec per fight:** call it with `fightIDs: [fid]` for a per-fight answer. A multi-fight call returns a `specs` list per
  player (inferred). For wipes as well as kills, the most reliable per-fight spec source is `combatantinfo.specID` (verified
  (cache)). Rankings exist for kills only.
- `potionUse` / `healthstoneUse` could cross-check the repo's own consumable counts (inferred; test).

**`rankings(compare, difficulty, encounterID, fightIDs, playerMetric: ReportRankingMetricType, timeframe): JSON`** (verified [S1]).
- Metrics include `dps, hps, bossdps, tankhps, wdps, playerspeed, krsi (deprecated)` (verified [S12]).
- Cached shape (verified (cache)): `data[]` per fight with `fightID, partition, zone, encounter{id, name}, difficulty, size,
  kill, duration, bracketData (ilvl bracket), deaths, damageTakenExcludingTanks, bracket, guild{...}, speed{rank, best,
  totalParses, rankPercent}, execution{...}, reportsBlacklistForCharacters, roles{tanks|healers|dps: {name, characters[]}}`.
- Character keys: **`id, name, server{id, name, region}, class, spec, amount, bracketData, bracket, rank ("~7282"), best,
  totalParses, bracketPercent, rankPercent`**. **`spec` is present** (e.g. "Brewmaster", "Unholy").
- `characters[].id` is the **WCL character id**, not the report actor id. Match by name + server, as the repo does (verified
  [S23] and code).
- Fight-level `speed` / `execution` ranks come free with the rankings the repo already fetches (verified (cache)).

**`characterData.character(id | name + serverSlug + serverRegion)`** (verified [S12]):
- **`zoneRankings(byBracket, className, compare, difficulty, includePrivateLogs, metric, partition, role, size, specName,
  timeframe, zoneID): JSON`**, and **`encounterRankings(encounterID, ..., includeCombatantInfo, ...)`**.
- `includePrivateLogs` "is only available if using the user GraphQL endpoint", so client credentials see **public logs only**.
  `partition: -1` = all partitions (verified [S12]).
- The response JSON is undocumented in the schema. The usual keys `bestPerformanceAverage, medianPerformanceAverage,
  rankings[{encounter{id, name}, rankPercent, medianPercent, totalKills, spec, bestSpec, bestAmount, lockedIn, allStars}],
  allStars[]` are inferred.
- **Cost:** undocumented. One community project measured "a character about 6" points (verified [S31]; the query content is
  unknown). For ~25 raiders, alias 25 `character(...) { zoneRankings(...) }` in one request and cache the result for hours
  (Archon guidance: "Rankings, characters, guild data: cache for hours or longer", verified [S14]).

## 5. Rate limits

- **Budget:** "The default unsubscribed limit is 3,600 points per hour. Gold: 9,000 points per hour. Platinum: 18,000 points per
  hour" (verified [S15], archived 2026-04-03). The profile page in 2024 said 3,600, or 36,000 via Patreon (verified [S19]),
  so tiers have changed over time. Read `limitPerHour` at run time instead of hard-coding.
- **Reset:** "Rate-limiting is done on 1-hour cycles, meaning your points are fully reset every hour" (verified [S14]).
- **Monitoring:** `rateLimitData { limitPerHour: Int!, pointsSpentThisHour: Float!, pointsResetIn: Int! (seconds) }` (verified
  [S11]); "You can append this to any of your queries" (verified [S14]). A community project observed `{"limitPerHour":
  18000, "pointsSpentThisHour": 9058.65, "pointsResetIn": 949}` (verified [S31]). Costs are **fractional**, which suggests
  they depend on work done, not on the request count (inferred).
- **How points are computed is not published.** Clues:
  - The schema says `phases` "requires loading fight data, but does not double-charge API points if you load fights and
    phases" (verified [S1]), so points track server-side loads.
  - wowsims says "WCL charges us 1 'point' for each subquery we issue within the request" (verified [S27]; a community
    claim, probably simplified).
  - Community measurements: "a raid night about 3, the current tier's list about 24, ... a character about 6" (verified
    [S31]).
  - **Recommendation:** add `rateLimitData { pointsSpentThisHour }` to each request kind for one build and log the deltas
    (roadmap item 6.5 already plans the end-of-run check; the repo does not query `rateLimitData` yet, verified (code) grep).
- **429s:** a user got HTTP 429 while points remained (verified [S22]), so there is a secondary burst limit. Kihra quoted
  "240 requests allowed every 120 seconds" for FF Logs **v1** in 2017 (verified [S24]); v2 burst limits are unknown
  (inferred). `WCL_PARALLEL=4` threads can burst. I could not verify whether WCL sends `Retry-After` or `X-RateLimit-*`
  headers; log them once.
- **What the repo does** (verified (code), wcl_client.py):
  - 401 → drop the token and retry (103-109).
  - **429 or 5xx → sleep `Retry-After` (capped at 120 s) or backoff 2→4→8→16 s (capped at 30 s)** (71-80, 110-113).
  - Connection/timeout errors → backoff (116-119).
  - GraphQL error text containing "rate limit" → sleep 60 s (123-127).
  - `MAX_ATTEMPTS=4`.
  - **Gap:** an exhausted hourly budget needs up to `pointsResetIn` (≤ 3,600 s). The client gives up after about 1-2
    minutes and the build fails part-way. Recommended: on 429 or rate-limit errors, query `rateLimitData`, then either
    sleep `pointsResetIn` or stop cleanly; the cache keeps finished fights (inferred).
- **Practical tips:**
  - Cache report data forever unless a fight is `inProgress` (verified [S14]). `ReportFight.inProgress` exists (verified
    [S7]) and is a cleaner live-log signal than endTime.
  - Keep master data separate (ids only; `useAbilityIDs`/`useActorIDs` default true).
  - `translate: false` for speed (verified [S1]).
  - `filterExpression` to cut payloads.
  - Batch fights with aliases, as the repo does.
  - Load `fights` and `phases` in one query: the repo loads them in two (FIGHTS_QUERY + PHASES_QUERY), so fight data may be
    charged twice (inferred from [S1]).
  - **`archiveStatus`:** "Events, tables, and graphs for archived reports are inaccessible unless the retrieving user has a
    subscription including archive access" (verified [S1]). The disk cache is the only copy of old nights; never clear it
    casually.

## 6. Data volume: events per pull, bytes, requests, monthly totals

Measured values come from the repo cache; the rest are labelled estimates.

| Per 6-min heroic pull, 20 players | Basis | Events | Bytes/event | JSON | Pages at 10k |
|---|---|---|---|---|---|
| Damage taken (friendly targets; fetched today) | **measured**: 92 pulls ≥ 4 min, median 338 s, 23 players → 10,190 events, 2.57 MB; 33 ev/s ≈ 1.4 ev/s/player | ~10,000 | 248 (incl. `buffs` string) | ~2.6 MB | 1-2 |
| `cast`+`begincast` (players) | **measured**: 0.72 casts/s/player in 210 pre-death windows of 6.3 s (4.56 per window) | 5,000-8,500 | 111 | 0.6-0.95 MB | 1 |
| Buff events on friendlies | **measured**: 6.27 ev/s/player in the same windows (39.5 per window; 79 % self-applied, 19 % leaked, see §1) | 30,000-45,000 | 120 | 3.6-5.4 MB | 3-5 |
| `resourcechange` | estimate: 0.5-2 /s/player | 3,600-14,000 | ~110 (≈ 350-450 with `includeResources`, inferred) | 0.4-6 MB | 1-2 |
| Damage done (player sources) | estimate: 5-15 /s/player (DoTs, pets, cleave) | 36,000-108,000 | ~180 | 6.5-19 MB | 4-11 |
| Healing (`heal` + `absorbed`) | estimate: 3-10 /s/player | 22,000-72,000 | ~160 | 3.5-11.5 MB | 3-8 |
| CombatantInfo (fetched today) | **measured** | 20-27 | ~9 KB | ~211 KB | 1 |
| `dataType: All` | sum of the above plus debuffs, summons, etc. | 130k-260k | | 25-50 MB | 13-26 |

The measured windows sit just before deaths, when defensives and externals cluster, so the buff rate may be high.
The cast rate may be low, because dying players are often moving (inferred).

**Today (verified (cache))**:
- Per pull: bundle median **614 KB** (DamageDone 146 KB, Healing 150 KB, Deaths 67 KB, CombatantInfo 211 KB, Dispels 2 KB),
  plus damage-taken events ~**2.6 MB**, ≈ **3.2 MB per pull**.
- The whole cache is **962 MB**: damage-taken pages 505 MB (52 %, 337 pages), bundles 417 MB (43 %, 681 fights), everything
  else < 20 MB (consumable casts 0.5 MB for 445 fights ≈ **1.2 KB per fight**; first-death casts+buffs 1.1 MB for 210 fights).
- About 700 HTTP requests would rebuild it (estimate from file counts ÷ batch sizes): 137 bundle batches, 337 damage-taken pages, 71 rankings, ~66 cast/consumable
  batches, ~100 report-level queries.

**×200 pulls per month** (inferred from the table):
- Player casts: 1.0-1.7 M events, **120-190 MB**, ~200 pages. With aliases (5-10 fights per request, each alias paginated),
  this is ~20-40 requests plus follow-ups.
- Friendly buffs: ~6-9 M events, **0.7-1.1 GB**, ~800-1,000 requests.
- Damage done: 7-22 M events, **1.3-3.8 GB**, 800-2,200 requests.
- `All`: **5-10 GB**, 2,600-5,200 requests. Not viable next to today's ~640 MB/month and the unknown per-page point cost.

**Filter-expression syntax** (verified [S16], WCL "Complete Guide to Pins", expression section):
- SQL-like: `AND/OR/NOT` (short-circuit), `= != < > <= >=`, `BETWEEN`, `IN (...)`, `NOT IN`, `CASE`, arithmetic.
- Strings in single **or** double quotes, compared case-insensitively.
- Built-ins: `type` (full event-type list incl. `begincast, cast, damage, heal, absorbed, healabsorbed,
  applybuff...removedebuffstack, summon, death, dispel, interrupt, resourcechange, drain, resurrect, taunt,
  modifythreat...`), `encounterID, encounterDifficulty, encounterPhase` ("Phases are numbered starting from 1"),
  `encounterFightPercentage`, `timestamp` (fight-relative!), `inCategory("damage"|"healing"|"auras"|"dispels"|"casts"|"deaths"|"resources"|"summons"|"other")`,
  `rawDamage, effectiveDamage, absorbedDamage, blocked, overkill, rawHealing, effectiveHealing, absorbedHealing, isCritical,
  isTick, missType, stack, stoppedAbility, feign, killer, killingAbility`.
- Actor fields: `source.|target.` + `name, id, instance, type ("player", "NPC", "pet"), class, spec, role ("tank", "melee",
  "ranged", "healer"), disposition, marker, owner, firstSeen, lastSeen`. Ability fields: `ability.name, ability.id,
  ability.type` (school). Resources fields: `resources.hitPoints, maxHitPoints, hpPercent, attackPower, spellPower, x, y`.
- Range tests: `IN RANGE FROM <cond> TO <cond> GROUP BY target ON source END`. Nth occurrence: `MATCHED <cond> IN (1,3) END`.
- Examples:
  - `source.type = "player" AND type = "cast"`
  - `source.role = "healer" AND type = "cast"` (healer mana via `includeResources`)
  - `ability.id IN (...)` on Buffs/Casts for tracked cooldowns
  - `target.role = "tank"` on DamageTaken
- In GraphQL, put the expression in a **variable** (`$filter: String`) or use single quotes inside it. The repo inlines
  `ability.id in (...)` in a double-quoted literal (collect_data.py:832-833), which breaks as soon as a name comparison adds
  quotes (inferred).

**Cheap vs expensive (conclusion, inferred)**:
- **Free (already cached):**
  - Active time / downtime (`activeTime`), overheal per player, ilvl, gear, enchants, gems, set pieces, spec, talents,
    stats, pre-pull auras, parses + spec, speed/execution ranks.
  - Tank mitigation: `mitigated/unmitigatedAmount/absorbed/hitType`, plus aura-at-hit from `buffs` on every damage-taken event.
  - Interrupts/dispels per player.
- **Cheap (≤ 1 alias per fight, KB-sized):**
  - `table(dataType: Casts)` for per-ability cast counts (no item uses).
  - Filtered Casts events for tracked cooldowns and defensives (~1-2 KB per fight, like `cons`).
  - Filtered Buffs events for tracked auras (Bloodlust, Power Infusion, major CDs).
  - `table(dataType: Buffs, ...)` uptime (inferred shape).
  - `playerDetails(fightIDs, includeCombatantInfo)`.
- **Moderate (~1 page per fight):**
  - All player casts (`dataType: Casts, filterExpression: "source.type = 'player'"`, or `hostilityType: Friendlies`),
    ~0.7 MB per pull, ~150 MB per month. Enough for cast timelines, cast counts vs fight length, and first-cast timings.
  - Healer casts with `includeResources` for mana curves (a few hundred KB per pull, inferred).
  - `resourcechange` filtered to one resource or role.
- **Expensive (avoid, or do only for the selected player or only for kills):**
  - Unfiltered friendly Buffs (3-5 pages per pull).
  - Full DamageDone / Healing events (4-11 pages).
  - `All`.

## 7. Spell / ability / actor / fight metadata

- `ReportMasterData { logVersion, gameVersion, lang, abilities: [ReportAbility], actors(type, subType): [ReportActor] }`
  (verified [S9]).
- `ReportAbility { gameID, icon, name, type }`; `type` = "the type of damage (e.g., the spell school in WoW)" (verified [S9];
  cache: `{"gameID": 448604, "name": "Spellfire Sphere", "type": "1"}`, type as a string).
- `GameData.ability(id): GameAbility { id, icon, name }`; `abilities(limit ≤ 100, page)` (verified [S10]).
- **No cooldown, GCD, charges, cast time, cost or duration anywhere in the schema** (verified [S9], [S10]: those are the only
  fields). WoWAnalyzer keeps its own per-spec cooldown/GCD modules (`SpellUsable.ts`, `GlobalCooldown.ts` under
  `src/analysis/**`) for exactly this reason (verified [S26] repo tree; the reasoning is inferred). Cast-efficiency numbers
  need SimC spell data, WoWAnalyzer's spell tables, or a small config (inferred).
- `ReportActor { gameID, icon, id, name, petOwner, server, subType (class for players; NPC / Boss for NPCs), type (Player /
  Pet / NPC) }` (verified [S9]). The repo fetches `id name subType server` for players and `id name` for NPCs
  (collect_data.py:90, 147).
- `ReportFight` fields (verified [S7], 2022 snapshot):
  `averageItemLevel, bossPercentage, boundingBox, classicSeasonID, completeRaid, difficulty, dungeonPulls, encounterID, endTime,
  enemyNPCs, enemyPets, enemyPlayers, fightPercentage, friendlyNPCs, friendlyPets, friendlyPlayers, gameZone, hardModeLevel,
  id, inProgress, keystoneAffixes, keystoneBonus, keystoneLevel, keystoneTime, kill, lastPhase, lastPhaseAsAbsoluteIndex,
  lastPhaseIsIntermission, layer, maps, name, rating, size, startTime, wipeCalledTime`.
  - `phaseTransitions { id, startTime }` is newer than that snapshot. It is documented as `PhaseTransition` (1-indexed phase
    id, report-relative `startTime`) (verified [S13]) and works in the repo (verified (cache)).
  - `friendlyPets` + `ReportFightNPC { gameID, id, instanceCount, groupCount, petOwner }` (verified [S8]) give **pet
    ownership per fight**, which pet damage and summons attribution need.
  - `averageItemLevel` is a free raid-level ilvl.
  - `size` distinguishes 20-man from other raid sizes.
  - `wipeCalledTime` is set when a wipe was called in the Companion app. Useful to exclude post-wipe junk from per-player
    stats, together with `wipeCutoff` on events (verified [S1], [S7]).
- `Report.phases: [EncounterPhases]` = per-encounter phase names and `isIntermission` (verified [S1], cache).

## 8. Deaths, threat and tank data; is there a "problems/insights" endpoint?

**Deaths table** (verified (cache), 11,899 cached deaths):
- Entry keys: `name, id, guid, type, icon (class-spec), timestamp, fight, damage{total, totalReduced, activeTime,
  activeTimeReduced, overheal, abilities[], damageAbilities[], sources[]}, healing{total, activeTime, activeTimeReduced,
  abilities[], damageAbilities[], sources[]}, deathWindow, overkill, events[], killingBlow{name, guid, type, abilityIcon},
  deathSaveAbility, deathSaveTime`.
- **`events[]` holds at most the last 3 events** (median 3, max 3), only `damage`/`instakill`, each with an embedded
  `ability{name, guid, type, abilityIcon}`, `sourceIsFriendly/targetIsFriendly`, `hitType, amount, mitigated,
  unmitigatedAmount, absorbed, isAoE, tick`.
- `deathWindow` (ms) varies: 0 for 2,552 deaths, < 5 s for 2,396, 5-10 s for 2,191, ≥ 10 s for 4,760.
- There are no heal events and no "bands". A full recap needs raw events, which the repo already builds from its
  damage-taken events. The `Survivability` table aggregates deaths across pulls (verified [S3]).

**Tank data**:
- **DamageTaken events** already give per-hit `mitigated`, `unmitigatedAmount`, `absorbed`, `blocked` / `hitType`
  (block/dodge/parry) and the `buffs` aura list (verified (cache)). So "was Shield of the Righteous / Ironfur / Shuffle /
  Demon Spikes up when the big hit landed" can be answered **with zero new calls**. A small per-tank-spec aura-id config is
  needed to name the auras (inferred).
- Active mitigation is otherwise just **Buffs events on the tank** (`applybuff` / `removebuff` of the AM aura) or the Buffs
  table uptime for that aura (inferred). The server-side `targetAurasPresent/Absent` arguments can split damage taken
  "with vs without AM" in two aliased `table(dataType: DamageTaken, targetID: tank, targetAurasPresent: "<id>")` calls
  (arguments verified [S1]; the usage is inferred). Kihra: the raw-damage graph is a ribbon, "the high point being the
  damage taken before mitigation, and the low point being the actual damage taken after mitigation" (verified [S23b]).
- **Threat**: `dataType: Threat` exists for events, tables and graphs (verified [S2], [S3]). The v1 Threat table carries
  active-tanking `bands` / `totalUptime` per target (verified [S26] WCL_TYPES.ts). WoWAnalyzer's own comment: tables "are not
  often useful ... but sometimes the aggregations include behaviors that we want to mimic (like Threat including active
  tanking time)" (verified [S25]). Taunts are `taunt` events (verified [S16]).
- Tank healing received: `table(dataType: Healing, hostilityType: Friendlies, targetID: tank)` (inferred). The metric
  `tankhps` exists for rankings (verified [S12]).

**"Problems" / insights endpoint: none.**
- The `Report` type exposes only `code, endTime, events, exportedSegments, fights, graph, guild, guildTag, owner, masterData,
  playerDetails, rankedCharacters, rankings, region, revision, segments, startTime, table, title, visibility, zone,
  archiveStatus, phases` (verified [S1]). No problems, insights or suggestions field exists.
- `Query` has `reportComponentData` / `systemReportComponentData` (verified [S11], 2025-11 snapshot). These relate to WCL
  "Report Components" (user JavaScript scripts, documented by the Scripting API [S17]). I could not fetch the
  `ReportComponentData` type page, so whether a component can be **executed** server-side through the API is **unverified**.
  Worth one look, since it would move computation to WCL.

---

## Sources
- **S1** Report schema (Wayback 2025-08-28): https://web.archive.org/web/20250828204915/https://www.warcraftlogs.com/v2-api-docs/warcraft/report.doc.html (live URL now 404)
- **S2** EventDataType (2025-08-26): https://web.archive.org/web/20250826172449/https://www.warcraftlogs.com/v2-api-docs/warcraft/eventdatatype.doc.html
- **S3** TableDataType (2022-11-28): https://web.archive.org/web/20221128220501/https://www.warcraftlogs.com/v2-api-docs/warcraft/tabledatatype.doc.html
- **S4** ReportEventPaginator (2022-11-30): https://web.archive.org/web/20221130210634/https://www.warcraftlogs.com/v2-api-docs/warcraft/reporteventpaginator.doc.html
- **S5** HostilityType (2022-11-26): https://web.archive.org/web/20221126160715/https://www.warcraftlogs.com/v2-api-docs/warcraft/hostilitytype.doc.html
- **S6** KillType https://web.archive.org/web/20221128213646/https://www.warcraftlogs.com/v2-api-docs/warcraft/killtype.doc.html · ViewType https://web.archive.org/web/20221128220120/https://www.warcraftlogs.com/v2-api-docs/warcraft/viewtype.doc.html · GraphDataType https://web.archive.org/web/20221201233720/https://www.warcraftlogs.com/v2-api-docs/warcraft/graphdatatype.doc.html
- **S7** ReportFight (2022-11-28): https://web.archive.org/web/20221128210854/https://www.warcraftlogs.com/v2-api-docs/warcraft/reportfight.doc.html
- **S8** ReportFightNPC: https://web.archive.org/web/20221128204228/https://www.warcraftlogs.com/v2-api-docs/warcraft/reportfightnpc.doc.html
- **S9** ReportMasterData https://web.archive.org/web/20221128214439/https://www.warcraftlogs.com/v2-api-docs/warcraft/reportmasterdata.doc.html · ReportAbility https://web.archive.org/web/20221201223838/https://www.warcraftlogs.com/v2-api-docs/warcraft/reportability.doc.html · ReportActor https://web.archive.org/web/20240222151110/https://www.warcraftlogs.com/v2-api-docs/warcraft/reportactor.doc.html
- **S10** GameAbility https://web.archive.org/web/20230206154944/https://www.warcraftlogs.com/v2-api-docs/warcraft/gameability.doc.html · GameData https://web.archive.org/web/20221201232155/https://www.warcraftlogs.com/v2-api-docs/warcraft/gamedata.doc.html
- **S11** RateLimitData https://web.archive.org/web/20221128205108/https://www.warcraftlogs.com/v2-api-docs/warcraft/ratelimitdata.doc.html · Query (2025-11-14) https://web.archive.org/web/20251114141016/https://www.warcraftlogs.com/v2-api-docs/warcraft/query.doc.html
- **S12** Character https://web.archive.org/web/20221126154350/https://www.warcraftlogs.com/v2-api-docs/warcraft/character.doc.html · CharacterData https://web.archive.org/web/20221128205444/https://www.warcraftlogs.com/v2-api-docs/warcraft/characterdata.doc.html · ReportRankingMetricType https://web.archive.org/web/20221128222020/https://www.warcraftlogs.com/v2-api-docs/warcraft/reportrankingmetrictype.doc.html · CharacterRankingMetricType https://web.archive.org/web/20221128213145/https://www.warcraftlogs.com/v2-api-docs/warcraft/characterrankingmetrictype.doc.html
- **S13** PhaseTransition (2025-11-14): https://web.archive.org/web/20251114103039/https://www.warcraftlogs.com/v2-api-docs/warcraft/phasetransition.doc.html
- **S14** Archon "API Documentation" (Wayback 2026-04-09, "Last updated: December 2, 2025"): https://web.archive.org/web/20260409213402/https://www.archon.gg/wow/articles/help/api-documentation (live page: human-verification wall)
- **S15** Archon "Subscriber Benefits" (Wayback 2026-04-03, last updated 2024-11-18): https://web.archive.org/web/20260403053752/https://www.archon.gg/wow/articles/help/subscriber-benefits
- **S16** WCL "The Complete Guide to Pins" (expression language; Wayback 2024-12-01): https://web.archive.org/web/20241201043341/https://www.warcraftlogs.com/help/pins
- **S17** WCL Scripting API (live): https://www.warcraftlogs.com/scripting-api-docs/warcraft/interfaces/RpgLogs.DamageEvent.html, …/RpgLogs.HealingEvent.html, …/RpgLogs.AbsorbedEvent.html, …/RpgLogs.AbstractResourceChangeEvent.html, …/RpgLogs.ResourceData.html, …/RpgLogs.CastEvent.html, …/RpgLogs.DeathEvent.html, …/RpgLogs.DispelEvent.html, …/RpgLogs.CombatantInfoEvent.html
- **S18** Forum "[API] Events Arguments vs Expression Results" (2025-11-29): https://forums.combatlogforums.com/t/api-events-arguments-vs-expression-results/16346
- **S19** Forum "[API v2] requests limit per second/minute/hour" (2023-24): https://forums.combatlogforums.com/t/api-v2-requests-limit-per-second-minute-hour/14659
- **S20** Forum "Warcraftlogs API Positional Data" (2024-03-15): https://forums.combatlogforums.com/t/15492
- **S21** Forum "How can I retrieve a fight's Resources (HP) using API v2?" (2025-03-19): https://forums.combatlogforums.com/t/16080
- **S22** Forum "API return 429 when the point is NOT limited" (2021-12-04): https://forums.combatlogforums.com/t/12327
- **S23** Forum "[API V2] mapping between character and event sourceID" (Kihra, 2021-11-04): https://forums.combatlogforums.com/t/12277 · **S23b** Forum t/14128 (Kihra, 2023-05-09, ribbon graph): https://forums.combatlogforums.com/t/14128
- **S24** Forum "FFLogs API — Maximum number of requests per second" (Kihra, 2017): https://forums.combatlogforums.com/t/fflogs-api-maximum-number-of-requests-per-second/3659
- **S25** WoWAnalyzer `src/common/fetchWclApi.ts` (branch `midnight`, last change 2026-04-12): https://github.com/WoWAnalyzer/WoWAnalyzer/blob/midnight/src/common/fetchWclApi.ts
- **S26** WoWAnalyzer `src/parser/core/Events.ts`, `src/common/WCL_TYPES.ts`, `src/game/HIT_TYPES.ts`, `src/game/RESOURCE_TYPES.ts`: https://github.com/WoWAnalyzer/WoWAnalyzer/tree/midnight/src
- **S27** wowsims `ui/raid/import_export.ts`: https://github.com/wowsims/wotlk/blob/master/ui/raid/import_export.ts
- **S28** go-fflogs report table structs (FF Logs v1, same platform): https://pkg.go.dev/github.com/RyuaNerin/go-fflogs/structure/reporttables
- **S29** lp-spec-stats (`wcl.py`, `enrich_wcl_player_details.py`): https://github.com/WillHalloward/lp-spec-stats
- **S30** ptarjan/warcraftlogs-analysis README: https://github.com/ptarjan/warcraftlogs-analysis
- **S31** Community cost observations: https://github.com/AnnikenJE/the-lionhearts-website/issues/32 · https://github.com/Erilla/SlashWho/pull/281
- **cache** = `/home/omess/Projects/WCL_analyzer/data/cache/` (e.g. bundle `5a4749871fffb9a948b6021083646aeab8c0cb98.json`; largest damage-taken page `294a5ce7fc37cee5d650564a127e44332017a7ad.json`)
- **code** = `/home/omess/Projects/WCL_analyzer/collect_data.py`, `wcl_client.py`, `cache.py`, `docs/CHANGES_2026-09-23.md`, `docs/ROADMAP_2026-09-24.md`

## Not verified — decide with one live call each
1. The WoW v2 JSON shapes of `table(dataType: Casts | Buffs | Debuffs | Resources | Summary | Threat)`, and whether Summary
   embeds `playerDetails`.
2. The full `playerDetails` entry fields (`potionUse`, `healthstoneUse`, `specs[]`, `min/maxItemLevel`, `combatantInfo`).
3. The raw key names on `heal`, `absorbed`, `resourcechange`, `death`, `interrupt`, `dispel` events, and the fields
   `includeResources` adds.
4. The point cost per request kind (log `rateLimitData` deltas) and whether 429s carry `Retry-After` / `X-RateLimit-*`
   headers.
5. Whether filtered event queries paginate early, as [S18] suggests (request `nextPageTimestamp` on every alias).
6. The `zoneRankings` response JSON, and what `reportComponentData` can do.
