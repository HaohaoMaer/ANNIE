"""Smoke test: MinecraftBridge + NPCAgent with real LLM.

Usage
-----
First open Minecraft → Open to LAN → note port, then:

  Bridge-only test (no LLM):
    PYTHONPATH=src python scripts/smoke_minecraft_bridge.py --port 55916

  Full cognition test (bridge + LLM — needs DEEPSEEK_API_KEY):
    PYTHONPATH=src python scripts/smoke_minecraft_bridge.py --port 55916 --cognition
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("smoke_minecraft")


def test_bridge_only(host: str, port: int, username: str) -> None:
    """Connect, print perception, disconnect."""
    from annie.minecraft.bot_connection import MinecraftBridge
    from annie.minecraft.perception import MinecraftPerception

    bridge = MinecraftBridge(host=host, port=port, username=username)
    try:
        logger.info("Starting Minecraft bridge...")
        bridge.start()

        logger.info("Bot ready. Gathering perception...")
        perception = MinecraftPerception(bridge)
        snapshot = perception.snapshot()
        print(perception.render(snapshot))
        print("---")
        stats = snapshot["stats"]
        print(f"[OK] Bot '{username}' alive at {stats.get('position')}")
        print(f"     Nearby blocks: {len(snapshot['blocks'].get('blocks', []))}")
        print(f"     Nearby entities: {len(snapshot['entities'].get('entities', []))}")

    finally:
        bridge.stop()
        logger.info("Bridge stopped.")


def test_full_cognition(host: str, port: int, username: str) -> None:
    """Connect, run one NPCAgent cognition cycle, disconnect."""
    from annie.minecraft.bot_connection import MinecraftBridge
    from annie.minecraft.engine import MinecraftWorldEngine, _default_survivor_profile
    from annie.npc.agent import NPCAgent
    from annie.npc.llm import create_chat_model
    from annie.npc.config import load_model_config

    config_path = Path("config/model_config.yaml")
    if not config_path.exists():
        logger.error("config/model_config.yaml not found.")
        return
    model_config = load_model_config(str(config_path))
    llm = create_chat_model(model_config)
    agent = NPCAgent(llm=llm)

    bridge = MinecraftBridge(host=host, port=port, username=username)
    try:
        logger.info("Starting Minecraft bridge...")
        bridge.start()

        profile = _default_survivor_profile()
        engine = MinecraftWorldEngine(
            bridge=bridge,
            profile=profile,
            history_dir="./data/minecraft/smoke_history",
            llm=llm,
        )

        logger.info("Running one cognition tick...")
        response = engine.step(agent, engine._npc_id)
        if response is not None:
            print(f"\n--- NPC Response ---")
            print(f"Dialogue: {response.dialogue[:300]}")
            print(f"Inner thought: {response.inner_thought[:200]}")
            print(f"Actions: {[a.type for a in response.actions]}")
            print(f"---")
            print(f"[OK] Cognition test passed.")
        else:
            print("[OK] Reflex fired only.")

    finally:
        bridge.stop()
        logger.info("Bridge stopped.")


def main():
    parser = argparse.ArgumentParser(description="Minecraft bridge smoke test")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55916)
    parser.add_argument("--username", default="ANNIE_SmokeBot")
    parser.add_argument("--cognition", action="store_true")
    args = parser.parse_args()

    if args.cognition:
        test_full_cognition(args.host, args.port, args.username)
    else:
        test_bridge_only(args.host, args.port, args.username)


if __name__ == "__main__":
    main()
