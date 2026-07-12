## ADDED Requirements

### Requirement: Full-day validation reports affordance alignment quality
Full-day and scaled TownWorld diagnostics SHALL summarize affordance alignment failures separately from runner failures.

#### Scenario: Diagnostics list top failed affordance targets
- **WHEN** a scaled town run records failed `use_affordance` or `interact_with` actions
- **THEN** diagnostics include top failed targets and objects by count
- **AND** diagnostics include top failed intents by count

#### Scenario: Diagnostics expose suggestion misses
- **WHEN** unsupported affordance failures include `suggested_affordances`
- **THEN** diagnostics report how many suggested affordance opportunities were still followed by repeated failure or loop guards

#### Scenario: Diagnostics expose rest lifecycle failures
- **WHEN** rest, sleep, wait, or lifecycle settlement produces failures or anomalies
- **THEN** diagnostics include a rest/lifecycle failure summary with affected residents and reasons
