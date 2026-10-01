> Review of `docs/plans/2026-09-25-player-analysis-design.md`, 2026-09-25, by a Fable 5.1 review agent.
> All 45 findings applied in the same session (line numbers below refer to the pre-revision document) — see `docs/CHANGES_2026-09-25.md`.

# Design review — `docs/plans/2026-09-25-player-analysis-design.md` (959 lines)

Reviewer: Fable 5.1, read-only, 2026-09-25. Evidence base: `docs/research/2026-09-25-player-analysis/00–05` and `CLAUDE.md` only.
Line numbers are those of the design document unless a research file is named.

## 1. Verdict

**Approve with fixes.** The architecture (mine the cache → casts pipeline + spell oracle → optional SimC), the ten decisions, the
tone/anonymity rules and the evidence discipline (`[unverified]` marks, Phase 0 probe) are sound and traceable to the research; the
user can decide D1–D10 on this document. It should **not** be read as a budget or handed to implementation sub-agents as-is:
the per-phase effort totals in §0/§8 understate the sum of their own task efforts by roughly 1.5–2.5× (Blocker), six catalogued
features have no roadmap task, the Phase 1 payload contract exists in two different versions, the "possible casts" formula is wrong
for charged spells, and several load-bearing definitions (severity tolerance, tracked-spell scope, short-pull handling, the `buffs`
string being absent on 14 % of events, deaths after a wipe call) are missing or ambiguous. All of these are editor-fixable; none
changes the recommendation.

## 2. Findings (most severe first)

### BLOCKER

**F1 — Phase effort totals contradict the task tables.**
§0 lines 46–50 and §8 headers (716, 740, 766, 796, 819) give Phase 0 = 4, Phase 1 = 12–16, Phase 2 = 14–20, Phase 3 = 12–16,
Phase 4 = 8–12 sub-agent-days. Using the document's own scale (line 14: S ≤ 1, M 2–4, L 5–10) the task rows sum to:
Phase 0 (10 tasks: 8×S, 1×M, 1×S/M) ≈ **7–14** (6–12 without the optional P0.8/P0.9); Phase 1 (M,M,S,S,L,M,S/M,M,S,S,S) ≈ **16–35**;
Phase 2 (M,M,M,M,L,M/L,S/M,L,S,S,S,S,S) ≈ **24–50**; Phase 3 (8×M + S+S) ≈ **17–34**; Phase 4 ≈ 7–14 (consistent).
The user reads §0 first and will approve budgets from it. *Evidence:* lines 14, 722–733, 746–758, 774–788, 803–813.
*Fix (replace the Effort cells in the §0 table and the §8 headers):* "0 Hygiene — 7–12 (6–10 without P0.8/P0.9)"; "1 Mine the cache — 16–30";
"2 Casts + oracle — 24–45"; "3 Role depth + RL — 17–30"; "4 SimC — 7–14"; add under the table: "Totals are the sums of the task
rows using S = 0.5–1, M = 2–4, L = 5–10; the low end assumes no fable re-work." Alternatively downgrade tasks explicitly (e.g. split
P1.5/P2.8, see F26) and recompute.

### MAJOR

**F2 — Two different Phase 1 payload contracts.** §6.10 (lines 521–545, "the Phase 1 contract for P1.1") lists
`act dps hps dth fd alv avh avm dtk dtps prep pot hs ir ds ish ilvl rp bp oh mit am amw gap`; §7.4 line 612 lists
`["act","dps","hps","dth","fd","avh","avm","dtk","prep","pot","hs","ir","ds","ilvl","bp","rp","oh","mit","am","dtps"]` — `alv`, `ish`,
`amw`, `gap` are missing and the order differs. P1.1 (fable) and P1.4 (opus) would implement different vectors; without `alv` the browser
cannot recompute any "per minute alive" figure. *Fix:* in §7.4 replace the literal list with "`pmcols` = the §6.10 columns in the §6.10 order
(single source of truth; P1.4 imports `PM_COLS` from `analysis/player_metrics.py` and the roundtrip test asserts equality)"; recompute the
per-player-pull byte estimate for 24 columns (≈ 80–100 B).

