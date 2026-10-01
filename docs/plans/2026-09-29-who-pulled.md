# Plan: "Who pulled" tracker (2026-09-29)

**Request (user, 2026-09-29):** "I want to see who and how many times someone pulls first on every boss and in total."

**Reading:** per pull, identify the player whose action started the encounter ("the puller"); count per boss and
across all bosses; show it in the dashboard. Nothing else changes.

## 1. Definition

The puller of a fight is the source (pet → owner) of the earliest friendly action on a hostile target at the start
of the fight: the earliest `damage` **or** `cast` event (not `begincast`) whose target is an NPC, with timestamp in
`[fight.startTime - PULL_TOLERANCE_MS, fight.startTime + PULL_WINDOW_MS]` (proposed 1 000 / 5 000 ms; the
collector task may tune these after looking at real events and must report what it chose and why). No qualifying
event → `None` ("unknown"). Casts on friendly targets (shields, misdirection) never count. `[CAVEAT]` a body pull
(nobody acts, the boss aggroes) is attributed to the first friendly who then hits it; document, do not solve.

## 2. Data contract (fixed - both implementation tasks rely on it)

Pull dict (collect_data.py), new key on **every** pull:

```
"pulled_by": {"player": <label>, "class": <class>, "ability": <name>, "offset_ms": <int, relative to fight start>,
              "kind": "damage" | "cast", "via_pet": <bool>}   # or None when unknown
```

Payload (dash/payload.py), per pull: `"pb": [label, ability, offset_ms, kind]` or `null`
(`kind` = `"d"` / `"c"`).

Fetch: one new per-fight event fetch, batched 10 fights per request via GraphQL aliases (template:
`get_consumable_casts()`), two aliases per fight (`DamageDone` + `Casts`, `hostilityType: Friendlies`, limited window,
`limit` generous), cached per fight under `entry:puller:v1:<code>:<fid>`, refreshed through `needs_refresh(f)` like the
other per-fight entries, `count_api_call()` per request, `_warn_once` + degrade to unknown on `WCLError`. Never
uncached, never per-report.

## 3. Tasks

| # | Task | Model | Files | Depends on |
|---|---|---|---|---|
| A | Detection + fetch + cache in the collector; fixture regeneration; collector tests | fable | `collect_data.py`, `tests/make_fixtures.py` (only if `_EVENT_KEEP` needs new fields), `tests/fixtures/**`, `tests/test_units.py`, `tests/test_collect_offline.py` | - |
| B | Payload + boss tab (Summary "Who pulled" table, "Pulled by" column in the pull table, grid tooltip) + Players tab matrix (players × bosses + Total, filter-aware) + dashboard/JS tests | opus | `dash/payload.py`, `dash/static/dash.js`, `dash/static/dash.css` (if needed), `tests/test_dashboard.py` | - (contract only) |
| C | Docs: `docs/CHANGES_2026-09-29.md`, CLAUDE.md §5 / §7 / §12 | opus | docs, CLAUDE.md | A, B |
| D | Verification: pytest, quickjs syntax check, real build, headless-Firefox screenshots of a boss tab Summary and the Players tab; raw output in the report | opus | none (read-only) | A, B |

## 4. Acceptance criteria

- A: pure function `pull_initiator(...)` with unit tests (pet → owner, `begincast` ignored, friendly-target cast ignored,
  window edges, empty → None); offline replay test asserts `pulled_by` on every pull and a known non-None puller in the
  fixture; `python tests/make_fixtures.py` re-run so the fixtures contain the new entries; the fixture cache stays small
  (extend `slim()`'s `_EVENT_KEEP` only with fields the detection reads); console line per report unchanged in shape.
- B: boss tab Summary gets a `tbl()` "Who pulled" (Player | Pulls | Share | Most used opener; an "Unknown" row when pulls
  lack data) that follows the pull selection and the global filters like every other section; the pull table gets a
  "Pulled by" column (player, ability, offset in s); the Python `pull_grid()` tooltip mentions the puller; the Players
  tab dynamic view gets a "Who pulls first" matrix (rows players sorted by Total desc, one column per boss tab in tab
  order, Total column; honours Nights / Raid night / Player filters exactly as the other Players-tab tables do).
  Pure helpers (`pullerRows(pulls)`, `pullerMatrix(...)`) live inside the quickjs-testable marker blocks with tests.
  No hex colours, no `undefined` keys in Plotly objects (no new charts expected), tables via `tbl()`, headings h2/h3 only.
- C: every change tagged; CLAUDE.md pull-dict field list, payload field list, boss-tab sections, Players tab, timeline.
- D: raw `pytest -q` output (all green), quickjs check output, build console output (API call line), screenshot paths.

## 5. Out of scope (deliberately)

Home callouts, Raid tab, per-player analysis design (separate, pending approval), body-pull heuristics, Plotly charts.
