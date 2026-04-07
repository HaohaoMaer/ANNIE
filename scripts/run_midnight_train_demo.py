#!/usr/bin/env python3
"""午夜列车剧本杀Demo

使用ANNIE系统运行一个完整的剧本杀游戏。

使用方法：
    python scripts/run_midnight_train_demo.py

要求：
    - DEEPSEEK_API_KEY 环境变量已设置（.env文件）
    - 午夜列车 剧本文件夹在项目根目录下
"""

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from annie.npc.config import load_model_config
from annie.world_engine.world_engine_agent import WorldEngineAgent

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def header(text: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {BOLD}{text}{RESET}")
    print(f"{'=' * 70}\n")


def section(text: str) -> None:
    print(f"\n{BOLD}{CYAN}>>> {text}{RESET}\n")


def success(text: str) -> None:
    print(f"{GREEN}✓ {text}{RESET}")


def info(text: str) -> None:
    print(f"{DIM}  {text}{RESET}")


def error(text: str) -> None:
    print(f"{RED}✗ {text}{RESET}")


def show_character_summary(name: str, summary_str: str) -> None:
    """Display a character's script summary."""
    print(f"\n  {BOLD}{CYAN}【{name}】{RESET}")
    try:
        info_dict = json.loads(summary_str)
        if info_dict.get("identity"):
            print(f"  身份: {info_dict['identity']}")
        if info_dict.get("background"):
            bg = info_dict["background"][:150]
            print(f"  背景: {bg}{'...' if len(info_dict['background']) > 150 else ''}")
        if info_dict.get("personality_traits"):
            print(f"  性格: {', '.join(info_dict['personality_traits'][:4])}")
        if info_dict.get("goals"):
            print(f"  目标: {', '.join(info_dict['goals'][:2])}")
        if info_dict.get("secrets"):
            print(f"  秘密: {len(info_dict['secrets'])}个隐藏信息")
    except (json.JSONDecodeError, KeyError):
        preview = summary_str[:200]
        print(f"  {preview}{'...' if len(summary_str) > 200 else ''}")


def main():
    header("午夜列车 - ANNIE剧本杀Demo")

    script_folder = Path(__file__).parent.parent / "午夜列车"

    if not script_folder.exists():
        error(f"剧本文件夹不存在: {script_folder}")
        print("\n请确保'午夜列车'文件夹在项目根目录下，包含以下内容：")
        print("  - 人物剧本/ (角色PDF文件)")
        print("  - 线索/ (线索图片)")
        print("  - 背景.docx, 游戏流程.docx, 真相.pdf")
        return

    print(f"{YELLOW}提示: 首次运行需要OCR处理（约2-3分钟），请耐心等待{RESET}")
    print(f"{YELLOW}      每局游戏使用全新记忆，不会受到之前运行的影响{RESET}\n")

    # ── Step 1: Initialize ────────────────────────────────────────
    section("1/5 初始化世界引擎")

    try:
        config = load_model_config("config/model_config.yaml")
        world_engine = WorldEngineAgent(script_folder=script_folder, config=config)
        success("世界引擎初始化完成（使用临时记忆，每局全新开始）")
    except Exception as e:
        error(f"初始化失败: {e}")
        return

    # ── Step 2: Read script files ─────────────────────────────────
    section("2/5 读取剧本文件")

    print("正在读取: 背景.docx, 游戏流程.docx, 真相.pdf, 人物剧本/*.pdf, 线索/**/*")
    print(f"{DIM}(OCR处理中，EasyOCR使用PyTorch进行文字识别){RESET}\n")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            world_engine.read_all_files()

        success("剧本文件读取完成")
        info(f"背景故事: {len(world_engine.background)} 字符")
        info(f"游戏流程: {len(world_engine.game_flow_doc)} 字符")
        info(f"真相文件: {len(world_engine.truth)} 字符")
        info(f"角色剧本: {len(world_engine.character_scripts)} 个角色")

        total_clues = sum(len(v) for v in world_engine.clues_data.values())
        info(f"线索图片: {total_clues} 张 ({len(world_engine.clues_data)} 个分类)")

    except Exception as e:
        error(f"读取失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # ── Step 3: Show character summaries ──────────────────────────
    section("3/5 角色剧本预览")

    if world_engine.character_summaries:
        for char_name, summary in world_engine.character_summaries.items():
            show_character_summary(char_name, summary)
        print()
        success(f"共 {len(world_engine.character_summaries)} 个角色剧本已总结")
    else:
        error("角色剧本摘要为空")
        return

    # ── Step 4: Generate game flow + Initialize NPCs ──────────────
    section("4/5 生成游戏流程 & 初始化NPC")

    print("正在使用LLM生成游戏流程...")
    try:
        game_flow = world_engine.generate_game_flow()
        success("游戏流程生成完成")
        if "phases" in game_flow:
            for i, phase in enumerate(game_flow["phases"], 1):
                print(f"    {i}. {phase.get('name', '未命名阶段')}")
    except Exception as e:
        error(f"生成游戏流程失败: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n正在初始化NPC角色...")
    try:
        world_engine.initialize_npcs()
        success(f"NPC初始化完成: {len(world_engine.npcs)} 个角色")

        for npc_name, profile in world_engine.npc_profiles.items():
            traits = ", ".join(profile.personality.traits[:3]) if profile.personality.traits else "无"
            has_bio = "✓" if profile.background.biography else "✗"
            has_goals = "✓" if (profile.goals.short_term or profile.goals.long_term) else "✗"
            has_secrets = "✓" if profile.memory_seed else "✗"
            print(f"    {npc_name}: 性格[{traits}] 背景{has_bio} 目标{has_goals} 秘密{has_secrets}")

    except Exception as e:
        error(f"NPC初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # ── Step 5: Run game ──────────────────────────────────────────
    section("5/5 开始游戏")

    header("游戏开始")

    try:
        world_engine.start_game()
        world_engine.run_game_loop(max_rounds=2)
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}游戏被用户中断{RESET}")
    except Exception as e:
        error(f"游戏运行错误: {e}")
        import traceback
        traceback.print_exc()

    # ── Final stats ───────────────────────────────────────────────
    header("游戏统计")

    print(f"  NPC数量: {len(world_engine.npcs)}")
    print(f"  对话轮数: {len(world_engine.dialogue_history)}")
    print(f"  线索总数: {world_engine.clue_manager.get_total_count()}")
    print(f"  已发现线索: {world_engine.clue_manager.get_discovered_count()}")

    if world_engine.clue_manager.get_discovered_count() > 0:
        print(f"\n  {BOLD}已发现的线索:{RESET}")
        for clue in world_engine.clue_manager.get_discovered_clues()[:5]:
            content_preview = clue.content[:50] if clue.content else "(无文字内容)"
            print(f"    - [{clue.category}] {clue.file_name}: {content_preview}")

    print(f"\n{GREEN}✓ Demo运行完成！{RESET}\n")


if __name__ == "__main__":
    main()
