> Research input (2026-09-25) to `docs/plans/2026-09-25-player-analysis-design.md`; copied unchanged from the session scratchpad apart from this header line.

# 01 - Codebase inventory for per-player combat analysis

Scope: `/home/omess/Projects/WCL_analyzer` at commit `393fad7`. The working tree differs only in `CLAUDE.md` and an untracked `docs/CHANGES_2026-09-25.md`; no code differs. Line numbers refer to the current tree. Measurements were taken on 2026-09-25 against `data/cache/` and against the newest build, `dashboards/dashboard_2026-08-19_to_2026-09-21.html` (built 17:21). Research scripts live in `/tmp/claude-1000/-home-omess-Projects-WCL-analyzer/3e40b12f-8591-4f04-b66e-86501a74f819/scratchpad/*.py`, and their raw output is quoted in sections 3 and 4. Nothing in the repo was modified.

---

## 1. Per-player data available today

### 1.1 Per-player fields of one pull dict (`collect_data.py:1376-1406`)

| Field | Shape / granularity | Source query -> function |
|---|---|---|
| `participants` | `{label: class}`, per pull | FIGHTS_QUERY `fights.friendlyPlayers` + `masterData.actors(type:"Player")` -> `collect_data.py:1312-1316`. Labels come from `Labeller` (`598-622`): the bare name, or `Name-Realm` if the name exists on more than one realm |
| `deaths[i]` (every death, sorted by time) | `player, actor_id, class, seconds_into_fight, ability` (killing-blow name, or `"Unknown / environment"`) | Bundle `deaths_<fid>` Deaths table -> `deaths_from_table` `698-712` |
| `deaths[i]` (recap part) | `recap` (the player's own damage-taken events in `[t-window, t+0.3]`, each `{self,is_tick,player,class,ability,source,amount,absorbed,overkill,unmitigated,avoided,seconds}`), `window_damage`, `top_contributor`, `biggest_hit`, `one_shot` (biggest hit >= 60 % of the window), `hits_in_window` | DAMAGE_TAKEN_QUERY events -> `attach_recaps` `1145-1171`. The window is `DEATH_WINDOW_SECONDS` (default 6), `1138-1142` |
| `deaths[0]` only | `casts [[seconds_before, name]]` (last 25), `defensives` (the casts that match the defensive patterns), `externals [[seconds_before, name, caster]]` (defensive-looking buffs applied by someone else, deduplicated on (name, caster)), `has_cast_data: True` | casts1 entry (Casts `sourceID=dying`, Buffs `targetID=dying`) -> `attach_casts` `940-979`. Called at `1361-1362`. `[DECISION]` first death only |
| `damage_taken[i]` | One row per (player, ability) per pull: `player, class, ability, amount` (includes absorbed), `hit_amount, tick_amount, unmitigated, avoided` (count), `sources {source: events}, hits` (instances with a 2.5 s gap, `1039`), `ticks, events, times [instance starts, s], uptime_seconds` | DAMAGE_TAKEN_QUERY -> `get_damage_events` `986-1036` -> `aggregate_damage` `1043-1109`. Self-inflicted damage is skipped in the stats (`1063-1064`) |
| `damage_done[i]`, `healing_done[i]` | One row per player per pull: `name, class, spec, total, active_seconds, ilvl` | Bundle DamageDone / Healing tables -> `player_tables_from_bundle` `715-744`. The spec is parsed from `icon` (`"Priest-Holy"`) at `731-733`. Pet/NPC rows are skipped (`725`), and so are rows whose name is not a participant (`729`) |
| `parses` | `{label: {dps, hps}}` = WCL `rankPercent`, kills only | RANKINGS_QUERY -> `get_parses` `1112-1135`. Wipes return `{}` without an API call (`1117-1118`) |
| `interrupts`, `dispels` | `{label: count}` | Bundle Interrupts / Dispels tables -> `counts_from_table` `747-770`. It walks `entries -> details` and sums `total` for player ids |
| `consumables` | `{label: {flask, food, vantus, rune, <extra aura cats>, prepot}}` booleans | CombatantInfo `auras` -> `consumables_from_cinfo` `773-790`. `prepot` comes from the consumable casts (`1366-1369`) |
| `consumable_use` | `{label: {combat_potion, healing_potion, mana_potion, healthstone}}` counts (casts after pull start + 1.5 s) | cons entry -> `consumable_use` `855-879` |
| `has_extras` | bool: the bundle had Interrupts/Dispels/CombatantInfo | `1405` |

Non-player pull fields, listed for completeness: `report_code, report_title, zone, zone_id, night, night_type, fight_id, encounter_id, kill, boss_percentage, fight_percentage, duration_seconds, absolute_start_ms, pull_time, phase, phase_timeline`.

Module-level per-player state:
- `NIGHT_PLAYERS {night: {label: class}}` holds everyone who was in any fight (trash included) that night (`238`, `1296-1298`). The Raid and Home tabs use it for the bench.
- `NIGHT_FIGHTS {night: [[abs_start, abs_end, is_boss]]}` (`235`, `1289-1291`).

### 1.2 What each cached WCL response contains vs what is read

I measured this on `data/cache` with the scratchpad scripts `bundle_inspect.py`, `misc_inspect.py` and `kb_check.py`.

**CombatantInfo** (`cinfo_<fid>`, one event per player at pull start; 14-27 per bundle, average 23.1)
- Keys present: `agility, armor, auras, avoidance, block, critMelee, critRanged, critSpell, customPowerSet, dodge, expansion, faction, fight, gear, hasteMelee, hasteRanged, hasteSpell, intellect, leech, mastery, parry, pvpTalents, secondaryCustomPowerSet, sourceID, specID, speed, stamina, strength, talentTree, talents, tertiaryCustomPowerSet, timestamp, type, versatilityDamageDone, versatilityDamageReduction, versatilityHealingDone`. All 10,511 cached cinfo events have a non-empty `talentTree` and `gear`.
- What the collector uses: only `sourceID`, `auras[].name` and `auras[].ability` (resolved via ability names). These become the consumable booleans (`collect_data.py:777-789`).
- What it throws away:
  - `specID` (numeric, the authoritative spec)
  - `talentTree` `[{id, rank, nodeID}]` (about 3.3 KB per player), `pvpTalents`, and `talents` (always an empty list)
  - `gear` `[{id, quality, icon, itemLevel, permanentEnchant, bonusIDs, gems}]` (about 3.2 KB per player)
  - every primary, secondary and tertiary stat
  - the auras' `source`, `stacks` and `icon`. The auras include raid buffs with their caster, e.g. Blessing of the Bronze from source 1.
- Item level: CombatantInfo gear ilvl is not used. The only ilvl collected is `itemLevel` from the DamageDone/Healing table rows (`collect_data.py:740`, stored as `damage_done[].ilvl`). It is **not** put into the payload (`dash/payload.py:146-147`).
- The fixture recorder keeps only `timestamp, type, fight, sourceID, auras, specID` of cinfo (`tests/make_fixtures.py:50`), so the test fixtures contain no talents, gear or stats.

**DamageDone / Healing table rows**
- Keys present: `abilities, activeTime, activeTimeReduced, damageAbilities, gear, given, guid, icon, id, itemLevel, name, pets, taken, talents, targets, total, totalRDPSGiven, totalRDPSTaken, totalReduced, type`, plus `overheal` on Healing.
- Read: `id, name, type, icon, total, activeTime, itemLevel`.
- Discarded:
  - the per-player `abilities` list `[{guid, name, total, type, icon}]`, i.e. a per-spell damage/healing breakdown per player per pull, already in the cache
  - `targets` (damage per enemy) and `pets`
  - `taken`, `given`, `totalRDPS*` (support-spec attribution)
  - `gear`, `overheal`, `totalReduced`
- The fixture slimmer drops `gear, talents, abilities, damageAbilities, targets, given, taken, pets` (`tests/make_fixtures.py:49`).

**Deaths table rows**
- Keys present: `damage, deathWindow, events, fight, guid, healing, icon, id, killingBlow, name, overkill, timestamp, type`.
- `killingBlow` is present in 6,415 of 7,943 cached rows. The other 1,528 (19 %) become `"Unknown / environment"`.
- Read: `id, name, type, timestamp, killingBlow.name`.
- Discarded: `icon` (spec), WCL's own recap `events`, the per-ability `damage`/`healing` of the death window, `overkill`.

**Interrupts / Dispels tables**
- Shape: `entries[]` (the enemy ability, with `spellsBegun/Completed/Interrupted`, `missedCasts`) -> `details[]` (player, `total`, `abilities` used, `actors`).
- Read: the player id and `total` only.

**Rankings**
- Character keys: `amount, best, bracket, bracketData, bracketPercent, class, id, name, rank, rankPercent, server, spec, totalParses`.
- Fight-level keys: `bracket, bracketData, damageTakenExcludingTanks, deaths, difficulty, duration, encounter, execution, fightID, guild, kill, partition, roles, size, speed, zone`.
- Read: `name, server.name, rankPercent`.

**DamageTaken events**
- Keys present: `abilityGameID, absorbed, amount, blocked, buffs, fight, hitType, isAoE, mitigated, overkill, sourceID, sourceInstance, sourceMarker, subtractsFromSupportedActor, supportID, supportInstance, targetID, targetInstance, targetMarker, tick, timestamp, type, unmitigatedAmount`. `buffs` is a dot-separated list of aura ids active on the target, e.g. `"157128.1235108."`.
- Read: `type, targetID, sourceID, abilityGameID, tick, amount, absorbed, overkill, unmitigatedAmount, timestamp` (`collect_data.py:1002-1033`).
- Discarded: `buffs`, `hitType`, `mitigated`, `blocked`, `isAoE`, the markers and instance ids, and the support fields.

**Casts / Buffs** (casts1 entry, first death only)
- Raw events `{timestamp, type, sourceID, targetID, abilityGameID, fight}`.
- Types kept: `cast`/`begincast` (`951`) and `applybuff`/`refreshbuff`/`applybuffstack` (`962`).

**Not fetched at all today:**
- a player's casts over the whole fight (only the dying player's window, and the consumable ability ids)
- player buffs/debuffs over the fight
- Healing events and DamageDone events
- resources, summons, threat, debuffs on enemies
- a Casts table (dropped in bundle v3; `209`: "WCL's Casts table does not list item uses")
- `rateLimitData`

