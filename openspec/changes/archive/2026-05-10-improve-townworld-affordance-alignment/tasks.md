## 1. Spec And Scenario Alignment

- [x] 1.1 Add OpenSpec artifacts for affordance alignment requirements and diagnostics.
- [x] 1.2 Extend scaled town affordances and aliases for delivery, market, home table, rest, and high-frequency objects.
- [x] 1.3 Add optional schedule completion tags to the town data model, loader, and persistence.

## 2. Town Tooling And Matching

- [x] 2.1 Make `use_affordance` affordance id and alias matching case-insensitive.
- [x] 2.2 Add unsupported interaction suggestions with no event writes on failure.
- [x] 2.3 Add read-only `find_affordance_targets(query, location_id?)` tool and context guidance.

## 3. Completion And Diagnostics

- [x] 3.1 Broaden inferred schedule completion from affordance ids, aliases, event types, notes, target ids, completion tags, wait, and rest evidence.
- [x] 3.2 Add short inserted conversation/event segment completion inference.
- [x] 3.3 Extend scaled diagnostics with failed targets, failed intents, suggestion misses, and rest/lifecycle failures.

## 4. Verification

- [x] 4.1 Add focused unit/scenario tests for case-insensitive rest, suggestions, target search, scaled aliases, and deterministic schedule completions.
- [x] 4.2 Run focused town tests and relevant lint/type checks as far as local environment permits.
