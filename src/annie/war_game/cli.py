"""CLI game loop for the three-faction war game."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from typing import Callable

from annie.war_game.config import GameConfig
from annie.war_game.display import (
    render_declarations,
    render_force_pool,
    render_game_over_summary,
    render_map,
    render_round_header,
    render_victory,
)
from annie.war_game.map_preset import FACTION_NAMES, PLAYER
from annie.war_game.phases import (
    declaration_phase,
    deployment_phase,
    diplomacy_phase,
    generate_round_report,
    resolution_phase,
)


# ---- Spinner for AI thinking ---------------------------------------------

class _Spinner:
    """Simple terminal spinner."""

    def __init__(self, text: str = "思考中") -> None:
        self._text = text
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join()
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()

    def _spin(self) -> None:
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while self._running:
            sys.stdout.write(f"\r{chars[i % len(chars)]} {self._text}...")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1


# ---- Player input handlers -----------------------------------------------

def _player_declaration(prompt: str) -> str:
    return input(prompt).strip() or "（无宣言）"


def _player_diplomacy(prompt: str) -> str:
    return input(prompt).strip()


def _on_ai_message(faction_name: str, message: str) -> None:
    print(f"\n  [{faction_name}]: {message}")


def _player_deployment(prompt: str, state, faction_id: str) -> list[dict]:
    """Interactive force deployment for the player."""
    owned = state.owned_cities(faction_id)
    enemies = state.adjacent_enemies(faction_id)
    pool = state.factions[faction_id].force_pool

    while True:
        print(f"\n{render_force_pool(state, faction_id)}")
        print("\n你的城市:")
        for c in sorted(owned, key=lambda c: c.id):
            adj_enemy = [
                a for a in c.adjacent if state.cities[a].owner != faction_id
            ]
            adj_str = f" (相邻敌方: {', '.join(adj_enemy)})" if adj_enemy else ""
            print(f"  {c.id}{adj_str}")

        print("\n可进攻的相邻敌方城市:")
        for c in sorted(enemies, key=lambda c: c.id):
            owner_name = FACTION_NAMES.get(c.owner, c.owner)
            print(f"  {c.id} (属于{owner_name})")

        print(f"\n请分配你的全部 {pool} 兵力。")
        print("格式: 城市 兵力 动作 (每行一条, 动作为 d=防守 a=进攻)")
        print("例如:")
        print("  P1 200 d")
        print("  P2 300 d")
        print("  A3 500 a")
        print("输入空行结束:")

        allocations: list[dict] = []
        while True:
            line = input("  > ").strip()
            if not line:
                break
            parts = line.split()
            if len(parts) != 3:
                print("  格式错误，请重试。格式: 城市 兵力 动作")
                continue
            target, troops_str, action_code = parts
            try:
                troops = int(troops_str)
            except ValueError:
                print(f"  兵力必须是数字: {troops_str}")
                continue
            action = "defend" if action_code.lower().startswith("d") else "attack"
            allocations.append({"target": target, "troops": troops, "action": action})

        # Validate
        total = sum(a["troops"] for a in allocations)
        if total != pool:
            print(f"\n  错误: 分配总兵力 ({total}) 不等于你的兵力池 ({pool})。请重新分配。")
            continue

        owned_ids = {c.id for c in owned}
        missing = owned_ids - {a["target"] for a in allocations if a["action"] == "defend"}
        if missing:
            print(f"\n  错误: 缺少城市防守分配: {', '.join(sorted(missing))}（可以分配0兵力）")
            continue

        adj_ids = {c.id for c in enemies}
        bad_attacks = [
            a["target"] for a in allocations
            if a["action"] == "attack" and a["target"] not in adj_ids
        ]
        if bad_attacks:
            print(f"\n  错误: 无法进攻非相邻城市: {', '.join(bad_attacks)}")
            continue

        return allocations


def _player_negotiate_decision() -> str:
    """Get withdraw/fight from the player during 2v1."""
    while True:
        choice = input("\n最终决定 [withdraw/fight]: ").strip().lower()
        if choice in ("withdraw", "fight", "w", "f"):
            return "withdraw" if choice.startswith("w") else "fight"
        print("请输入 'withdraw'(撤退) 或 'fight'(战斗)")


def _make_diplo_callback(spinner: _Spinner) -> Callable[[str, str], None]:
    def _cb(name: str, msg: str) -> None:
        spinner.stop()
        _on_ai_message(name, msg)
        spinner.start()
    return _cb


# ---- Main game loop -------------------------------------------------------

def run_game(config: GameConfig | None = None, model_config_path: str = "config/model_config.yaml") -> None:
    """Run the interactive CLI game loop."""
    from dotenv import load_dotenv  # type: ignore[import-untyped]

    from annie.npc.agent import NPCAgent
    from annie.npc.config import load_model_config
    from annie.npc.llm import create_chat_model
    from annie.war_game.engine import WarGameEngine

    load_dotenv()

    cfg = config or GameConfig()

    # Init LLM via project config (DeepSeek by default)
    model_cfg = load_model_config(model_config_path)
    llm = create_chat_model(model_cfg)
    agent = NPCAgent(llm=llm)
    engine = WarGameEngine(config=cfg, agent=agent, llm=llm)
    state = engine.state

    print("\n" + "="*40)
    print("  三方势力争霸 — 语言欺诈策略游戏")
    print("="*40)
    print(render_map(state))
    print(render_force_pool(state, PLAYER))

    try:
        while not state.is_game_over():
            state.round_number += 1
            print(render_round_header(state.round_number))

            # Phase 1: Declaration
            print("\n--- 宣言阶段 ---")
            spinner = _Spinner("AI正在思考宣言")
            # Player declares first
            player_decl = _player_declaration("你的宣言: ")
            state.declarations[PLAYER] = player_decl
            # AI declarations with spinner
            spinner.start()
            declaration_phase(
                state, engine, agent,
                player_input_fn=None,  # player already declared
            )
            state.declarations[PLAYER] = player_decl  # re-set player decl
            spinner.stop()
            print(render_declarations(state.declarations))

            # Phase 2: Diplomacy
            print("\n--- 外交阶段 ---")
            spinner_diplo = _Spinner("AI正在外交")

            def player_diplo_input(prompt: str) -> str:
                spinner_diplo.stop()
                result = _player_diplomacy(prompt)
                spinner_diplo.start()
                return result

            diplomacy_phase(
                state, engine, agent,
                player_input_fn=player_diplo_input,
                on_ai_message=_make_diplo_callback(spinner_diplo),
            )
            spinner_diplo.stop()

            # Phase 3: Deployment
            print("\n--- 部署阶段 ---")
            # Player deploys
            player_allocs = _player_deployment("", state, PLAYER)
            from annie.war_game.game_state import Deployment
            state.deployments[PLAYER] = [
                Deployment(target=a["target"], troops=a["troops"], action=a["action"])
                for a in player_allocs
            ]
            # AI deploys
            spinner_deploy = _Spinner("AI正在部署兵力")
            spinner_deploy.start()
            deployment_phase(state, engine, agent, player_input_fn=None)
            # Keep player deployment (deployment_phase with None skips player but we already set it)
            spinner_deploy.stop()

            # Phase 4: Resolution
            print("\n--- 结算阶段 ---")
            results = resolution_phase(
                state, engine, agent,
                player_negotiate_fn=_player_negotiate_decision,
            )

            # Display results
            report = generate_round_report(state, results)
            print(f"\n{report}")
            print(f"\n{render_map(state)}")
            print(render_force_pool(state, PLAYER))

        # Game over
        w = state.winner()
        if w:
            print(render_victory(w))
        print(render_game_over_summary(state))

    except (KeyboardInterrupt, EOFError):
        print("\n\n游戏中断。")
        print(render_game_over_summary(state))


def main() -> None:
    parser = argparse.ArgumentParser(description="三方势力争霸 — 语言欺诈策略游戏")
    parser.add_argument("--diplomacy-rounds", type=int, default=3, help="外交轮数 (default: 3)")
    parser.add_argument("--production", type=int, default=50, help="每城每回合产出 (default: 50)")
    parser.add_argument("--initial-forces", type=int, default=1000, help="初始兵力 (default: 1000)")
    parser.add_argument("--model-config", type=str, default="config/model_config.yaml", help="LLM配置文件路径")
    args = parser.parse_args()

    config = GameConfig(
        initial_forces=args.initial_forces,
        production_per_city=args.production,
        max_diplomacy_rounds=args.diplomacy_rounds,
    )
    run_game(config=config, model_config_path=args.model_config)


if __name__ == "__main__":
    main()
