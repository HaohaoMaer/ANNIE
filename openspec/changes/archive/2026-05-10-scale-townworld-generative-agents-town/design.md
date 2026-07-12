## Context

TownWorldEngine currently supports semantic locations, resident state, schedules,
local perception, town tools, conversations, reflections, replay artifacts, and
runtime snapshots. Recent validation has proven the architecture with small
cohorts, but the system has not yet been exercised at the population and social
density associated with Generative Agents-style Smallville runs.

The reference target for this change is scale and behavior shape, not a direct
port of another runtime. ANNIE will keep the current two-layer architecture:
`src/annie/npc/` remains stateless and business-agnostic, while durable town
state, scenario content, memory, schedules, and runtime diagnostics remain in
`src/annie/town/` and `src/annie/world_engine/`.

## Goals / Non-Goals

**Goals:**
- Add a large semantic town scenario with at least 25 residents.
- Cover a district-level town graph with homes, workplaces, public services,
  social venues, outdoor spaces, and event locations.
- Give residents coherent personas, occupations, relationships, memory seeds,
  home/sleep locations, and initial schedules.
- Run deterministic scale validation without live LLM credentials.
- Support opt-in real-LLM scale validation with cost controls and diagnostics.
- Make replay and diagnostics useful for judging whether the larger run behaves
  like town life rather than only checking that it did not crash.

**Non-Goals:**
- No tile renderer, sprite map, or browser game UI in this change.
- No direct dependency on GenerativeAgentsCN data files or runtime classes.
- No change to `NPCAgent` persistence semantics.
- No requirement that all 25 residents use real LLM calls in every local run.

## Decisions

1. **Use ANNIE-native scenario YAML as the source of truth.**

   The scaled town will be authored as a project-owned scenario file under
   `src/annie/town/content/scenarios/`. It may be inspired by the Smallville
   structure of homes, cafe, stores, public places, and socially connected
   residents, but it will use ANNIE fields: locations, exits, objects,
   affordances, residents, personas, relationships, schedules, and memory seeds.

   Alternative considered: import or mirror GenerativeAgentsCN runtime data.
   That would couple ANNIE to another project's object model and weaken the
   NPC/world-engine separation.

2. **Scale first through semantic graph density, not tile density.**

   The first scaled milestone should prove that scheduling, perception,
   conversation, memory, reflection, and replay work with a larger cohort. The
   town graph can later be adapted to tile coordinates once the semantic runtime
   is stable.

   Alternative considered: implement tile visualization first. That would add a
   new representation before the core autonomy risks are measured at scale.

3. **Separate deterministic scale gates from opt-in real-LLM gates.**

   Deterministic tests should load the full scenario, run a representative
   cohort, and assert stable structural/behavioral signals. Real-LLM validation
   should be explicit and configurable because 25 residents across multiple days
   can be expensive and slow.

   Alternative considered: require full 25-resident real-LLM validation as the
   primary gate. That would make routine validation too costly.

4. **Report behavior quality as first-class diagnostics.**

   Scaled runs must report schedule completion, unfinished schedules, action
   failures, loop guards, excessive skips, conversation density, reflection/day
   summary evidence, memory seed coverage, and replay paths. A run can complete
   technically while still producing inspectable behavior-quality warnings.

   Alternative considered: rely only on pass/fail tests. That would hide the
   difference between runtime correctness and believable town behavior.

## Risks / Trade-offs

- **Large scenario authoring can become brittle.** → Keep scenario validation
  strict and add tests for resident count, location coverage, relationships,
  schedules, memory seeds, and route reachability.
- **Real-LLM scale runs can be slow or expensive.** → Provide CLI limits for
  resident subset, days, time window, max ticks, retries, and prompt preview.
- **More residents may create noisy conversation loops.** → Validate cooldowns,
  failed conversation rates, and loop guard output at scale.
- **Semantic locations may feel less like GenerativeAgentsCN than tiles.** →
  Treat this as a deliberate runtime milestone; tile visualization remains a
  later adapter over validated semantic state.
- **Scenario content inspired by another project can blur ownership.** → Use
  ANNIE-original names and descriptions while matching the reference scale,
  social density, and category mix.
