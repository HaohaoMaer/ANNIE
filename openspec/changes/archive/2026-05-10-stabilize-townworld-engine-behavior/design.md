## Design Notes

TownWorldEngine owns deterministic behavior. Prompts should describe stable rules,
but movement routing, conversation success, schedule completion, and tool argument
coercion are enforced in engine/tool code.

Movement uses the existing directed location graph. If the requested destination is
not a direct exit but is reachable, the engine computes the shortest route and moves
only to the next hop. The action remains successful and facts include the requested
destination, actual destination, route, and `auto_routed=true`.

Dialogue keeps old Python APIs for compatibility, but NPC context receives only
`talk_to`. The tool delegates to the managed conversation flow. If the first turn is
empty, the engine retries once; if it is still empty, the action fails with
`empty_conversation` and no cooldown is written.

Schedule completion uses `completed_schedule_segments` as the single read model.
Completion types are normalized to `explicit_request`, `inferred_action_match`,
`repair`, and `day_finalize_missed`. Explicit completion validates that a current or
recoverable segment exists and that the resident is at the segment location or has
recent successful evidence for it.

Memory recall input normalization stays in the built-in NPC tool layer because it is
business-agnostic argument coercion.
