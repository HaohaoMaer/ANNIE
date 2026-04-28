import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Configure detailed logging for testing
# This will show LangGraph nodes, tool calls, and LLM interactions in the console.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
# Silence some noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# Load .env file automatically
load_dotenv()

# Add src to python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from annie.interrogation.engine import InterrogationEngine, GamePhase
from annie.npc.agent import NPCAgent
from annie.npc.llm import create_chat_model
from annie.npc.config import load_model_config
from annie.npc.context import AgentContext

def print_banner(text):
    print("\n" + "="*60)
    print(f" {text} ".center(60, "="))
    print("="*60 + "\n")

def run_game():
    script_dir = "double_shadow"
    engine = InterrogationEngine(script_dir)
    
    # Load model config and create LLM
    try:
        config = load_model_config("config/model_config.yaml")
        llm = create_chat_model(config)
    except Exception as e:
        print(f"错误：无法加载模型配置或创建 LLM。请检查 .env 和 config/model_config.yaml。\n{e}")
        return

    print_banner("《双重暗影》：审讯与搜证游戏 (DEBUG 模式)")
    print("系统提示：底层日志已开启，你可以看到 Agent 的执行过程。")

    while not engine.state.is_game_over:
        phase = engine.state.current_phase
        
        if phase in [GamePhase.INITIAL_INT, GamePhase.SECOND_INT, GamePhase.FINAL_INT]:
            run_interrogation_round(engine, llm, phase)
        elif phase in [GamePhase.SEARCH_1, GamePhase.SEARCH_2]:
            run_search_round(engine, phase)
        elif phase == GamePhase.VERDICT:
            run_verdict_round(engine, llm)
            break

def run_interrogation_round(engine, llm, phase):
    print_banner(f"审讯阶段：{phase.value}")
    npc_ids = list(engine.state.npc_turns_left.keys())
    
    # Initialize NPCAgent (Stateless)
    agent = NPCAgent(llm=llm)

    while any(engine.state.npc_turns_left[nid] > 0 for nid in npc_ids):
        print("\n当前可审讯对象：")
        for i, nid in enumerate(npc_ids):
            turns = engine.state.npc_turns_left[nid]
            hr = engine.state.npc_heart_rates.get(nid, 60)
            print(f"{i+1}. {nid} (剩余回合: {turns}, 当前心率: {hr} bpm)")
        
        choice = input("\n请选择审讯对象编号 (输入 q 退出, n 跳过本阶段): ")
        if choice.lower() == 'q':
            sys.exit(0)
        if choice.lower() == 'n':
            engine.advance_phase()
            return
            
        try:
            idx = int(choice) - 1
            target_npc = npc_ids[idx]
        except:
            print("输入无效。")
            continue
            
        if engine.state.npc_turns_left[target_npc] <= 0:
            print(f"{target_npc} 在本阶段的审讯次数已用完。")
            continue

        # Interrogation prompt
        print(f"\n--- 正在审讯 {target_npc} ---")
        msg = input("你的提问/出示证据 (输入 'evidence' 查看包, 'back' 返回): ")
        
        if msg.lower() == 'evidence':
            print(f"当前证据包: {engine.state.evidence_bag}")
            continue
        if msg.lower() == 'back':
            continue

        # Build context from engine
        context = engine.build_context(target_npc, msg)
        
        # Track the question for history in engine state
        engine.state.dialogue_history["_last_event"] = msg
        
        # Run agent with timing and logs
        try:
            print(f"\n>>> [AGENT START: {target_npc}]")
            response = agent.run(context)
            engine.handle_response(target_npc, response)
            
            # Fetch updated HR from engine state
            hr = engine.state.npc_heart_rates.get(target_npc, 60)
            
            print(f">>> [AGENT END]\n")

            # --- Content Cleaning Logic ---
            raw_dialogue = response.dialogue
            audit_content = ""
            
            # Extract audit tag if present using regex
            import re
            audit_match = re.search(r'<strategy_audit>(.*?)</strategy_audit>', raw_dialogue, re.DOTALL)
            if audit_match:
                audit_content = audit_match.group(1).strip()
                # Remove the tag from dialogue
                clean_dialogue = re.sub(r'<strategy_audit>.*?</strategy_audit>', '', raw_dialogue, flags=re.DOTALL).strip()
            else:
                clean_dialogue = raw_dialogue
                
            # Remove any stray markdown code fences
            clean_dialogue = re.sub(r'```.*?```', '', clean_dialogue, flags=re.DOTALL).strip()
            clean_dialogue = clean_dialogue.replace('```', '')

            if response.reflection:
                print(f"[Agent Reflection]: {response.reflection}\n")
            
            # Display Audit and Thoughts
            print(f"[{target_npc} 的心理活动]:")
            if audit_content:
                print(f"--- 策略审计 ---\n{audit_content}\n---------------")
            if response.inner_thought:
                print(response.inner_thought)
            
            print(f"\n[{target_npc}]: {clean_dialogue}")
            print(f"\n>> 实时心率反馈: {hr} bpm <<")
            
        except Exception as e:
            print(f"运行时错误：{e}")
            import traceback
            traceback.print_exc()

    print("\n本轮审讯结束，准备进入下一阶段...")
    engine.step()

def run_search_round(engine, phase):
    print_banner(f"搜证阶段：{phase.value}")
    locations = engine.state.unlocked_locations
    print(f"可搜查地点 (请选择 2 个):")
    for i, loc in enumerate(locations):
        print(f"{i+1}. {loc}")
        
    choice_str = input("\n请输入地点编号 (例如 '1 2'): ")
    choices = choice_str.split()
    try:
        selected = [locations[int(c)-1] for c in choices[:2]]
    except:
        print("选择无效，搜证失败。")
        selected = []
        
    if selected:
        results = engine.search_locations(selected)
        print("\n搜证结果：")
        for res in results:
            loc = res['location']
            ev = res['evidence']
            if ev:
                print(f" - 在 [{loc}] 发现了：{ev['name']}")
                print(f"   描述：{ev['description']}")
            else:
                print(f" - 在 [{loc}] 未发现任何相关线索。")
            
    input("\n按下回车键进入下一轮审讯...")

def run_verdict_round(engine, llm):
    print_banner("最终真相揭露")
    print("请根据以下几个方面描述案件真相：")
    print("1. 谁杀害了真正的陆远山？")
    print("2. 活着的那个人的真实身份是谁？")
    print("3. 本案的深层动机是什么？")
    print("4. 谁协助了这场身份窃取？")
    
    verdict = input("\n请输入你的最终推论：\n")
    
    print("\n系统正在进行判定...")
    
    score = 0
    if "周正" in verdict or "npc_survivor_lu" in verdict:
        score += 40
    if "身份" in verdict or "取代" in verdict:
        score += 20
    if "剽窃" in verdict or "复仇" in verdict:
        score += 20
    if "陈默" in verdict:
        score += 20
        
    print(f"\n判定得分: {score}/100")
    if score >= 70:
        print("\n【胜利】你成功识破了周正的诡计！")
        epilogue = engine.truth.get("judgement_rubric", {}).get("epilogue_resonance", "真相大白。")
        print(f"\n结局：{epilogue}")
    else:
        print("\n【失败】真相被埋没在阴影之中...")

if __name__ == "__main__":
    run_game()
