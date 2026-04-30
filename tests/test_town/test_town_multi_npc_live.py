from __future__ import annotations

import os
from pathlib import Path

import chromadb
import pytest

from annie.npc.agent import NPCAgent
from annie.npc.config import load_model_config
from annie.npc.llm import create_chat_model
from annie.town import TownWorldEngine, create_small_town_state, run_multi_npc_day


@pytest.mark.integration
def test_live_llm_multi_npc_town_smoke(tmp_path: Path) -> None:
    config = load_model_config("config/model_config.yaml")
    if not os.environ.get(config.model.api_key_env):
        pytest.skip(f"{config.model.api_key_env} is required for live town LLM smoke")
    if os.environ.get("ANNIE_RUN_TOWN_LIVE_LLM") != "1":
        pytest.skip("Set ANNIE_RUN_TOWN_LIVE_LLM=1 to run the live town LLM smoke")

    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vs")),
        history_dir=tmp_path / "history",
    )
    agent = NPCAgent(create_chat_model(config), max_retries=1)

    result = run_multi_npc_day(
        engine,
        agent,
        ["alice", "bob", "clara"],
        start_minute=8 * 60,
        end_minute=10 * 60,
        max_ticks=12,
        replay_dir=tmp_path / "replay",
    )

    assert result.ok is True
    assert result.replay_paths["actions"].exists()
    assert result.replay_paths["checkpoints"].exists()
    assert any(item["action_type"] in {"move_to", "wait"} for item in engine.action_log)
