> Research input (2026-09-25) to `docs/plans/2026-09-25-player-analysis-design.md`; copied unchanged from the session scratchpad apart from this header line.

# Design brief — per-player combat analysis (next phase)

Written by the orchestrator on 2026-09-25 from the user's request. Sections marked ASSUMPTION are the
orchestrator's reading, not the user's words; the user will correct them after reading the proposal.

## What the user asked for (their words, condensed)
- "Plan the next phase of upgrades."
- "Tailor the feedback and combat analysis of each player down" — i.e. from raid/boss-level aggregates to
  individual-player feedback.
- Inspirations: SimulationCraft (https://github.com/simulationcraft/simc) and WoWAnalyzer
  (https://github.com/wowanalyzer/wowanalyzer).
- "Consider different possibilities on how to implement them in this dashboard."
- Audiences: raid lead and guild master **and** DPS, healers and tanks.
- Deliverable of this turn: analysis, proposed feature sets matching the intention, and a roadmap.
  No implementation yet.

## Intended outcome (ASSUMPTION)
A raider opens the dashboard after a raid night, selects themselves, and sees a short, honest, specific
picture of how they played: where they lost throughput, whether they used their tools (cooldowns,
defensives, consumables, interrupts/dispels), how they compare to a fair baseline, and what one or two
things to work on. The raid lead sees the same data rolled up: who needs help with what, and whether the
raid as a whole is executing. Success = players say "that matched what I felt in the fight" and the raid
lead spends less time reading WCL by hand.

## Hard constraints (from CLAUDE.md, not negotiable without the user)
- Python 3.14, no Node; Firefox headless for screenshots; Plotly + inline SVG in the browser.
- Data source is the WCL v2 API (client credentials, public reports only). Everything report-specific is
  cached per fight; report list and meta are never cached; live logs must refresh only new fights.
- Single self-contained HTML, shared in the raid Discord (public artefact, < 10 MB, ~1.7 MB/month now).
  Home shows no names. Boss tabs show names.
- Tests stay offline (fixtures recorded once by tests/make_fixtures.py). Any external binary (simc) must be
  optional at build time with graceful degradation and never required by tests.
- Design system: tokens.css is the only place colours live; tables via table()/tbl(); charts via
  chart()/fig_html() with the small-data fallback rule; boss tabs rendered only by dash.js from the payload.
- Every change recorded in docs/CHANGES_<date>.md; CLAUDE.md kept current.
- Delegation policy: implementation will be done by sub-agents from a written plan (superpowers
  writing-plans format), so the roadmap must be decomposable into self-contained tasks.

## Soft constraints / preferences (ASSUMPTION)
- No per-spec maintainer exists. Anything that needs a hand-written per-spec ability list for all ~13
  specs in the roster is a maintenance liability; prefer (1) spec-agnostic analyses, (2) data-derived
  baselines (SimC output, spell-data dump, same-spec comparison, own history), (3) small per-spec configs
  only where the value is very high (e.g. tank active mitigation), in that order.
- The guild is Heroic progression, 2 main nights/week, ~20 raiders. Feedback should help a Heroic raider
  improve, not chase 99th-percentile parses.
- Tone: motivating, never shaming; compare to own history and a fair baseline before ranking against
  guildmates; the public artefact must not become a wall of shame. A "named" private build already exists
  for the RL (HOME_CALLOUTS=named) and can carry the sharper content.
- The user is a Havoc Demon Hunter; a DPS view is the natural first vertical slice, but healers and tanks
  must be first-class in the design, not an afterthought.

## Open questions the proposal should answer explicitly (so the user can decide)
1. How much SimC to use: none / spell-data oracle only / per-player baseline sims / sim-vs-actual.
2. Where the per-player view lives: expand the Players tab, a new "My raid" tab, or the player filter's
   focus block inside boss tabs.
3. Public vs private: which per-player insights go into the Discord build and which only into the
   named RL build.
4. Payload strategy: precomputed per-player metrics in the payload (small) vs raw casts in the payload
   (big, enables client-side timelines).
5. Which per-spec knowledge, if any, we accept maintaining, and in what config format.

## Success criteria for the proposal document
- Feature sets grouped by audience (RL/GM, DPS, healer, tank, everyone), each feature with: what the
  player sees, data needed, spec knowledge needed, cost (API points, cache, payload), effort S/M/L.
- 2-3 architecture options with a recommendation.
- A phased roadmap: each phase ships something visible, phases ordered by value/effort, with explicit
  dependencies, acceptance criteria and risks; the first phase must be startable next session.
- Honest limits: what WCL cannot give, what SimC cannot give, what needs per-spec knowledge.