### 1.3 GraphQL text (verbatim), variables, batching, cache keys

**FIGHTS_QUERY** (`collect_data.py:85-107`). Vars `{code}`, 1 per report, run in pass 1 (`1269`). `cq()` -> `cached_query`, key `sha1(text+vars)`.
```graphql
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
```
**PHASES_QUERY** (`110-126`). Vars `{code}`, 1 per report, `cq()`.
```graphql
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
```
**ABILITIES_QUERY** (`129-139`). Vars `{code}`, 1 per report, `cq()`. Only `gameID -> name` is kept (`579-585`).
```graphql
query ReportAbilities($code: String!) {
    reportData {
        report(code: $code) {
            masterData {
                abilities { gameID name type }
            }
        }
    }
}
```
**NPC_ACTORS_QUERY** (`142-152`). Vars `{code}`, 1 per report, `cq()`.
```graphql
query ReportNPCs($code: String!) {
    reportData {
        report(code: $code) {
            masterData {
                actors(type: "NPC") { id name }
            }
        }
    }
}
```
**DAMAGE_TAKEN_QUERY** (`155-166`). Vars `{code, fightID, start, end}`, where `start` is the page cursor. One request per page per fight, not aliased. `cq(..., refresh=needs_refresh(fight))`, one cache file per page (key includes `start`).
```graphql
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
```
**RANKINGS_QUERY** (`169-178`). Vars `{code, fightID}`, 1 per **kill** (two aliases in one request), `cq()`.
```graphql
query FightRankings($code: String!, $fightID: Int!) {
    reportData {
        report(code: $code) {
            dps: rankings(fightIDs: [$fightID], playerMetric: dps)
            hps: rankings(fightIDs: [$fightID], playerMetric: hps)
        }
    }
}
```
**REPORT_META_QUERY** (`180-192`). Vars `{code}`, used only for `--reports` / `_include` codes (`fetch_reports_by_code` `368-390`). Calls `run_query` directly and is **never cached**.
```graphql
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
```
**ZONE_ENCOUNTERS_QUERY** (`194-203`). Vars `{id}`, 1 per zone per build, from `zone_encounter_order` (`335-345`) called by `dash/page.py:45-46`. Uses `cached_query`.
```graphql
query ZoneEncounters($id: Int!) {
    worldData {
        zone(id: $id) {
            name
            encounters { id name }
        }
    }
}
```
**Guild report list** (`fetch_reports.py:20-49`, loop `76-94`). Paginated by `page` / `has_more_pages`; **never cached**.
```graphql
query GuildReports(
    $guildName: String!,
    $guildServerSlug: String!,
    $guildServerRegion: String!,
    $startTime: Float!,
    $endTime: Float!,
    $page: Int!
) {
    reportData {
        reports(
            guildName: $guildName,
            guildServerSlug: $guildServerSlug,
            guildServerRegion: $guildServerRegion,
            startTime: $startTime,
            endTime: $endTime,
            page: $page
        ) {
            data {
                code
                title
                startTime
                endTime
                zone { id name }
            }
            has_more_pages
        }
    }
}
```
**Fight bundle builder** `_bundle_query` (`collect_data.py:633-643`):
- `BUNDLE_TABLES = {"damage": "DamageDone", "healing": "Healing", "deaths": "Deaths", "interrupts": "Interrupts", "dispels": "Dispels"}` (`207-208`).
- `BUNDLE_VERSION = "v3"` (`209`), `BUNDLE_BATCH = 5` fights per request (`210`).
- Only `$code` is a variable. Fight ids and times are inlined into the text. The string is:
```
query FightBundle($code: String!) { reportData { report(code: $code) { <parts> } } }
```
- Per fight `<fid>` it adds these parts:
```
damage_<fid>: table(dataType: DamageDone, fightIDs: [<fid>])
healing_<fid>: table(dataType: Healing, fightIDs: [<fid>])
deaths_<fid>: table(dataType: Deaths, fightIDs: [<fid>])
interrupts_<fid>: table(dataType: Interrupts, fightIDs: [<fid>])        # extras only
dispels_<fid>: table(dataType: Dispels, fightIDs: [<fid>])              # extras only
cinfo_<fid>: events(dataType: CombatantInfo, fightIDs: [<fid>], startTime: <int start>, endTime: <int end>, limit: 200) { data }   # extras only
```
- Fetch and cache: `_fetch_bundle_batch` (`646-669`) sends one request per batch and stores one entry per fight with `put_entry`.
- Key (`_bundle_key` `629-630`): `bundle:v3:full:<code>:<fid>`, or `bundle:v3:min:<code>:<fid>` when the extras were rejected. The stored file key is `entry:` + that string.
- Stored value: `{damage, healing, deaths, interrupts, dispels, cinfo:[...], extras:bool}` (`664-666`).
- Fallback: on `WCLError` it warns once and sets the global `_bundle_extras_ok = False` (`223`, `655-658`). From then on the run uses min bundles (damage/healing/deaths only).
- `get_fight_bundles` (`672-689`) serves cache hits and `pool.map`s the missing batches.

**Casts + buffs before the first death** `get_first_death_casts` (`890-937`):
- `CASTS_BATCH = 10` pulls per request (`211`), `CASTS_VERSION = "v2"` (`212`).
- Window: `end = fight.start + death.s*1000 + 300`, `start = max(fight.start, end - window*1000 - 300)` (`912-913`).
- Wrapper: `query FirstDeathCasts($code: String!) { reportData { report(code: $code) { <parts> } } }`. Per pull:
```
casts_<fid>: events(dataType: Casts, fightIDs: [<fid>], sourceID: <actor_id>, startTime: <int start>, endTime: <int end>, limit: 300) { data }
buffs_<fid>: events(dataType: Buffs, fightIDs: [<fid>], targetID: <actor_id>, startTime: <int start>, endTime: <int end>, limit: 300) { data }
```
- Key (`886-887`): `casts1:v2:<code>:<fid>:<window:g>`, stored value `{data:[casts], buffs:[buffs]}`.
- On `WCLError` it warns once and returns `{}` for that batch (nothing is cached, so the next run retries).

**Consumable casts** `get_consumable_casts` (`812-852`):
- `CASTS_BATCH = 10` fights per request, `CONSUMABLES_VERSION = "v1"` (`213`).
- `ids` = report abilities whose name matches a cast category (`consumable_ability_ids` `797-805`).
- Server-side filter: `expr = "ability.id in (<sorted ids>)"`.
- Wrapper: `query ConsumableCasts($code: String!) { reportData { report(code: $code) { <parts> } } }`. Per fight:
```
cons_<fid>: events(dataType: Casts, fightIDs: [<fid>], startTime: <int start - 5000>, endTime: <int end>, filterExpression: "ability.id in (…)", limit: 2000) { data }
```
- Key (`808-809`): `cons:v1:<code>:<fid>:<sha1(','.join(sorted ids))[:12]>`, stored value `{data:[...]}`.
- With no matching ids it makes no request (`819-820`).