**F3 — Six catalogued features have no roadmap task; §0 promises one of them a phase early.** Phase 3 "Ships" (line 799) lists H5, H11
and D10, but P3.1–P3.8 (lines 805–812) reference only D6 D7 E13 H1 H2 H6 R6 R10 R11 R12 T4. H7 (line 315), H8 (316) and T6 (330) are
Phase 3 in §4 and appear nowhere in §8. §0 line 48 says Phase 2 ships "tracked buff uptimes", but D10 is Phase 3 (line 300) and no task
renders it (P2.3 only collects segments). *Fix:* add rows "P3.9 Healer efficiency: H5 (healing per mana from P2.2 mana series) + H11
(non-healing time from P2.6 GCD union split by Healing-table `abilities[]`) — M — opus"; "P3.10 Tracked-buff views: D10 (buff uptime
vs own history), H8 (externals given, named), T6 (self-healing share + externals received) from `tbuffs` + `heal:v1` — M — opus";
"P3.11 H7 team note (healable-damage deaths) — S — opus", or drop them with a `[DECISION]`. In §0 Phase 2 row delete "tracked buff
uptimes" (or move D10 to Phase 2 and add it to P2.8).

**F4 — "Possible casts" formula is wrong for charges and anchored on the first cast.** D2 (line 292): "possible = `1 + floor((fight −
first_cast)/cd) × charges`". For a 2-charge 30 s spell in a 60 s fight this gives 5; WoWAnalyzer's `rawMaxCasts = fightDuration/cd +
charges − 1` gives 3 (02 §1 line 108). Anchoring on `first_cast` also rewards holding the opener (a later first cast shrinks the
denominator). P2.5 (line 780) says "time-based efficiency = WoWA formula" — two formulas, one wrong. *Fix:* replace the D2 formula with
"possible = `charges + floor((fight_s − t0)/cd_s)` with `t0` = pull start (pre-pull casts inferred from `combatantinfo.auras`, 02 §3
`PrePullCooldowns`), capped at the WoWA `floor(rawMaxCasts) + 1`; efficiency = WoWA time-based `timeUnavailable / fightDuration`; ±1
cast tolerance". Make P2.5's acceptance criteria name both quantities.

**F5 — The `buffs` string is on 86 % of damage events, not "every" one; T1's denominator is undefined for the rest.** Lines 31–32 ("on
every damage-taken event") and 122 vs 04 §2 line 147–149: "present on 20,032 of 23,184 sampled events … looks like a subset of all
auras (inferred)". `am`/`amw` (lines 542–543) and T1 (325) do not say whether an event without `buffs` counts as "no AM" or is excluded.
*Fix:* line 31 → "on ≈ 86 % of damage-taken events"; §6.10 `am` null rule → "events lacking the `buffs` key are excluded from numerator
and denominator; if they exceed 30 % of the tank's hits, `am` is `null` and the card says 'aura data incomplete'"; add the share of
excluded events to P2.11's cross-check.

**F6 — Whole-fight cast volume is presented as measured; it is an extrapolation from a biased sample.** Lines 33 and 48 ("measured ≈
0.7 MB, one page"); 04 §6 line 361 measured only a *rate* (0.72 casts/s/player) in 210 pre-death windows of 6.3 s and warns (line 370)
"the cast rate may be low, because dying players are often moving". The batch size (3 fights/request, line 395), the 1-page assumption,
the cache-growth and request numbers (§6.8) all rest on it. *Fix:* lines 33/48 → "estimated ≈ 0.6–1 MB and 1–2 pages per pull, from a
cast rate measured in pre-death windows (`04` §6; likely a low estimate)"; add to P0.7: "one whole-fight `casts` alias on the longest
cached pull: record events, bytes, pages"; make the batch size "3 (revisit after P0.7)".

**F7 — The public build still ships a ranked roster.** §0 lines 27–28 and D3 promise "never a sorted roster"; §7.7 line 662 keeps "the
existing roster table (neutral counts, no severity colours)", but that table is sorted by first-death rate (01 §5 line 593) — a named
wipe-starter ranking, which is exactly tone rule 1's forbidden surface. *Fix:* line 662 → "the existing roster table **sorted by name
(secondary: pulls)** with neutral counts; the first-death-rate sort is available only in the named build"; add to P1.9's acceptance
criteria "anonymous build: roster table order is alphabetical (test)".

**F8 — Two severity engines re-create the Python/JS drift the project removed.** Line 599 ("`analysis/severity.py`, mirrored in JS for
the card") plus D10 (line 882, static Python rollups) means the Good/Watch/Note logic lives twice. `CLAUDE.md` §7 `[DECISION 2026-09-23]`
went to a single renderer precisely because "the Python and JS versions of every table/chart had drifted". *Fix:* §6.9/§7.3 → "Python
computes per player × night × metric the value, baseline, level and template id into a small `sev` payload block; JS only orders,
filters and renders it (so the card follows the filters by re-selecting nights, not by re-scoring); the named rollups read the same
block." Update D10's recommendation to "yes, and the rollups reuse the precomputed severities".

**F9 — P2.6 fixes the base GCD at 1500 ms although the oracle carries per-spell GCDs.** Line 781: "GCD = `max(min(1500, 750),
1500/(1+haste))`"; §6.4 line 442 emits `gcd_ms` per spell; 03 §4 shows `GCD : 1.5 seconds` per spell. Specs whose core spells have a
1.0 s GCD (Rogue, Windwalker, etc.) get a 50 % over-estimate of active time. Haste rating→% also ignores the diminishing-return
brackets (02 §1 line 145). *Fix:* P2.6 → "per cast: base = oracle `gcd_ms` (0 → off-GCD, no segment); hasted unless the spell's
attributes say otherwise; `gcd = max(750, base/(1+haste))`; haste % from cinfo rating via the oracle scale **with DR brackets from
`item_scaling.inc`**; 1500 only when the oracle lacks the id."

**F10 — Fixture re-recording and Phase 2 back-fill depend on report archive status, which is not probed.** 04 §5 line 350: "Events,
tables, and graphs for archived reports are inaccessible unless … subscription". D7 (line 879) assumes `make_fixtures.py` can re-record
`3w1jJ8BZ2m9kMrYG`; Phase 2 assumes casts can be fetched for every report in the build range. Both fail silently (`_warn_once` + `{}`)
for archived reports; the design mentions archives only for cache backup (line 895). *Fix:* add to P0.7 "query `archiveStatus` for the
fixture report and the oldest report of the current build"; add to Phase 2 risks "casts cannot be back-filled for archived reports — the
card shows 'cooldown data from <first unarchived night>'"; add to D7 "if the fixture report is archived, pick a new one (all fixture
expectations change, +1 S task)".

**F11 — Deaths and hits after a wipe call are counted.** E1/E2/E4 and `dth/fd/avh/avm` (§6.10) use every death; 04 §7 lines 456–457
documents `ReportFight.wipeCalledTime` and `events(wipeCutoff)`; 05 E2 notes Warcraft Insights "excluding wipe-phase deaths". A raider
who dies in the 20 s after "wipe it" is charged a death and avoidable hits. *Fix:* add `wipeCalledTime` to `FIGHTS_QUERY` (query-text
change → fold into P0.8's fixture re-record) and define in §6.10: "`dth`, `avh`, `avm`, `dtk` exclude events after `wipeCalledTime`
when set; `fd` and `alv` are unaffected"; state the rule on the card ("deaths after the wipe call are not counted").

**F12 — The severity engine's core parameters are undefined.** Line 601: "worse than baseline beyond *tolerance*" — no tolerance per
metric anywhere; lines 602–603 order by "severity × pulls affected" and pick "the best Good by margin", but with three levels all Watch
items tie and metrics have incompatible units. The "one thing to work on" (block 2) therefore has no defined selection function.
*Fix:* add a table "metric · tolerance (relative or absolute) · direction · priority tier" (e.g. deaths/pull ±0.15 abs, avoidable/min
±25 % rel, prep any miss, active % ±3 pts abs, DPS/HPS ±8 % rel, cast efficiency −10 pts abs) and define
`score = |value − baseline| / tolerance × pulls_affected / pulls`; tiebreak by tier (deaths > avoidable > defensives > preparation >
active time > throughput > cooldowns); "best Good" = highest score in the good direction.

**F13 — "Tracked spell" is ambiguous in scope and threshold.** E14 (line 284) "≤ 6 longest-cooldown spells actually cast (cd ≥ 45 s)";
D3 (293) "≥ 90 s"; glossary (959) "in the selection" (a browser-side notion) although `cdt` is computed per pull in Python (P2.7). If
chosen per pull the set varies and cross-pull aggregation breaks; if per build it must be said. *Fix:* "Chosen **per player per build**
in Python: spells the player cast in any pull, with oracle `max(cd, category_cd) ≥ 45 s`, ranked by cooldown, top 6, plus every
configured raid CD / defensive the player cast; stable across pulls; D3's integer view applies to those with cd ≥ 90 s."

**F14 — Short pulls and kills-vs-wipes are undefined for throughput and efficiency metrics.** E7, D1, E6, E14, H1 average over
"pulls"; a 30 s wipe has opener-inflated DPS, 100 % active time and a trivial cast-efficiency denominator. Only E8 (kills) and E7
("kills marked") say anything. *Fix:* add to §6.10 preamble: "pulls shorter than 60 s are excluded from `act/dps/hps/oh` medians, from
cast efficiency and from downtime (they still count for deaths, prep and avoidable hits); the card states the number of pulls used."

**F15 — Support specs (Augmentation) in DPS medians.** Line 120 marks `given/taken/totalRDPS*` "out of scope, noted"; the roster has
Augmentation (01 §4: 40 player-pulls). Their D1/E7 will read as a permanent Watch and they depress the DPS role median. *Fix:* spec
table gains a `support` flag; "support specs are excluded from role medians; D1/E7 render for them as a Note ('support spec — WCL's
rDPS is not in the payload')".

**F16 — Phase 4 exit criterion contradicts its degradation rule.** Line 824: binary missing → `empty_state("Sim baselines", …)`;
line 845: "with `simc` absent the built HTML is byte-identical to a Phase 3 build". *Fix:* choose one; recommended: "with `simc`
absent no sim section is rendered (byte-identical apart from the footer); the 'simc not found' hint goes to the console, not the public
HTML".

**F17 — A Phase 1 exit criterion depends on a tool the machine lacks.** Lines 641–645, 757, 842 require `validate_palette.js`
(needs `node`, or a non-headless Firefox session that a sub-agent cannot drive). *Fix:* remove it from the Phase 1 exit criteria; keep
it as a `[TODO]` for the user, or specify "run in headless Firefox from a scratch page that writes `console.table` output into the DOM
and is screenshotted".

**F18 — `tbuffs` cache key churns with the roster.** Line 397/778: the id hash includes "buff ids of tracked cooldowns", which change
whenever a player's tracked-spell set changes → re-download of every `tbuffs` entry. *Fix:* "the `tbuffs` id list = config ids only
(`raid_cooldowns.json`, `tank_mitigation.json`, `defensives.json`); tracked-cooldown buff uptimes (D10) use the casts entry plus oracle
`Duration` instead".

### MINOR

**F19** §0 line 52 "Five decisions" vs ten in §9 (D6–D10 include D7, which gates Phase 1 testing, and D8). *Fix:* "Ten decisions; the
five from the brief first, five new ones (D6–D10) below."
**F20** Decision ids D1–D10 collide with feature ids D1–D10 (lines 350, 400, 799, 865 mix them in one sentence). *Fix:* rename decisions
Q1–Q10 throughout.
**F21** "Four" config files (lines 38, 60, 262) vs six in §6.5 (`gear_checks.json` is Phase 1; `simc.json` Phase 4). *Fix:* "five small
configs in Phases 1–3 (+ `simc.json` in Phase 4)".
**F22** Cache growth: §5 line 368 and Phase 2 line 772 say "≈ 90–120 MB/month compact"; §6.8 sums to ≈ 65 MB. *Fix:* one number.
**F23** D4 budget "≤ +0.5 MB/month" (line 59) vs Phases 1–3 total "+0.55 MB" (line 619). *Fix:* budget "≤ +0.6 MB" or trim `rdt`.
**F24** Phase 0 has no docs task and its exit criteria omit the `CHANGES` entry required by line 713 / `CLAUDE.md` §10. *Fix:* add "P0.D".
**F25** Block 2 uses `article.insight`, which the Python helper renders with an `h4` (01 §8(f) line 744); inside `dash.js` the heading
test allows only h2/h3. *Fix:* "card insight uses the `article.insight` markup with an `h3`".
**F26** P1.5 (L) and P2.8 (L) each bundle 4–6 deliverables (renderer + severity helpers + players.py + page.py + CSS; panel + bullet +
heat strip + efficiency + deaths row + focus block). *Fix:* split P1.5 into "pure helpers + severity (fable, M)" and "renderer (opus,
M/L)"; split P2.8 into DPS panel, healer strip, deaths row, focus-block timelines.
**F27** P0.5 files omit `collect_data.py`, where `specID` must be lifted from `cinfo` into the pull dict. *Fix:* add it.
**F28** New `.env` keys (`SIMC_SRC`, `SIMC_BIN`, `WCL_RATE_WAIT_MAX`) must be added by the user (`CLAUDE.md` §3 caveat). *Fix:* one
sentence in §6.2/§6.4/Phase 4 + `.env.example` note.
**F29** T3 (line 327) `(unmitigatedAmount − amount) ÷ unmitigatedAmount` counts overkill as mitigation (04 §2: `amount` excludes overkill).
*Fix:* "`(mitigated + absorbed) ÷ unmitigatedAmount`, or subtract `overkill`".
**F30** E9/R7 assume the Interrupts table lists enemy spells that were never interrupted and that `spellsBegun` = interruptible casts;
the research shows the shape only (01 §1.2, 04 §3). *Fix:* mark `[unverified]` and add to P0.7.
**F31** Mock (§7.9): header "2 nights" (679) vs "vs your 2 earlier nights" (688); "3 of 27 player-pulls per person" (682) is muddled;
"2nd potion 12 of 18 kills/long pulls" (699) — "long" undefined (potion shared cooldown 5 min, 02 §2 line 200). *Fix:* "3 nights";
"raid median 3 of 27 pulls"; "pulls ≥ 5 min".
**F32** E10 is Phase "1 → 2" in §4 (line 280) but absent from Phase 1 Ships (743). *Fix:* add "E10 (first death)".
**F33** P0.4 wait/stop sleeps up to 900 s on any 429, but 04 §5 (S22) shows burst 429s while points remain. *Fix:* "keep the existing
short backoff first; escalate to the `pointsResetIn` wait only when `pointsSpentThisHour ≥ 0.95 × limitPerHour`".
**F34** Oracle id set (line 441) is derived from cached casts that do not exist before P2.1 runs (slot 7 runs P2.1 and P2.4 in
parallel). *Fix:* "build warns 'N cast ids missing from the oracle — rerun tools/build_spell_oracle.py' and treats them as untracked".
**F35** 12-point sparklines (line 591) with < 4 nights violate the chart fallback rule (`CLAUDE.md` §7). *Fix:* "sparkline omitted
below 4 nights; the delta text stays".
**F36** Phase 2 `pm` column named `dt` (line 545) collides with the payload's damage-taken key `dt`. *Fix:* `dtm`.
**F37** "Own history (≥ 2 nights)" (600) — earlier nights or total? And what is "this night" when the user filters a past night?
*Fix:* "baseline = median over the player's nights **before the latest selected night**; needs ≥ 2 such nights; 'this night' = the
latest night in the selection".
**F38** Role median (600, 957) — per pull or per player, subject excluded?, regulars only?, tanks (n = 2) never reach ≥ 3. *Fix:*
"median over the other players of the role in the same pull, then median over pulls; needs ≥ 3 others (tanks → co-tank baseline);
players with < 25 % of the pulls excluded".
**F39** §3.4 drops the research's "not legal advice" caveats (02 §5, 03 §1). *Fix:* add the phrase.
**F40** specID 66 example (line 427) is not in the research (only 62, 253, 262, 577 verified in the cache). *Fix:* mark or use 577/62 only.
**F41** "casts are the cheapest event type WCL has" (377) — 04 §6 ranks filtered/table queries cheaper; casts are "moderate".
*Fix:* "the cheapest **whole-fight** event type".
**F42** Deep link `#tabPlayers?player=<label>` (580) must coexist with the `#tabN:section` parser (`dash.js:993-1001`) and URL-encode
labels containing apostrophes or `Name-Realm`. *Fix:* one sentence in P1.7.
**F43** Multi-spec players: headline spec (589) and role section for a player who swapped specs across nights are undefined. *Fix:*
"headline = spec with most pulls in the selection; role section per role played, as the focus block does today".
**F44** Ordering: the user re-records fixtures in slot 2 and again after P0.8 in slot 3 (and after F11's `wipeCalledTime`). *Fix:*
decide P0.8 before the first re-record (P0.7 → P0.8 → re-record) so Phase 0 needs one recording.
**F45** `tbuffs` size "1–5 KB" (397) is low for AM auras that re-apply every few seconds on two tanks; harmless but state "≤ 30 KB".

## 3. Evidence spot-check (30 claims)

| # | Claim (design) | Line | Research source | Verdict |
|---|---|---|---|---|
| 1 | Buffs `targetID` leak = 19 % of cached events | 46, 484 | 04 §1 (1,451 / 7,683 = 18.9 %, cache) | Supported |
| 2 | `buffs` string on **every** damage-taken event | 31–32 | 04 §2: 20,032 of 23,184 (86 %), "subset (inferred)" | **Overstated** (F5) |
| 3 | Casts ≈ 0.7 MB, one page per pull, "measured" | 33, 48 | 04 §6: rate measured in 6.3 s pre-death windows; size extrapolated; "may be low" | **Overstated** (F6) |
| 4 | WCL schema has no cooldown/GCD/charges/cast time | 132 | 04 §7 (verified S9/S10) | Supported |
| 5 | 1.85 MB / 1.29 MB b64 / 69.9 % / 5.9 KB per pull / 253 B per player-pull / 8.1 MB headroom | 136–137 | 01 §4 | Supported |
| 6 | 962 MB cache, 632 MB current, 573 KB + 2.11 MB per fight, ~34 requests per new 15-pull report | 138 | 01 §2–3 | Supported |
| 7 | 93 of 5,121 player-pulls without spec | 110 | 01 §5 | Supported |
| 8 | WCL `talentTree[].id` = SimC TalentID, 7 pairs | 111, 198 | 03 §2 (1 + 6 sampled pairs) | Supported |
| 9 | `killingBlow` in 81 % of Deaths rows | 121 | 01 §1.2 (6,415 / 7,943) | Supported |
| 10 | hitType 0/1/2/4/5/7/8/10 mapping | 123 | 04 §2 (WoWA HIT_TYPES) | Supported |
| 11 | Interrupts table `spellsBegun/Completed/Interrupted` = interruptible-cast denominator | 124, 279 | 01 §1.2 / 04 §3 give the shape only | Shape supported; **semantics unverified** (F30) |
| 12 | Rankings carry `bracketPercent`, `spec`, `speed`, `execution` | 125 | 01 §1.2, 04 §4 (cache) | Supported |
| 13 | WoWA MaintainedFull 17/40, 14 at 12.1; Havoc ~60 modules | 154 | 02 §6 | Supported (module count is 02's inference) |
| 14 | Downtime 5/10/15 %, small gaps 6/8/10 per min | 161 | 02 §1 | Supported |
| 15 | Cast efficiency 0.80 / −0.05 / −0.15, time-based, suppressed at max casts | 163 | 02 §1 | Supported |
| 16 | Cancelled 2/5/15; mana 10/20/30; melee .98/.90/.80; debuff .85/.80/.75; AoE .95/.90/.80 | 164–168 | 02 §2 | Supported |
| 17 | GCD `max(min(base,750), base/(1+haste))`, hidden at ≥ 2 errors/min | 171 | 02 §1 | Supported (but F9: base must be per spell) |
| 18 | Havoc 15/25/35 vs shared 5/10/15 branch discrepancy | 173–175 | 05 E6 vs 02 §1 | Supported; reconciliation sensible |
| 19 | `fake: true` on 98 of 863 cached casts | 181 | 04 §2 | Supported |
| 20 | `classResources.amount` stale within 150 ms | 186 | 02 §3 item 6 | Supported |
| 21 | SpellDataDump 13 files ≈ 17.8 MB; labels Cooldown/Charges/Category/GCD/Cast Time/Attributes/Category Flags/Replaces | 197 | 03 §4 | Supported |
| 22 | SimC has healer APL only for Resto Druid | 199, 898 | 03 §5 | Supported |
| 23 | 88–98 % / 65–75 % sim-vs-real | 200 | 03 §6a (65–75 marked inferred) | Supported as "community reports" |
| 24 | Casts table omits item uses (potions) | 183 | 04 §3, CLAUDE.md §5 | Supported |
| 25 | Filter-expression `timestamp` is fight-relative | 412 | 04 §1 (S16) | Supported |
| 26 | 3,600 points/h free; cost unpublished; "raid night ≈ 3, character ≈ 6"; wowsims "1 point per subquery" | 419–421 | 04 §5 | Supported |
| 27 | Cached aliased entries far below limits (58 / 18 / 121 / 27) | 409 | 04 §1 | Supported |
| 28 | specIDs 62 Arcane, 577 Havoc, **66 Protection Paladin** | 427 | 04 §2 lists 62, 253, 262, 577 only | 66 **not in research** (F40) |
| 29 | `sc_scale_data.inc` in `engine/dbc/generated/` for rating→% | 440 | 02 §1 cites the filename via WoWA; 03 does not list the path | **Path unverified** |
| 30 | 370 MB orphaned cache files | 492 | 01 §3 (1,003 − 632) | Supported |
| 31 | Deaths table `events[]` ≤ 3 hits; `deathSaveAbility` | 121, 891 | 04 §8 | Supported |
| 32 | Wipes = 74 % of pulls | 880 | 01 §4 (57 kills / 221) | Supported |
| 33 | Docker image 29.3 MB; AUR packages BfA/GUI | 202 | 03 §1 | Supported |
| 34 | `renderPlayersTab` aggregates all payloads (`dash.js:953-990`, `963`); `tabPlayers` outside `/^tab\d+$/` | 558 | 01 §5, §8(e) | Supported |
| 35 | Roster table "neutral counts" | 662 | 01 §5: sorted by first-death rate | **Contradicted** (F7) |

## 4. Checklist summary

- **A Placeholders/vagueness:** no TBD/TODO-without-owner, but "as documented in P2.7" (545) points to a row that documents nothing; "tolerance" (601), "long pulls" (699), "…" in config lists (459), P3.V/P3.D "as before" (813) and P4.5 (832) are hand-waved; the `validate_palette.js` `[TODO]` sits inside an exit criterion (F17).
- **B Internal consistency:** effort totals vs task sums (F1); two payload contracts (F2); six orphaned features and a §0 phase promise (F3); "five" vs ten decisions, "four" vs six configs, D-id collisions, 65 vs 90–120 MB, 0.5 vs 0.55 MB, byte-identical vs empty state (F16, F19–F23); mock arithmetic (F31).
- **C Evidence:** 30 claims checked; 26 supported at the stated confidence; overstated: `buffs` on every event, casts "measured"; unverified/not in research: Interrupts-table semantics, specID 66, `sc_scale_data.inc` path; one contradiction (roster sort). The document's `[unverified]` marks are otherwise faithful to 04's "Not verified" list.
- **D Constraints:** respected on size budget, Home anonymity, boss tabs JS-only, tokens, `table()/tbl()/kpis()/chart()`, cache keys with version tags, report list/meta never cached, `$filter` variable, `nextPageTimestamp`, model on every task, delegated verification with raw output, `CHANGES` per phase (missing for Phase 0, F24). Violations/omissions: ranked public roster (F7), h4 in `article.insight` inside `dash.js` (F25), sparkline vs chart fallback rule (F35), two engines vs single-renderer decision (F8), new `.env` keys (F28).
- **E Feasibility/effort:** Phase 0 is not "4 days" (F1) but is startable; Phase 1 is startable on cached data for production and on synthetic data for tests — the fixture dependency blocks only offline coverage of gear/`buffs`/`abilities`/overheal (correctly stated, but archive risk unprobed, F10). GCD model (F9), cast-efficiency formula (F4), tracked-spell scope (F13) need the fixes above before they are implementable without re-research; the oracle parser and AM-at-hit check are specified adequately once F5 lands. P1.5 and P2.8 are several tasks each (F26).
- **F Ambiguity:** tolerance/score (F12), tracked spells (F13), short pulls & kills vs wipes (F14), own history and "this night" (F37), role median (F38), multi-spec players (F43), `buffs` missing (F5), second-potion rule (F31).
- **G Product judgement:** the audience coverage is balanced and honest (healers thin in Phase 1, stated). Nothing high-value was dropped without a `[DECISION]`. Lower-value/higher-maintenance items kept: E13/R10 talent-diff (n = 1–3 per spec, not actionable), H9 healer-damage note (tone risk on a public card — keep as Note only). Tone design is strong and structural; the ranked roster (F7) and the undefined "one thing" selector (F12) are the two gaps. Support specs (F15) and wipe-call deaths (F11) are fairness gaps.
- **H Risks:** covered — rate limits, hidden parses, Labeller identity, fixture cost, load time, Plotly CDN (implicitly), oracle drift, SimC build. Missed — archive status for fixtures/back-fill (F10), post-wipe deaths (F11), Augmentation (F15), burst 429 (F33), oracle/casts chicken-and-egg (F34), `tbuffs` key churn (F18).

## 5. What is good (do not "fix")

- The evidence discipline: every `file:line` traces to 01, every threshold to 02, every WCL argument to 04; `[unverified]` items are collected into a Phase 0 probe with a decision per item, and the branch discrepancy in WoWA thresholds is caught and reconciled (lines 173–175).
- Phase 1 = zero new API calls is real: `activeTime`, `overheal`, `bracketPercent`, `specID`, gear, `abilities[]`, the `buffs`/`mitigated`/`hitType` fields are all in the cache per 01/04; the Interrupts-table denominator and the `buffs`-string AM check are genuinely clever reuse.
- D1 (oracle over sims, sims opt-in), the rejection of APL comparison and stat weights, and "sim-vs-actual as own trend only" follow 03's ranking exactly and keep healers first-class.
- D4 (precomputed vectors, no raw casts) with the 6–9 MB counter-example and the size guards in P1.4/P2.7.
- The tone architecture (§7.7, §10): structural mitigations (nothing per-name until a name is chosen, own-history-first, Watch cap, no top-log names, RL build never posted) plus the "announce before first post" advice.
- Phase 0's hygiene set is the right first move: the leak fix, pagination, `$filter`, rate-limit wait/stop, spec table and the fixture recorder all unblock later phases and fix latent bugs in today's build.
- The fixture plan keeps tests offline and one code path for compact casts in production and fixtures.
- The glossary and the traceability table to 05's shortlist, with three marked deviations.
