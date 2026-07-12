## Why

Recent TownWorld runs exposed behavior that depended too heavily on prompt wording:
multi-hop movement failed at non-direct destinations, NPC-facing dialogue tools were
split across overlapping entry points, empty conversations counted as successful
evidence, schedule completion had multiple implied meanings, and memory recall
arguments from LLMs were too brittle.

## What Changes

- Make `move_to(destination_id)` advance one deterministic shortest-path hop toward
  reachable non-direct destinations.
- Expose one NPC dialogue tool, `talk_to(target_npc_id, topic_or_reason)`, while
  keeping `speak_to` and `start_conversation` as compatible engine APIs.
- Expose `complete_current_schedule(note)` as the NPC schedule completion tool and
  keep `finish_schedule_segment` as a compatible alias.
- Record schedule completion through the `completed_schedule_segments` ledger with
  normalized completion types.
- Reject empty managed conversations without cooldown or schedule-completion evidence.
- Tolerate common `memory_recall` category and `k` argument shapes.

## Impact

- Affected code: `src/annie/town/`, `src/annie/npc/tools/builtin.py`, town tests.
- Public behavior: NPC contexts use `talk_to` and `complete_current_schedule`; old
  engine methods remain callable.
- No changes to NPC/world-engine architectural boundaries.
