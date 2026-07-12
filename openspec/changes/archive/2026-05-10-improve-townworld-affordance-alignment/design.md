## Context

TownWorld already keeps semantic locations, objects, affordances, action logs, and schedule inference in the world layer. The scaled real-LLM run showed that this contract is too brittle: common resident intents map to missing affordances, `Rest` fails against `rest`, failed interactions do not suggest executable alternatives, and schedule completion inference misses successful semantically equivalent actions.

## Goals / Non-Goals

**Goals:**
- Keep all business vocabulary and affordance search inside `src/annie/town/`.
- Make supported actions discoverable through context and a read-only town tool.
- Improve affordance matching without turning `interact_with` into a free-form success path.
- Make schedule completion inference traceable and deterministic.
- Add diagnostics that identify remaining affordance alignment failures.

**Non-Goals:**
- No NPC agent-layer changes.
- No inventory or pastry quantity simulation.
- No migration of legacy `web/` or deleted demo paths.
- No requirement for live LLM tests in normal verification.

## Decisions

- Affordance ids and aliases are matched with normalized lowercase strings. This preserves explicit affordances while removing accidental casing failures.
- Unsupported `interact_with` remains a failure when an object has affordances and the intent does not match. The failure facts include `available_affordances` and ranked `suggested_affordances` so the next action can inspect or execute a valid affordance.
- `find_affordance_targets(query, location_id?)` is a read-only tool backed by the town graph. It returns locations and objects whose ids, names, descriptions, affordance ids, labels, aliases, descriptions, or event types match query tokens, plus travel hints from the resident's current location.
- `ScheduleSegment.completion_tags` is optional and backward-compatible. Existing YAML and snapshots omit it; new scaled content can add tags where intent text is too broad.
- Completion inference compares action evidence against segment intent and completion tags, including affordance id, label, aliases, event type, target id, object id, note, and wait/rest evidence at lifecycle locations.
- Runtime diagnostics aggregate from existing action logs and loop guard events rather than adding a second event stream.

## Risks / Trade-offs

- Broader token matching could infer completion too eagerly. Mitigation: require same schedule location except movement segments and lifecycle rest/sleep evidence.
- Query results could be noisy in a 25-resident town. Mitigation: cap results and score by exact phrase, token overlap, current/reachable location, and object affordance detail.
- Scenario YAML can become harder to maintain with repeated home table affordances. Mitigation: keep additions compact and validated through loader tests.
