"""Smoke test: DefaultWorldEngine + NPCAgent with a real LLM.

Runs two turns against one NPC so you can eyeball:
  * Planner → Executor (tool-use loop) → Reflector output
  * Rolling history injection on turn 2
  * Long-term memory population (episodic / reflection / possibly impression)

Usage:
    python scripts/smoke_npc_loop.py

Reads DEEPSEEK_API_KEY from .env (or environment). DeepSeek is used via its
OpenAI-compatible endpoint through ``ChatOpenAI``. Switch the constructor
at the top if you want another provider. The run uses a fresh tmpdir for
ChromaDB + history so your real data store is untouched.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from annie.npc import NPCAgent
from annie.npc.state import Background, Goals, NPCProfile, Personality
from annie.world_engine import DefaultWorldEngine


def _banner(title: str) -> None:
    print("\n" + "=" * 8 + f" {title} " + "=" * 8)


def main() -> None:
    load_dotenv()  # pull DEEPSEEK_API_KEY (and friends) from .env
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY not found in env or .env")

    llm = ChatOpenAI(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=api_key,
        temperature=0.7,
    )

    tmp = Path(tempfile.mkdtemp(prefix="annie_smoke_"))
    print(f"[smoke] scratch dir: {tmp}")

    we = DefaultWorldEngine(
        chroma_client=chromadb.PersistentClient(path=str(tmp / "vs")),
        history_dir=tmp / "hist",
        llm=llm,  # needed for Compressor.maybe_fold
        world_rules="午夜酒吧；雨夜；吧台上方只剩一盏暖黄吊灯。店里几乎没人。",
    )
    we.register_profile("alice", NPCProfile(
        name="Alice",
        personality=Personality(
            traits=["谨慎", "好奇", "嘴上客气心里警觉"],
            values=["不轻易出卖老客人"],
        ),
        background=Background(
            biography="酒吧侍者，在这家店做了十年。记得每个常客的酒量。",
            past_events=["三年前目击过一场斗殴，没报警。"],
        ),
        goals=Goals(
            short_term=["摸清陌生男子的来意", "不暴露对老陈的认识"],
            long_term=["攒钱盘下这家酒吧"],
        ),
        memory_seed=["老陈每周三晚来喝黑啤。"],
    ))
    we.set_situation("陌生男子推门而入，浑身湿透，身上有旧烟味。")

    agent = NPCAgent(llm=llm)

    # -------- Turn 1 --------
    _banner("Turn 1 · build_context")
    ctx1 = we.build_context("alice", event="陌生人走到吧台边坐下，低声说：'来杯最烈的。'")
    print(f"history (empty on first turn): {ctx1.history!r}")

    resp1 = agent.run(ctx1)
    _banner("Turn 1 · dialogue")
    print(resp1.dialogue)
    _banner("Turn 1 · reflection")
    print(resp1.reflection)
    we.handle_response("alice", resp1)

    # -------- Turn 2 --------
    # An external event enters Alice's rolling history without Alice speaking.
    we.ingest_external("alice", "player", "他把一枚生锈的铜钥匙放在吧台上，挪到她面前。")

    _banner("Turn 2 · build_context")
    ctx2 = we.build_context(
        "alice",
        event="陌生人盯着她的眼睛，低声说：'我在找一个叫老陈的人。'",
    )
    print("rendered history fed into the agent:")
    print(ctx2.history)

    resp2 = agent.run(ctx2)
    _banner("Turn 2 · dialogue")
    print(resp2.dialogue)
    _banner("Turn 2 · reflection")
    print(resp2.reflection)
    we.handle_response("alice", resp2)

    # -------- Memory probe --------
    _banner("Memory recall: '陌生人 钥匙 老陈'")
    for r in we.memory_for("alice").recall("陌生人 钥匙 老陈", k=6):
        print(f"  [{r.category}] ({r.relevance_score:.2f}) {r.content[:100]}")

    _banner("History JSONL on disk")
    jsonl = tmp / "hist" / "alice.jsonl"
    print(f"path: {jsonl}")
    if jsonl.exists():
        for i, line in enumerate(jsonl.read_text(encoding="utf-8").splitlines(), 1):
            print(f"  {i}: {line[:160]}")

    print(f"\n[smoke] done. Scratch dir preserved at: {tmp}")


if __name__ == "__main__":
    main()
