# Town Multi-NPC Smoke

The deterministic multi-NPC smoke runs through `pytest`:

```bash
PYTHONPATH=src pytest tests/test_town/test_town_multi_npc.py
```

The deterministic replay snapshot smoke can also be run directly:

```bash
PYTHONPATH=src python scripts/show_town_replay_snapshot.py
```

The live LLM smoke is opt-in because it calls the configured provider in
`config/model_config.yaml`:

```bash
ANNIE_RUN_TOWN_LIVE_LLM=1 DEEPSEEK_API_KEY=... \
  PYTHONPATH=src pytest -m integration tests/test_town/test_town_multi_npc_live.py
```

The standalone live script keeps reflection disabled by default. Pass
`--enable-reflection` to use the same `NPCAgent` as the opt-in reflection
backend:

```bash
conda run -n annie python scripts/run_town_multi_npc_real_llm.py --enable-reflection
```

Both runners write replay artifacts only when a `replay_dir` is passed. The
current files are:

- `town_replay.jsonl`: action stream with tick time, NPC id, action type,
  status, location, summary, and facts.
- `town_checkpoints.jsonl`: per-tick run/skip records plus `snapshot`.
- `town_timeline.txt`: compact human-readable action timeline.
- `town_reflections.jsonl`: opt-in reflection events; the file exists even when
  no reflection was generated.

Each checkpoint `snapshot` contains:

- `day`, `minute`, and `time`.
- `residents`, keyed by NPC id, with `location_id`, `current_action`,
  `current_schedule`, `schedule_completed`, `poignancy`, `reflection_due`, and
  `reflection_evidence_count`.
- `conversation_sessions`, with stable session metadata only: id, participants,
  status, location, topic/reason, turn count, start/end minute, and close
  reason. Raw transcripts stay out of checkpoint snapshots.
- `reflection_events`, containing reflection events generated during that tick.