Also present, but part of M+ roster tooling rather than per-player analysis: `mplus.py:136-146` `query Servers($region, $page)` and `mplus.py:170-185` `query Actors($code)`, both through `cached_query`.

---

## 2. Fetching mechanics

**Thread pool**
- One `ThreadPoolExecutor(max_workers=parallelism())` per `collect()` call (`collect_data.py:1274`). It is shut down in `finally` (`1414-1415`).
- `parallelism()` reads `WCL_PARALLEL` (default 4, minimum 1, `78-82`).
- Reports are processed **sequentially** (`1276`). Inside a report, four sequential phases each fan out on the pool:
  1. bundles, `pool.map(_fetch_bundle_batch, batches)` (`687`)
  2. per selected fight, `fetch_fight` = damage-taken pages (sequential inside the worker) + rankings (`1335-1342`)
  3. first-death casts batches (`935`)
  4. consumable-cast batches (`850`)
- These run on the main thread: FIGHTS (pass 1, `1269`), PHASES / ABILITIES / NPC_ACTORS (`1288-1293`), and all pull assembly (`1356-1407`).

**Refresh flag and threads**
- `_refresh_current` is a module global set on the main thread (`1268`, `1278`). `cq()` reads it when `refresh=None` (`510-512`).
- Worker calls pass `refresh` explicitly (`1337-1339`). Any new `cq()` call made from a worker must do the same.

**Retries** (`wcl_client.py:83-131`)
- Timeout: `WCL_TIMEOUT_SECONDS` (60, `23`). Attempts: `WCL_MAX_ATTEMPTS` (4, `24`).
- 401: drop the token and retry immediately (`103-109`).
- 429 / 5xx: sleep `Retry-After` (capped at 120 s) or back off `2*2^attempt` capped at 30 s (`71-80`, `110-113`).
- `ConnectionError` / `Timeout`: back off (`116-119`).
- GraphQL errors containing "rate limit": sleep 60 s and retry (`124-127`). Any other GraphQL error raises `WCLError` at once (`128`).
- The token is cached under a lock and refreshed 60 s early (`36-68`). One shared `requests.Session` (`29`).
- No request-level throttling or WCL points accounting (`rateLimitData`): not present.
- Graceful fallbacks: phases `535-539`, rankings `1119-1123`, bundle extras `655-658`, casts `919-923`, consumables `835-839`.

**HTTP requests for one new report with N selected pulls** (counted from the code)
- 1 FIGHTS (pass 1)
- 3 report-level requests: PHASES, ABILITIES, NPC_ACTORS. All four report-level requests are spent even when 0 pulls are selected, because the selection check is at `1322`, after `1288-1293`.
- `ceil(N/5)` bundle requests, plus 1 wasted request once per run if WCL rejects the extras
- `sum(pages)` DamageTaken requests. The cache shows **1.41 pages per fight** (337 pages / 239 fights; `events_inspect.py`)
- K RANKINGS, one per kill
- `ceil(D/10)` first-death casts, where D = pulls with at least one death
- `ceil(N/10)` consumable-cast requests (0 if no consumable ability matched)

