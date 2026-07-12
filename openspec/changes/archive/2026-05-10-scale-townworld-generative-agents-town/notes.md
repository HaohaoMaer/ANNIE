## Verification Notes

- Deterministic tests:
  `conda run -n annie env PYTHONPATH=src python -m pytest tests/test_town/test_town_scenario_loader.py tests/test_town/test_town_runtime_runner.py tests/test_town/test_town_resume_validation.py tests/test_town/test_town_replay_viewer.py`
  passed with 23 tests.
- Lint:
  `conda run -n annie ruff check scripts/validate_townworld_scaled_real_llm.py src/annie/town/content/scenario.py src/annie/town/runtime/runner.py src/annie/town/runtime/validation.py src/annie/town/engine.py tests/test_town/test_town_scenario_loader.py tests/test_town/test_town_runtime_runner.py`
  passed.
- Type check:
  `conda run -n annie npx pyright scripts/validate_townworld_scaled_real_llm.py`
  passed. A broader `pyright src/annie/town scripts/validate_townworld_scaled_real_llm.py`
  still reports pre-existing typing issues in existing town runtime modules.
- OpenSpec:
  `openspec validate scale-townworld-generative-agents-town --strict` passed.

## Real-LLM Smoke

Command:

```bash
conda run -n annie env PYTHONPATH=src python scripts/validate_townworld_scaled_real_llm.py --resident-count 1 --days 1 --start-minute 480 --end-minute 490 --max-ticks 1 --retries 0 --prompt-preview-length 400 --output-dir runs/town_scaled_real_llm/smoke-scale-townworld-generative-agents-town
```

Artifacts:

- Terminal output: `runs/town_scaled_real_llm/smoke-scale-townworld-generative-agents-town/terminal_output.txt`
- Summary: `runs/town_scaled_real_llm/smoke-scale-townworld-generative-agents-town/summary.json`
- Diagnostics: `runs/town_scaled_real_llm/smoke-scale-townworld-generative-agents-town/diagnostics.json`
- Manifest: `runs/town_scaled_real_llm/smoke-scale-townworld-generative-agents-town/manifest.json`
- Latest snapshot: `runs/town_scaled_real_llm/smoke-scale-townworld-generative-agents-town/state/latest.json`

Smoke result:

- LLM calls: 1
- Runner failure: none
- Behavior-quality warnings: unfinished schedule count and no conversations observed,
  which are expected for a one-resident, one-tick smoke.