Worked example: N=15, K=2 (the build's kill rate is 57/221, about 26 %), D=15:
- 4 + 3 + ~21 + 2 + 2 + 2 = **about 34 requests**.
- On disk that is about 15 x (573 KB bundle + 2.11 MB damage-taken) = about 40 MB per report.

Build-level extras (not per report):
- guild report list: at least 1 page, never cached
- REPORT_META: one per `_include` / `--reports` code, never cached
- ZONE_ENCOUNTERS: 1 per zone (cached)
- Raider.IO for M+

Cost of other report states:
- An unchanged cached report costs 0 requests.
- A changed (live) report re-fetches its 4 report-level queries plus the per-fight requests for fights that ended after the previously seen endTime.

**Pagination**
- Only DamageTaken events paginate: the `while start is not None` loop follows `nextPageTimestamp` (`995-1034`).
- CombatantInfo (`limit: 200`), first-death Casts/Buffs (`limit: 300`) and consumable Casts (`limit: 2000`) do not request `nextPageTimestamp`, so they are **silently truncated** at the limit.
- The guild report list paginates with `page` / `has_more_pages` (`fetch_reports.py:76-94`).

**`events(...)` arguments in use** (quoted)
- `filterExpression`: only in the consumable casts: `filterExpression: \"{expr}\"` with `expr = "ability.id in (" + ",".join(...) + ")"` (`829-833`).
- `startTime` / `endTime`: every events call. DamageTaken `startTime: $start, endTime: $end` (`159`); cinfo `startTime: {int(f['startTime'])}, endTime: {int(f['endTime'])}` (`641-642`); casts/buffs `startTime: {int(start)}, endTime: {int(end)}` (`914-917`); cons `startTime: {int(f['startTime']) - PREPOT_BEFORE_MS}, endTime: {int(f['endTime'])}` (`832-833`).
- `limit`: 10000 / 200 / 300 / 300 / 2000 (as above).
- `sourceID` / `targetID`: casts (`sourceID: {death['actor_id']}`) and buffs (`targetID: {death['actor_id']}`) (`914-916`).
- `useAbilityIDs`, `hostilityType`, `translate`, `includeResources`: not present (grep).

## 3. Cache

**Two entry kinds** (`cache.py`)

`cached_query(query, variables, refresh=False)` (`67-89`)
- File: `data/cache/<sha1(query + json.dumps(variables, sort_keys=True))>.json` (`45-51`).
- Returns the cached file unless `refresh` or `FORCE_REFRESH` is set (`--refresh`, `build_dashboard.py:122-125`, `cache.py:35`). Otherwise it calls `run_query`, counts an API call and overwrites the file.
- Changing a query's text changes the hash, so the query is re-fetched automatically.

`get_entry(key, refresh=False)` / `put_entry(key, data)` (`92-102`)
- File: `data/cache/<sha1("entry:" + key)>.json`.
- `get_entry` returns `None` when the file is missing or a refresh is requested. The caller then fetches, calls `count_api_call(n, refreshed)` (`105-109`) and `put_entry`s one entry per fight.
- Changing the query text does **not** invalidate these entries. Only the version tag in the key does (`BUNDLE_VERSION` / `CASTS_VERSION` / `CONSUMABLES_VERSION`, `collect_data.py:209-213`).

Common behaviour:
- Writes are atomic (temp file + `os.replace`, `59-64`). Stats sit behind a lock (`37-42`).
- On-disk layout is one flat directory of `<sha1>.json` files plus `report_meta.json`. There is no index and no garbage collection: old-version files stay forever.
- The `cache.py` docstring still says "a `.cache/` folder next to this file" (`16-17`). That is stale: `CACHE_DIR = data/cache` (`31`).

**Key formats** (entry kind)
- Bundle: `bundle:v3:{full|min}:<code>:<fid>` (`collect_data.py:629-630`)
- First-death casts: `casts1:v2:<code>:<fid>:<window:g>` (`886-887`). The key depends on the `DEATH_WINDOW_SECONDS` env value.
- Consumable casts: `cons:v1:<code>:<fid>:<sha1(sorted ids)[:12]>` (`808-809`). The key depends on which ability ids `config/consumables.json` matches.

**Refresh semantics** (fight granularity)
- `report_meta.json` stores `{code: endTime seen}` (`49-63`). `changed = seen_end is not None and seen_end != report.endTime` (`1266-1267`).
- A changed report sets `_refresh_current`, so FIGHTS, PHASES, ABILITIES and NPC_ACTORS are re-downloaded (`1268`, `1278`).
- Per fight, `needs_refresh(f) = changed and seen_end is not None and report.startTime + f.endTime > seen_end` (`1285-1286`). It is passed to bundles, damage-taken pages, rankings, casts1 and cons. So only fights that ended after the previously seen endTime are re-fetched.
- Meta is saved after each report (`1412-1413`), and also for reports with 0 selected pulls (`1328-1329`).
- A fight that was never cached (e.g. a difficulty newly added to `--difficulty`) is simply "missing" and fetched.
- Rankings responses are cached whatever they contain. An empty ranking cached shortly after a kill is not re-checked unless that fight is refreshed (reading of `get_parses` `1112-1135` + `cq`).

**Size right now**
- `du -sh data/cache` = 962M (1,003 MB) in 2,298 files.
- Every current-version report-specific entry, **and** a large amount of orphaned data from older query versions:
  - 239 non-v3 bundles plus 221 v2 bundles, which carry the `casts` + `prepull` keys the code no longer writes
  - 450 per-fight responses of the `damage,healing` and `table` shapes, which no current query produces (older code versions)
  - 4 REPORT_META responses cached by an older version
- **Current-version** bundle + damage-taken + rankings entries total 632 MB (`active_cache.py`).

**Raw events stored**
- DamageTaken pages are **raw events**: 337 files, 504.6 MB. Averages: 1.50 MB per page, 6,021 events per page, about 249 B per event. The largest page is 2.63 MB (10,031 events). Per fight: 2.11 MB over 1.41 pages.
- The bundle's `cinfo` is raw CombatantInfo: about 186 KB per bundle average, 220 KB max. v3 bundles average 573 KB per fight.
- casts1 holds raw cast/buff events (5.5 KB average, 17.6 KB max). cons holds raw filtered casts (1.2 KB average). The 445 files of `{data}` shape are consumable casts, but may also include leftover casts1:v1 entries, which had the same shape before `buffs` was added.

Raw output: `du` + `ls -S` (`out_du.txt`):
```
962M	data/cache
2298
total 984800
-rw-r--r-- 1 omess omess 2626314 Sep 21 20:56 294a5ce7fc37cee5d650564a127e44332017a7ad.json
-rw-r--r-- 1 omess omess 2618559 Sep 21 20:56 bed8c861a348e7af7a55718511f4fb77b429c3dd.json
-rw-r--r-- 1 omess omess 2603023 Sep 22 18:34 21d8e8648a84263c73f93d734b1d76631b392345.json
-rw-r--r-- 1 omess omess 2582602 Sep 21 20:56 1a80346711fee5acc7739fa893e7deacc70b6baf.json
-rw-r--r-- 1 omess omess 2581176 Sep 21 20:56 4415047e24a09786633fa7cc558424fd18d1d431.json
```
Raw output: `cache_classify.py data/cache` (no current query produces the two "query other" shapes, so they are leftovers of older per-fight queries; the "entry bundle (full)" row counts v1, v2 and v3 bundles together):
```
category                                       files  total MB   avg KB   max KB  max file
query DAMAGE_TAKEN (events page)                 337     504.6   1497.3   2626.3  294a5ce7fc37cee5d650564a127e44332017a7ad.json
entry bundle (full)                              681     417.3    612.8   1213.9  c1bdc231338a46b06b611c7fafbcb1a8b5a804d5.json
query other: damage,healing                      225      63.1    280.3    374.0  9ab79155769b8ddd9fb7aaab55e08d1530d7eeab.json
query other: table                               225      12.4     55.0    107.6  2aacd77fbf8dbe52c8f7f9b57ebe6b68d96adc30.json
query ABILITIES                                   18       1.9    107.3    191.8  086e7576be394361abb37ecfd0cc0d3f3a98f5a9.json
entry casts1 (first-death casts+buffs)           210       1.1      5.5     17.6  3db58dd176900b9815b823e4aa283787696cf443.json
query RANKINGS                                    71       1.0     14.8     17.7  00f8863f626e300a1c8a6669409938bef6d783ee.json
query FIGHTS                                      44       1.0     23.6    163.4  5c8f002fe8588aa2c7dc022dfcce2529ed2b5cc5.json
entry cons (consumable casts)                    445       0.5      1.2      6.4  ff31731840a902adff17b022589715399ca9425f.json
query PHASES                                      18       0.1      3.1      5.5  f4af7220f98e4d85ef103bf4c23caea65382f890.json
query NPC_ACTORS                                  18       0.1      3.1      9.1  350ef6eb3a1e701a0b06c6f675d5e8cdee0cf2aa.json
query REPORT_META (should not be cached)           4       0.0      0.2      0.2  d4d61ca2e33bb533742954013258db4be0ca46a0.json
report_meta.json                                   1       0.0      0.6      0.6  report_meta.json
query ZONE_ENCOUNTERS                              1       0.0      0.5      0.5  d436a6e367c108265ceec8c3f2d81293c1a2532e.json
TOTAL 1003.1 MB in 2298 files
```
Raw output: `active_cache.py` (only keys the current code would read: `bundle:v3:full`, current DAMAGE_TAKEN and RANKINGS text, over the 18 reports in `report_meta.json`):
```
{
 "reports": 18,
 "boss_fights": 244,
 "bundles": 221,
 "bundle_bytes": 126621497,
 "dt_pages": 337,
 "dt_bytes": 504593587,
 "fights_with_dt": 239,
 "rank": 71,
 "rank_bytes": 1049440
}
v3 bundle avg 573 KB/fight; damage-taken 2.11 MB/fight over 1.41 pages
active (current-version) bundle + damage-taken + rankings bytes: 632 MB
```
Raw output: `events_inspect.py data/cache`:
```
damage-taken pages: 337, pages with nextPageTimestamp (i.e. fight continues on another page): 98
=> ~239 fights cached, 1.41 pages per fight
events per page: min 18 max 10031 avg 6021; bytes per event ~249
event types (first 200 per page): {'damage': 67144}
event keys seen: ['abilityGameID', 'absorbed', 'amount', 'blocked', 'buffs', 'fight', 'hitType', 'isAoE', 'mitigated', 'overkill', 'sourceID', 'sourceInstance', 'sourceMarker', 'subtractsFromSupportedActor', 'supportID', 'supportInstance', 'targetID', 'targetInstance', 'targetMarker', 'tick', 'timestamp', 'type', 'unmitigatedAmount']
report_meta.json entries: 18
```
The test fixtures are `tests/fixtures/`: 4.3 MB, 23 cache files plus `report.json`, largest 1.47 MB.

---

## 4. Payload budget

**Per-pull payload fields** (`dash/payload.py:135-151`)

| Key | Content |
|---|---|
| `i` | pull index (1-based) |
| `n` | night |
| `t` | pull time HH:MM |
| `k` | kill |
| `p` | boss HP % |
| `fp` | fight % |
| `d` | duration s |
| `a` | absolute start ms |
| `o` | open night |
| `ph` | end phase |
| `pt` | phase timeline `[[name, s]]` |
| `code`, `fid` | report code and fight id |
| `parts` | `{label: class}` |
| `specs` | `{label: spec}`, via `pull_specs` |
| `deaths` | list of `{pl, cl, s, kb, tc, os, w, recap:[[s_before, ability, source, amount, self]] (last 8)}`. The first death adds `hc, def [[s,name]], cs [[s,name]], ext [[s,name,caster]]` (`_death_payload` `70-81`) |
| `dt` | `[[player, ability, hits, amount, times?, phaseCounts?]]`. `times` only for avoidable abilities, `phaseCounts` only when the pull has phases; trailing `None`s are popped (`124-131`) |
| `parses` | `{label: {dps, hps}}` |
| `dd`, `hd` | `[[name, class, spec, total, active_s]]`. **No ilvl** |
| `ir`, `ds` | interrupt / dispel counts `{label: n}` |
| `use` | `{label: [counts in usecats order]}` |
| `cons` | `{label: [0/1 in cats order]}` |
| `hx` | bundle had extras |

Boss-level keys (`154-160`): `boss, diff, avoidable, ignored, break_minutes, busy {night: [[start,end]]}, src {ability: [top 3 sources]}, cats, usecats, pulls`.

Encoding: `json.dumps(separators=(",",":"), ensure_ascii=False)`, then `gzip.compress(level 9)` + base64 (`161-165`). `--uncompressed` embeds `application/json` with `</` escaped.

Parts of the pull dict that are **not** in the payload: `ilvl`, `biggest_hit`, `hits_in_window`, `actor_id`, the `damage_taken` sub-fields (`ticks, hit_amount, tick_amount, unmitigated, avoided, uptime_seconds, events`, and `times` for non-avoidable abilities), and `consumable_use` naming beyond the `usecats` order.

**Measurement** of the newest build, `dashboards/dashboard_2026-08-19_to_2026-09-21.html` (raw output of `measure_payload.py`):
```
file: dashboard_2026-08-19_to_2026-09-21.html
total file size: 1,851,828 B (1.852 MB)

tab    boss (diff)                            pulls     b64 B    gzip B     JSON B  ratio b64 B/pull JSON B/pull
tab0   Nek'zali the Soulcoiler (Normal)           5    19,460    14,595     65,153   4.46      3,892      13,031
tab1   Entombed Sentinels (Normal)                6    27,296    20,470    102,063   4.99      4,549      17,010
tab2   Vashnik the Malignant (Normal)             3    18,296    13,722     54,632   3.98      6,099      18,211
tab3   The Lost Explorers (Normal)                4    19,396    14,547     63,682   4.38      4,849      15,920
tab4   Sszorak (Normal)                           9    34,800    26,098    140,195   5.37      3,867      15,577
tab5   The Twin Fangs (Normal)                    4    23,340    17,503     78,302   4.47      5,835      19,576
tab6   The Coiled Altar (Normal)                  8    75,980    56,983    287,909   5.05      9,498      35,989
tab7   Ula'tek (Normal)                           8    41,988    31,490    176,477   5.60      5,248      22,060
tab8   Nek'zali the Soulcoiler (Heroic)           8    41,500    31,124    162,472   5.22      5,188      20,309
tab9   Entombed Sentinels (Heroic)               20   119,780    89,835    531,285   5.91      5,989      26,564
tab10  Vashnik the Malignant (Heroic)             8    56,600    42,448    198,260   4.67      7,075      24,782
tab11  The Lost Explorers (Heroic)                6    31,140    23,354    111,615   4.78      5,190      18,602
tab12  Sszorak (Heroic)                          40   196,844   147,633    936,300   6.34      4,921      23,408
tab13  The Twin Fangs (Heroic)                   16    98,484    73,861    414,197   5.61      6,155      25,887
tab14  The Coiled Altar (Heroic)                 27   238,868   179,150    958,472   5.35      8,847      35,499
tab15  Ula'tek (Heroic)                          49   250,996   188,247  1,164,829   6.19      5,122      23,772
TOTAL                                           221 1,294,768   971,060  5,445,843   5.61      5,859      24,642

payload (base64) share of file: 69.9%
boss tabs: 16; pulls: 221; distinct reports: 15; raid nights: 14; distinct players in pulls: 66

raw JSON bytes by per-pull field (all tabs), largest first:
  dt                      2,551,194 B   46.8%    11,544 B/pull
  deaths                  1,806,656 B   33.2%     8,175 B/pull
  hd                        241,706 B    4.4%     1,094 B/pull
  dd                        238,828 B    4.4%     1,081 B/pull
  cons                      119,981 B    2.2%       543 B/pull
  specs                     113,170 B    2.1%       512 B/pull
  parts                     106,836 B    2.0%       483 B/pull
  (boss) busy                67,710 B    1.2%
  use                        47,078 B    0.9%       213 B/pull
  parses                     42,194 B    0.8%       191 B/pull
  pt                         22,817 B    0.4%       103 B/pull
  (boss) src                 22,233 B    0.4%
  ds                         11,865 B    0.2%        54 B/pull
  ph                          6,432 B    0.1%        29 B/pull
  ir                          6,042 B    0.1%        27 B/pull
  code                        5,746 B    0.1%        26 B/pull
  n                           4,831 B    0.1%        22 B/pull
  a                           3,978 B    0.1%        18 B/pull
  t                           2,652 B    0.0%        12 B/pull
  (boss) ignored              2,544 B    0.0%
  hx                          2,210 B    0.0%        10 B/pull
  d                           2,175 B    0.0%        10 B/pull
  o                           2,172 B    0.0%        10 B/pull
  k                           2,153 B    0.0%        10 B/pull
  fp                          2,139 B    0.0%        10 B/pull
  fid                         1,938 B    0.0%         9 B/pull
  p                           1,918 B    0.0%         9 B/pull
  (boss) avoidable            1,672 B    0.0%
  i                           1,433 B    0.0%         6 B/pull
  (boss) usecats              1,154 B    0.0%
  (boss) cats                   784 B    0.0%
  (boss) boss                   408 B    0.0%
  (boss) break_minutes          320 B    0.0%
  (boss) diff                   256 B    0.0%

inline <style> (tokens.css + dash.css): 29,434 B
inline <script> blocks: 7 = dash.js 100,974 B + 6 Plotly figure scripts 22,308 B
external scripts: ['https://cdn.plot.ly/plotly-2.35.2.min.js']
Python-rendered Plotly divs: 6
rest of file (HTML of Home/Raid/Players/M+ incl. Plotly figure JSON, pull grids, toolbar): 404,344 B
  section tabHome: 38,107 B
  section tabRaid_main: 91,497 B
  section tabRaid_open: 61,837 B
  section tabPlayers: 14,281 B
  section tabMplus: 44,625 B
  pull grids (all boss tabs): 135,786 B
```
Raw output of `payload_stats.py` on the same file:
```
pulls 221, kills 57, by difficulty {'Normal': 47, 'Heroic': 174}
avg per pull: participants 23.2, damage_taken rows 229, deaths 17.8, dd rows 22.5, hd rows 23.0, duration 249 s
player-pulls 5121; player-pulls without a spec in the payload: 93
player-pulls by inferred role: {'dps': 3657, 'healer': 937, 'tank': 434}
distinct spec names: 32 -> {'Arcane': 529, 'Holy': 478, 'BeastMastery': 419, 'Elemental': 380, 'Restoration': 241, 'Unholy': 215, 'Arms': 211, 'Havoc': 201, 'Affliction': 201, 'Balance': 198, 'Mistweaver': 189, 'Vengeance': 181, 'Protection': 176, 'Retribution': 173, 'Subtlety': 149, 'Assassination': 148, 'Survival': 147, 'Fury': 145, 'Devastation': 144, 'Shadow': 136, 'Frost': 86, 'Windwalker': 49, 'Augmentation': 40, 'Enhancement': 37, 'Blood': 36, 'Destruction': 27, 'Brewmaster': 26, 'Discipline': 16, 'Guardian': 15, 'Marksmanship': 13, 'Preservation': 13, 'Outlaw': 9}
total combat time in payload: 15.3 h
```
Summary:
- The file is 1.85 MB. The 16 boss payloads are 1.29 MB of base64 (69.9 % of the file), which is 0.97 MB of gzip or 5.45 MB of raw JSON.
- Raw JSON to gzip is 5.61:1; base64 adds 4/3.
- Per pull: **about 5.9 KB base64**, 24.6 KB raw JSON. Per player-pull (5,121 of them): about 253 B base64.
- `dt` (46.8 % of raw JSON) and `deaths` (33.2 %) dominate. `dd` + `hd` together are 8.8 %.
- Headroom to Discord's 10 MB is about 8.1 MB.

**Other assets**
- Plotly is **not inlined**: `<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'>` (`dash/common.py:35`, emitted at `dash/page.py:176`). Python charts use `include_plotlyjs=False` (`dash/common.py:306`), so the page needs network access for charts.
- `dash.js` is inlined at `dash/page.py:208`: 100,974 B in the page (100,972 B on disk).
- `tokens.css` + `dash.css` are inlined at `dash/page.py:178-179`: 29,434 B in the page (2,001 + 27,430 B on disk).
- The 6 Python-rendered Plotly figure scripts take 22,308 B.
- The pull grids of all boss tabs take 135,786 B.
- Section sizes: Home 38 KB, Raid main 91 KB, Raid open 62 KB, Players (static) 14 KB, Mythic+ 45 KB.

---

## 5. Players tab and player focus today

**Players tab, static part** (`dash/players.py:8-59`)
- Built by `players_tab(bosses, avoidable_cfg)` and mounted at `dash/page.py:113-115` inside `div#static_tabPlayers`, followed by an empty `div#detail_tabPlayers`.
- It merges `player_stats()` per boss into one table, "Players across all bosses". Columns: Player (`player_cell`, no role), Pulls, Bosses, First death, "Started the wipe in % of pulls", Avoidable hits / pull (only if any boss has avoidable abilities), and "What killed them" (top 2 first-death causes).
- Rows are sorted by first-death rate. Players under 25 % of the maximum pull count get `lowpart` and sit behind a "Show N hidden players" checkbox (`38-58`).
- No DPS, HPS, parse, spec, role, consumable or interrupt columns.

**Players tab, dynamic part** (`dash/static/dash.js:953-990`, `renderPlayersTab`)
- It renders only while a global filter is active; otherwise the static part shows (`956`). It recomputes from **all boss payloads in the browser** (`PD[tab].data`).
- With a player selected, one row per boss (`960-974`): Boss (`gotab` button), Pulls, First death, Started the wipe, Deaths, Avoidable hits / pull, Dmg taken / pull, DPS, HPS. DPS and HPS are total / pull seconds.
- With a night or night type selected, the static table is recomputed for those nights with a limit of 15 (`975-986`).

**Player focus block in a boss tab** (`playerFocus`, `dash.js:708-766`)
- Rendered at the top of the boss panel when the toolbar Player is set (`803`). `S` is then restricted to the pulls the player was in (`784`), and every section below renders for that subset.
- KPI cards, computed against "regulars" (players in at least 50 % of the pulls):
  - Pulls
  - Started the wipe: count, % of pulls, `rankOf`, and a delta against the raid median (`738`)
  - Died: count and per pull (`739`)
  - Avoidable hits / pull: rank (1 = worst) and delta against the median (`740`)
  - Damage taken / pull: rank and delta (`741`)
  - Output: players who played more than one role get "As {role} ({specs})" cards with DPS/HPS and % active per role (`742-746`). Everyone else gets a DPS card (with % active and rank by total) and an HPS card when healing exceeds damage (`747-750`).
  - Interrupts / dispels, total and per pull (`751`)
- Then a note for multi-role players (`753`) and a grouped bar chart of hits per pull by ability against the raid average, top 12 by amount, gold = avoidable (`754-760`).
- Then a table of that player's deaths with Tags, "What killed them", Killing blow, Defensives (`defCell`) and "Last seconds" (`recapHtml`) (`761-764`).
- Every sortable table row whose `data-player` equals the player gets class `me` (`825`, CSS `dash/static/dash.css:189-190`). The pull grid greys out pulls the player was absent from (`774`).

**`player_stats`** (`dash/common.py:384-404`)
- Returns `name -> {class, pulls, first_deaths, avoid_hits, causes: Counter}`.
- It counts `pulls` from `p["participants"]` and looks only at `p["deaths"][0]`: `first_deaths += 1`, `causes[top_contributor or ability] += 1`. `avoid_hits` sums `damage_taken[].hits` whose normalised ability is in `avoidable`.
- Used by `dash/players.py:14` and the Home wipe-starter insight (`dash/home.py:167`).
- The JS twins inside `secDeaths` (`dash.js:594-597`) and `renderPlayersTab` compute the same numbers from the payload.

**Role / spec inference**
- The spec comes **only** from the WCL DamageDone/Healing table rows: `icon` `"Class-Spec"` is split, and kept only if the prefix equals the row `type` (`collect_data.py:731-733`).
- `pull_specs(p)` (`dash/common.py:147-156`) takes the damage-table spec, then overrides it with the healing-table spec only when that spec is a healer spec. It ships as the payload's `specs` (`payload.py:142`).
- `spec_role` (`dash/common.py:139-144`) uses `TANK_SPECS = {Protection, Blood, Vengeance, Guardian, Brewmaster}` and `HEALER_SPECS = {Holy, Discipline, Restoration, Mistweaver, Preservation}` (`135-136`); everything else is dps.
- The JS twin is `TANKS` / `HEALERS` / `roleOf` (`dash.js:44-46`).
- Aggregates:
  - `player_roles` gives the dominant role (`common.py:159-165`)
  - `player_role_labels` gives e.g. `"healer 29 / dps 20"` (`168-180`), used in the toolbar player picker (`page.py:128-131`)
  - JS `rolesOf` / `roleLabel` (`dash.js:405-412`) feed the role tags, Hide tanks, the damage-done role groups (`508`) and the "tank" pattern of "Who gets hit" (`658`)
- Known gaps:
  - CombatantInfo `specID` and the rankings `spec` are fetched but discarded.
  - A player with no row in either table has no spec. That is 93 of 5,121 player-pulls (1.8 %) in the newest build; they get role `''` / dps.
  - Spec names are WCL CamelCase identifiers (`BeastMastery`).
  - The role is looked up by spec name only. This is safe today because shared names map to one role (Holy, Protection, Restoration, Frost).
  - There is no specID -> spec table, and no class+spec key for per-spec rules.
  - Support attribution (Augmentation `taken`/`given`) is ignored.
  - The static Players tab shows no role or spec.

---

## 6. Ability metadata

- **ABILITIES / masterData** (`ABILITIES_QUERY`, `collect_data.py:129-139`)
  - Fetched fields: `gameID, name, type`. `type` is a numeric string. Values seen: `0, 1, 2, 4, 8, 12, 16, 28, 32, 33, 36, 40, 48, 5, 6, 64, 68, 72, 80, 96, 106, 124-127`, which look like WCL's spell-school bitmask. That is an inference; the code never reads the field.
  - One report holds about 1,900 abilities (107 KB average response).
  - `get_ability_names` keeps only `{gameID: name}` (`579-585`). `icon` is not requested.
  - Per-ability icons are present inside the table rows (`abilities[].icon`) and interrupt entries (`abilityIcon`), but are not read.
- **`data/abilities_seen.json`**
  - Written every build by `write_abilities_seen` (`build_dashboard.py:37-56`).
  - Shape: `{boss: {ability_name: {hits: int, sources: [top 3 source names]}}}`, sorted by hits.
  - It covers only **damage taken** by players (from `damage_taken`). No ids, icons, types or player-side abilities. Current file: 8 bosses, 406 abilities, 41.7 KB. It is the input for `avoidable.json`.
- **Cooldown / GCD / charges / cast time / spell book:** not present anywhere in Python, JS or config (grep for `cooldown|gcd|charges|haste|talent|gear|specID` finds only the ilvl lines and the fixture slimmer's comments). Defensives and consumables are recognised by **name substring** only (`is_defensive` `498-500`, `name_matches` `428-433`).

---

## 7. Config conventions

- **Paths**: `CONFIG_DIR` from `path.py:5`. `CONSUMABLES_FILE` and `DEFENSIVES_FILE` at `collect_data.py:406-407`, `AVOIDABLE_FILE` at `dash/common.py:14`, `NIGHTS_FILE` at `collect_data.py:279`.
- **Loader**: `_load_json(path)` (`collect_data.py:472-477`) returns `None` on a missing or invalid file, and the defaults are used silently.
- **Load timing**: loaded once per `collect()` (`1229-1230`), consumables and defensives both.
- **`consumables.json`** (`consumable_patterns` `480-487`)
  - Schema: `{category: [lower-case substrings], "_comment": ...}`. A pattern starting with `-` excludes names that contain it (`name_matches` `428-433`). Keys starting with `_` are skipped.
  - The file **replaces** `DEFAULT_CONSUMABLES` (`414-423`) wholesale; there is no merge.
  - `CAST_CATEGORIES = (combat_potion, healing_potion, mana_potion, healthstone)` are matched against cast ability names (`424`). Every other category, including unknown ones, is treated as an aura at pull start (`425`, `789`).
  - A legacy `prepot` key is migrated to `combat_potion` (`485-486`).
- **`defensives.json`** (`defensive_patterns` `490-495`)
  - Schema: `{"defensives": [names]}` or a bare list. Case-insensitive substring match.
  - It replaces `DEFAULT_DEFENSIVES` (`435-469`, a per-class list of names).
- **`*.example.json` pattern**
  - `config/consumables.example.json` and `config/defensives.example.json` are byte-identical to the live files, including the comment "Copy to X.json". `avoidable.example.json` and `nights.example.json` are templates.
  - Everything in `config/` is tracked except `nights.json` and `roster.txt` (`.gitignore`).
- **`load_avoidable()`** (`dash/common.py:100-120`)
  - A missing file gives `{}`.
  - Boss keys and ability names are normalised with `normalize()` (lower-case, alphanumerics only, `collect_data.py:251-252`).
  - `"*"` is special-cased (`116`) because `normalize("*") == ""`. `_ignore` is extracted into a set (`119`). All other `_` keys (`_comment`, `_uncertain`, `_changelog`) are skipped (`118`). Values must be lists.
  - `avoidable_set(cfg, boss)` = boss set ∪ `"*"` (`123-124`). `ignore_set` is at `127-128`.
- **Validation**: `validate_config` (`build_dashboard.py:59-93`) warns about avoidable bosses without pulls and abilities that never hit anyone, and about unknown `nights.json` keys (the known list is at `81`).
- **Cache-key coupling**: the `cons` entry key hashes the matched ability ids (`808-809`), so editing the cast categories in `consumables.json` re-downloads the consumable casts. The tests read the real `config/consumables.json`; `conftest.py` redirects only `NIGHTS_FILE`, see 8(g).

---

## 8. Extension points

**(a) A new per-fight event query**

There are two existing patterns.

1. *Add an alias to the fight bundle.*
   - Edit `_bundle_query` (`collect_data.py:633-643`) and the read-back in `_fetch_bundle_batch` (`660-668`), then bump `BUNDLE_VERSION` (`209`).
   - Gotchas:
     - The version bump invalidates all 221 current bundles: about 45 requests and about 127 MB are re-downloaded, and old files are never deleted (290 MB of old bundles already sit orphaned).
     - A rejected alias fails the whole batch. It flips the global `_bundle_extras_ok` for the rest of the run, which also drops Interrupts, Dispels and CombatantInfo (`223`, `655-658`).
     - `BUNDLE_BATCH = 5` exists because the tables are bulky (`210`).
     - Events aliases in the bundle have no pagination.
2. *A separate batched per-fight entry*, like `get_consumable_casts` (`812-852`) or `get_first_death_casts` (`890-937`).
   - Build aliased parts per fight inside one `query X($code: String!) { reportData { report(code: $code) { ... } } }`.
   - Cache with `get_entry(key, refresh=needs_refresh(f))` / `put_entry` using an explicit `name:vN:<code>:<fid>[:params]` key.
   - Batch with `CASTS_BATCH`, fan out with `pool.map`, and call `count_api_call(1, refreshed)`.
   - On `WCLError`, `_warn_once` with a new flag (`217-231`) and return `{}`. Nothing is cached, so the next run retries.
   - Call it from the per-report block in `collect()` after the bundles (`1333-1354`).
   - A report-level query instead goes through `cq()` (`510-512`) and is refreshed when the report changes.
   - Worker-thread `cq()` calls must pass `refresh` explicitly (section 2).

**(b) A new per-player structure in the pull dict**
- Assemble it in the per-fight loop `collect_data.py:1357-1407`. In scope there: `bundle`, `events` (raw damage-taken dicts), `parses`, `deaths`, `participants`, `actors` (`{id: {name, class, server}}`, `521-524`), `lab`, `ability_names`, `npc_names`, `fight`, `report`, `casts`, `cons_casts`.
- Key the structure by `lab.actor_label(actors[id])` and filter `name in participants`, as every existing structure does (`729`, `763`, `782-783`, `871`).
- Pulls are sorted and `progression_only`-trimmed afterwards (`1422-1428`). `all_pulls()` shallow-copies the dicts (`dash/common.py:356-364`).
- The offline test asserts a list of required keys only (`tests/test_collect_offline.py:9-11`), so adding keys is safe.

**(c) A new field in the boss payload, read in `dash.js`**
- Add a per-pull key in `pull_payload` (`dash/payload.py:135-151`) or a boss-level key (`154-160`).
- In the browser the payload is `PD[tab].data` (inflated at `dash.js:319-325`, which also derives `avoidSet`, `ignoreSet` and `nights`). `D.pulls` is filtered to the selection `S` in `renderSelection` (`783-784`), and every section gets `(D, S, n, …)`.
- The Players tab's dynamic view iterates every `PD[tab]` (`963`, `978`), so cross-boss per-player aggregation needs no extra transport.
- Gotchas:
  - Keys are short by convention, and `dt` rows have their trailing `None`s popped (`payload.py:129-130`), so JS must tolerate missing trailing elements.
  - `test_payload_roundtrip_compressed_and_plain` (`tests/test_dashboard.py:35-55`) asserts the key list.
  - Never leave `undefined` keys in Plotly objects (the `CLAUDE.md` caveat; `dash.js:226`).
  - Boss tabs name every player. Only Home is anonymised.

**(d) A new section in a boss tab**
- Write `secX(D, S, n, …, tab)` returning HTML that starts with `<h2 id='sec_${tab}_<key>'>` (the pattern at `443`, `500`, `505`, `542`, `620`, `676`, `694`).
- Append it to `body` in `renderSelection` (`805-813`) and add `['<key>', 'Label']` to `secs_` (`801`). The section nav lists only sections whose id occurs in `body` (`814-815`).
- The deep link `#tabN:<key>` then works with no extra code: `sec_${wanted}_${wantedSec}` (`994-1000`).
- After `panel.innerHTML`: `drawProgression` hook (`818-821`), custom listeners such as the phase buttons (`823`), `.me` row highlight via `data-player` (`825`), `wireSort` / `wireToggles` (`826`), `drawCharts()` for queued `chart()`s (`827`), and `plotly_click` -> pull mapping for x axes titled "Pull #" (`828-840`).
- Constraints: headings `h2`/`h3` only (`tests/test_dashboard.py:600-604`); no hex colours (`531-538`); new pure helpers go inside the quickjs marker blocks to be unit-testable (`dash.js:49-64`, `76-139`; loaders `tests/test_dashboard.py:125-135`, `261-269`).
- The player focus block (`playerFocus` `708-766`) is inserted before the KPI tiles when a player is filtered (`803`).
- Existing section keys: `prog, sum, dd, hd, deaths, dt, prep, util`.

**(e) A new top-level tab**
- In `build_html` (`dash/page.py:73-212`): `_tab_button(tab_id, label_html, extra_class='', active=False, attrs='')` (`58-62`) + `_tab_panel(tab_id, body, active=False, busy=False)` (`64-69`), concatenated in display order. The current order is Home `78-79`, bosses `81-91`, Raid `99-112`, Players `113-115`, Mythic+ `149-152`.
- ARIA roles, `aria-controls` and roving `tabindex` come from those helpers. JS picks up any `.tab-btn`:
  - `activateTab` (`dash.js:257-266`)
  - arrow, Home and End keys (`268-275`)
  - mobile `<select>`: buttons without `data-diff` go under "Overview" (`278-288`)
  - hash deep link (`993-1001`)
- Gotchas:
  - Ids matching `/^tab\d+$/` are treated as boss tabs (`dash.js:893`). `bossTabs` comes from the `tab_names` JSON, which lists only boss tabs (`page.py:132`, `148`; `dash.js:232-233`). Do not name a new tab `tabN`.
  - A JS-rendered tab needs a dirty flag and a branch in `renderIfDirty` (`899-903`), like `tabPlayers` / `playersDirty` (`235`, `891`, `911`, `953-990`), to follow the global filters.
  - In-page links use `gotab(tab_id, text, cls='linklike')` (`dash/common.py:253-254`) + the delegated click handler (`dash.js:929-935`).
  - Heading-level test: `tests/test_dashboard.py:607`.

**(f) A new Home insight**
- Append a tuple `(severity 'good'|'warn'|'info', title_html, text_html, tab_id|None)` inside `insights()` (`dash/home.py:107-292`).
- `home_section` renders it (`369-374`) as `article.insight` with an `h4`, a badge (`SEVERITY_LABEL` `14`) and a `gotab` "Open X ->" jump.
- Gating:
  - `named = mode == "named"`, `people = mode != "off"` (`117-118`).
  - In the default anonymous mode no names may appear (`tests/test_dashboard.py:360`). Title and text are raw HTML, so `esc()` any names (test at `404`).
  - `insights()` runs once per night type with bosses already filtered (`home_tab` `416-420`).
- It sees the full pull dicts (not the payload), plus `NIGHT_FIGHTS`, `NIGHT_PLAYERS` and `MPLUS_FILE`.
- The prog-boss block (`124-212`) shows the idiom: `player_stats`, `regulars`, `player_roles`, and a median-based outlier threshold.

**(g) Test fixtures**

Recording (`tests/make_fixtures.py`):
- `main` (`27-43`) points `cache.CACHE_DIR` and `collect_data.META_FILE` at `tests/fixtures/cache`.
- It runs the **real** `collect()` for `DEFAULT_CODE = "3w1jJ8BZ2m9kMrYG"` (4-pull Normal night, `24`) over all difficulties, and writes `report.json`.
- Then `slim()` (`55-80`) runs: damage events are cut to `_EVENT_KEEP` (`51-52`), table rows lose `_TABLE_DROP` (`49`), and cinfo is cut to `_CINFO_KEEP` (`50`). `--slim` re-slims only (`84-85`).
- Recording needs network + `.env`.

Replay (`tests/conftest.py:37-55`, fixture `offline`):
- Points `cache.CACHE_DIR` at the fixtures and `META_FILE` at a tmp file.
- Replaces `run_query` in `cache`, `collect_data` and `wcl_client` with `_no_network`, which raises `AssertionError` (`23-25`).
- Stubs the report list with the fixture report and redirects `NIGHTS_FILE`. Sets `RAID_TIMEZONE` and `MAIN_RAID_DAYS`.
- The `bosses` fixture (`58-62`) runs `collect()`.

A new query stays offline **only if its exact cache file exists** in `tests/fixtures/cache`, i.e. the sha1 of the query text + vars, or of the entry key.

Gotchas:
1. Any change to the query text (`cached_query`) or to an entry key (version tag or params hash) needs re-recording.
2. Some keys depend on config or env that the tests do not pin: the cons hash depends on `config/consumables.json`, and the casts1 key on `DEATH_WINDOW_SECONDS`, which comes from `.env` via `load_dotenv()` at `wcl_client.py:18`.
3. `_no_network` raises `AssertionError`, which the `except WCLError` fallbacks do not catch, so a missing fixture fails loudly instead of degrading.
4. `slim()` knows only damage-taken pages and bundles (`63-80`). A new bulky entry shape is stored unslimmed (fixtures today: 4.3 MB, 23 files).
5. Slimmed fixtures lack `gear`, `talents`, the per-player `abilities`, `targets` and the cinfo stats/talents. Any feature reading those needs `slim()` updated and the fixtures re-recorded.

Pure-function tests with synthetic data live in `tests/test_units.py` (e.g. `test_consumable_categories_and_use` `100`, `test_counts_from_table_walks_wcl_details_level` `88`).

---

## 9. Existing helpers to reuse (one line each)

**Python, `dash/common.py`**
- `table(headers: list[(label, 'num'|'str'|'none')], rows_html: str|list[str], extra_class='', caption='', limit=None) -> str` (`200-229`): `.scroller` + visible caption + sortable `<th><button>` + "Show all N".
- `kpis(items: list[(label, value[, tile_class])], extra_class='', raw=False) -> str` (`232-240`): `dl.kpis` tiles.
- `player_cell(name, cls, role='', spec='') -> str` (`265-272`): class-coloured name, role tag, spec line. `class_label(cls)` is at `260-262`.
- `fig_html(fig, height=380, div_id=None, fallback=None) -> str` (`290-316`): Plotly in `figure.chart`, title moved to `<h3>`, tokens applied. With `fallback`, `should_skip_chart(fig)` (`275-287`: all bars with < 2 non-zero categories, or every other trace < 4 points) turns the chart into a sentence.
- `hp_band(pct, kill=False) -> 'kill'|'near'|'mid'|'far'` (`68-73`).
- `empty_state(what, why, action='') -> str` (`247-250`).
- `section_note(text_html) -> str` (`243-244`).
- `gotab(tab_id, text, cls='linklike') -> str` (`253-254`).
- Formatting:
  - `esc` (`48-49`)
  - `fmt_duration` (`52-54`), `fmt_num` (`57-61`)
  - `median` (`76-78`)
  - `parse_class(pct)` (`81-88`)
  - `json_for_script` (`91-93`)
- Roles:
  - `spec_role(spec)` (`139-144`), `pull_specs(p)` (`147-156`)
  - `player_roles(pulls)` (`159-165`), `player_role_labels(pulls)` (`168-180`)
- Pull aggregates:
  - `player_stats(pulls, avoidable=None)` (`384-404`)
  - `regulars(pulls)` (`378-381`, players in >= 50 % of the top count)
  - `all_pulls(bosses)` (`356-364`), `filter_bosses_by_type` (`367-375`)
  - `night_stats` (`407-420`), `boss_status` (`423-436`), `detect_breaks` (`330-353`)
- Avoidable config: `load_avoidable()` / `avoidable_set()` / `ignore_set()` (`100-128`).
- Tokens:
  - `load_tokens() -> {name: value}` from `dash/static/tokens.css`; it raises if any `REQUIRED_TOKENS` are missing (`17-33`)
  - `TOKENS` (`36`), `SERIES` (`38`), `LINE_DASHES` / `MARKERS` (`40-41`)
  - `PLOTLY_CDN` (`35`)

**JS, `dash/static/dash.js`, inside the IIFE**
- `tbl(heads, rows, extra, caption, limit)` (`56-60`): twin of `table()`. Also `th` (`53`) and `lowRow` (`55`).
- `kpisHtml(items: [[label, valueHtml, cls?]], extra)` (`65`): values are raw HTML, labels escaped.
- `playerCell(name, cl, role, spec)` (`48`), `clsLabel` (`51`).
- `chart(traces, layout, height, title, fallback)` (`206-216`): returns `figure.chart` and queues the draw. `drawCharts()` is at `217-225`.
  - Pure helpers: `shouldSkipChart(traces)` (`126-130`), `chartLayout(base, layout, h)` (`79-87`), `narrowLegend(lay)` (`90-93`), `boxLayout(n)` (`138`), `topByMedian(entries, n)` (`132-135`).
  - Trace builders: `barTrace(pairs, colors)`, `headroom(pairs, title)`, `heatTrace(z, x, y, unit)` (`227-229`).
  - Series styling: `lineStyle(i)` / `symbolOf(i)` (`69-70`).
- `hpBand(pct, kill)` (`111`), `BAND_COLOR` (`112`).
- `emptyHtml(what, why, action)` (`63`).
- Cell helpers: `prepCell(have, pulls)` (`115-118`), `avoidCell(isA, review)` (`120`), `defCell(d)` (`415-421`), `recapHtml(d)` (`423-430`), `bar(share, heal)` (`61`).
- Formatting: `escH` (`52`), `fmtN` (`36`), `fmtD` (`37`), `median` (`40`), `topN` (`41`), `parseCls` (`43`), `pct` (`39`), `norm` (`35`).
- Roles: `roleOf` (`46`), `rolesOf(S)` / `roleLabel(S, name)` (`405-412`).
- Phases and breaks: `phaseOrder(S)` / `phaseAt(p, s)` (`413-414`), `detectBreaks(S, thr, busy)` (`393-404`).
- `TOK` (`28-32`): resolved token strings (`ink, inkDim, border, borderStrong, borderControl, surfaceCard, surfaceRaised, accent, good, warn, bad, series[6]`).
- State:
  - `G = {night, player, ntype}` (`866`)
  - `PD[tab] = {data, sel:Set, player, dirty, rendered, phase}` (`234`, `325`)
  - `filteredPulls(tab)` (`914-919`)

**Design tokens and the colour rule**
- `dash/static/tokens.css:1-54` is the only place hex values live: surfaces, ink, accent `#c9a227`, `good/warn/bad`, `series-1..6`, type scale `--fs-micro..xl`, spacing `--sp-1..6`, `--radius`, `--ring`, fonts.
- No-hex tests:
  - `tests/test_dashboard.py:531-538` checks `dash.js` and `home.py`, `raid.py`, `players.py`, `mplus_tab.py`, `payload.py`, `page.py`. `common.py` is **not** in the list, and a new `dash/*.py` module would have to be added to it.
  - `page.py` is checked again at `188-189`.
  - CSS hex is allowed only in class and parse colours (`592-597`).
  - `test_tokens.py` checks the required keys, contrast and the 12 px floor.

---

## 10. Rough numbers

**Newest dashboard** (`dashboard_2026-08-19_to_2026-09-21.html`, measured):
- **16 boss tabs**: 8 Normal + 8 Heroic, no Mythic.
- **221 pulls**: 47 Normal, 174 Heroic, 57 kills. Largest tabs: Ula'tek Heroic 49 pulls, Sszorak Heroic 40.
- **15 reports, 14 raid nights, 66 distinct players**. 5,121 player-pulls, 23.2 participants per pull on average.
- Role split of player-pulls: dps 3,657, healer 937, tank 434, no spec 93. 32 distinct spec names.
- Per pull on average: 229 damage-taken rows (player × ability), 17.8 deaths, 22.5 dd rows, 23.0 hd rows, 249 s duration. 15.3 h of boss combat in total.
- File 1.85 MB; payload 1.29 MB base64. About 5.9 KB base64 per pull, about 253 B per player-pull.

**Cache** (`data/cache`):
- 18 reports in `report_meta.json` (15 are in the newest build), 244 boss fights.
- Current-version entries: 221 v3 bundles, 337 damage-taken pages for 239 fights, 71 rankings, and 210 casts1 v2 entries. There are also 445 files of `{data}` shape (consumable casts, possibly with leftover casts1 v1 entries).
- 1,003 MB total, about 632 MB of it current-version.
- Per fight on disk: about 573 KB bundle (about 186 KB of it CombatantInfo) + 2.11 MB damage-taken events.

**Size per build** (from the file names in `dashboards/`):
- 2026-09-01..09-21: 1.26 MB
- 2026-08-23..09-21: 1.72 MB, an older build
- 2026-08-19..09-21: 1.85 MB

That is about 1.7-1.85 MB per month, in line with `CLAUDE.md` §1.
