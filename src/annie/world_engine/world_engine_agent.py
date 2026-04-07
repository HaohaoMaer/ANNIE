"""World Engine Agent - The Game Master for murder mystery games.

This agent acts as the director and narrator, controlling game flow,
managing NPCs, and ensuring the story progresses according to the script.
"""

from __future__ import annotations

import json
import logging
import random
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chromadb
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.agent import NPCAgent
from annie.npc.config import ModelConfig
from annie.npc.llm import create_chat_model
from annie.npc.state import (
    Background,
    Goals,
    NPCProfile,
    Personality,
    RelationshipDef,
)
from annie.npc.tools.docx_reader import DOCXReaderTool
from annie.npc.tools.image_reader import ImageReaderTool
from annie.npc.tools.pdf_reader import PDFReaderTool
from annie.npc.tools.pdf_ocr import PDFOCRTool
from annie.social_graph.event_log import SocialEventLog
from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import RelationshipEdge as SocialRelationshipEdge
from annie.world_engine.clue_manager import Clue, ClueManager
from annie.world_engine.game_master import GameMaster
from annie.world_engine.game_master.phase_controller import Phase

logger = logging.getLogger(__name__)

DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

GAME_MASTER_SYSTEM_PROMPT = """\
你是"午夜列车"剧本杀游戏的主持人（世界引擎Agent）。

你的职责是：
1. 控制游戏流程，确保每个阶段都有足够的互动
2. 观察NPC的行为，在合适的时候提供线索和引导
3. 在投票阶段引导投票，确保每个人都做出选择
4. 在最终阶段揭示真相，公布结果

你必须保持中立，不偏向任何角色。你知道完整的真相，但只在适当的时候揭露。
请用生动有感染力的语言来主持游戏。
"""


class WorldEngineAgent:
    """World Engine Agent - Acts as the Game Master for murder mystery games.

    This agent:
    1. Reads all script files (PDF, DOCX, images)
    2. Generates game flow using LLM
    3. Initializes all NPCs with rich profiles from script summaries
    4. Controls game progression with dialogue history
    5. Manages voting and announces results deterministically
    """

    def __init__(
        self,
        script_folder: str | Path,
        config: ModelConfig | None = None,
        config_path: str | Path = "config/model_config.yaml",
    ) -> None:
        self.script_folder = Path(script_folder)

        from annie.npc.config import load_model_config
        self.config = config or load_model_config(config_path)
        self.llm = create_chat_model(self.config)

        self.pdf_reader = PDFReaderTool()
        self.pdf_ocr = PDFOCRTool()
        self.image_reader = ImageReaderTool()
        self.docx_reader = DOCXReaderTool()

        self.background: str = ""
        self.game_flow_doc: str = ""
        self.truth: str = ""
        self.character_scripts: dict[str, str] = {}
        self.character_summaries: dict[str, str] = {}
        self.clues_data: dict[str, list[dict]] = {}

        self.social_graph = SocialGraph()
        self.event_log = SocialEventLog()
        self.clue_manager = ClueManager()
        self.game_master = GameMaster()

        # Use ephemeral ChromaDB so each game starts with clean memory
        self._chroma_client = chromadb.EphemeralClient()

        self.npcs: dict[str, NPCAgent] = {}
        self.npc_profiles: dict[str, NPCProfile] = {}
        self.dialogue_history: list[dict] = []

        self._game_started = False
        self._start_time: datetime | None = None

        # Search batch mechanics: clues split into 2 rounds for search phases
        self._search_batches: list[list[str]] = []  # list of clue ID batches
        self._search_batch_revealed: int = 0  # how many batches have been revealed
        self._last_revealed_clues: list[Clue] = []  # clues revealed in last batch

        # Social graph snapshots collected during game loop for session saving
        self._graph_snapshots: list[dict] = []

        # Vote/truth results stored for session saving
        self._final_results: dict | None = None

        # OCR cache: persisted to disk to avoid re-running OCR on every restart
        self._ocr_cache_path = self.script_folder / ".ocr_cache.json"
        self._ocr_cache: dict[str, dict] = {}
        self._load_ocr_cache()

    # ── OCR Cache ─────────────────────────────────────────────────────

    def _load_ocr_cache(self) -> None:
        """Load OCR results cache from disk."""
        if self._ocr_cache_path.exists():
            try:
                with open(self._ocr_cache_path, encoding="utf-8") as f:
                    self._ocr_cache = json.load(f)
                logger.info(f"Loaded OCR cache: {len(self._ocr_cache)} entries")
            except Exception as e:
                logger.warning(f"Failed to load OCR cache, will re-run OCR: {e}")
                self._ocr_cache = {}

    def _save_ocr_cache(self) -> None:
        """Persist OCR cache to disk."""
        try:
            with open(self._ocr_cache_path, "w", encoding="utf-8") as f:
                json.dump(self._ocr_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save OCR cache: {e}")

    def _get_cached_text(self, file_path: Path) -> str | None:
        """Return cached OCR text for a file, or None if absent/stale."""
        key = str(file_path.resolve())
        entry = self._ocr_cache.get(key)
        if entry is None:
            return None
        try:
            if abs(entry.get("mtime", 0) - file_path.stat().st_mtime) > 1.0:
                return None  # File has changed since last OCR
            return entry.get("text", "")
        except Exception:
            return None

    def _store_cached_text(self, file_path: Path, text: str) -> None:
        """Store an OCR result in the in-memory cache (call _save_ocr_cache after bulk ops)."""
        try:
            mtime = file_path.stat().st_mtime
        except Exception:
            mtime = 0.0
        self._ocr_cache[str(file_path.resolve())] = {"mtime": mtime, "text": text}

    # ── File Reading ──────────────────────────────────────────────────

    def read_all_files(
        self,
        event_callback: Callable[[dict], None] | None = None,
    ) -> None:
        """Read all script files from the script folder.

        Args:
            event_callback: Optional callback for live-streaming progress events.
        """
        logger.info(f"Reading script files from {self.script_folder}")

        self.background = self._read_docx("背景.docx")
        logger.info(f"Read background: {len(self.background)} chars")

        self.game_flow_doc = self._read_docx("游戏流程.docx")
        logger.info(f"Read game flow: {len(self.game_flow_doc)} chars")

        if event_callback:
            event_callback({"type": "initializing", "message": "正在读取真相文件..."})
        self.truth = self._read_pdf("真相.pdf")
        logger.info(f"Read truth: {len(self.truth)} chars")

        if event_callback:
            event_callback({"type": "initializing", "message": "正在读取角色剧本..."})
        self.character_scripts = self._read_character_scripts()
        logger.info(f"Read {len(self.character_scripts)} character scripts")

        if event_callback:
            event_callback({"type": "initializing", "message": "正在用LLM分析角色..."})
        self.character_summaries = self._summarize_character_scripts()
        logger.info(f"Summarized {len(self.character_summaries)} character scripts")

        if event_callback:
            event_callback({"type": "initializing", "message": "正在读取线索图片..."})
        self.clues_data = self._read_all_clues(event_callback=event_callback)
        total_clues = sum(len(v) for v in self.clues_data.values())
        logger.info(f"Read {total_clues} clue images from {len(self.clues_data)} categories")

        self._load_clues_to_manager()

    def _read_docx(self, filename: str) -> str:
        """Read a DOCX file from the script folder."""
        path = self.script_folder / filename
        if not path.exists():
            logger.warning(f"DOCX file not found: {path}")
            return ""

        result = self.docx_reader.execute({"docx_path": str(path)})
        return result.get("text", "")

    def _read_pdf(self, filename: str) -> str:
        """Read a PDF file from the script folder using OCR if needed."""
        path = self.script_folder / filename
        if not path.exists():
            logger.warning(f"PDF file not found: {path}")
            return ""

        # Check cache first
        cached = self._get_cached_text(path)
        if cached is not None:
            logger.info(f"Cache hit for {filename}")
            return cached

        # Try standard text extraction first (fast)
        result = self.pdf_reader.execute({"pdf_path": str(path)})
        content = result.get("content", "")

        # Fall back to OCR only if text extraction yields too little
        if len(content.strip()) < 50:
            logger.info(f"Standard extraction too short for {filename}, trying OCR...")
            result = self.pdf_ocr.execute({"pdf_path": str(path)})
            if result.get("success"):
                content = result.get("content", content)

        if content.strip():
            self._store_cached_text(path, content)
            self._save_ocr_cache()
        return content

    def _read_character_scripts(self) -> dict[str, str]:
        """Read all character scripts from 人物剧本/ folder."""
        scripts = {}
        script_folder = self.script_folder / "人物剧本"

        if not script_folder.exists():
            logger.warning(f"Character script folder not found: {script_folder}")
            return scripts

        cache_dirty = False
        for pdf_path in sorted(script_folder.glob("*.pdf")):
            # Check cache first
            cached = self._get_cached_text(pdf_path)
            if cached is not None:
                scripts[pdf_path.stem] = cached
                logger.info(f"Cache hit for {pdf_path.stem} ({len(cached)} chars)")
                continue

            # Try standard text extraction first (fast, no OCR)
            result = self.pdf_reader.execute({"pdf_path": str(pdf_path)})
            content = result.get("content", "")

            # Fall back to OCR only if text extraction yields too little
            if len(content.strip()) < 100:
                logger.info(f"Standard extraction too short for {pdf_path.stem}, trying OCR...")
                result = self.pdf_ocr.execute({"pdf_path": str(pdf_path)})
                content = result.get("content", "")

            if content.strip():
                scripts[pdf_path.stem] = content
                self._store_cached_text(pdf_path, content)
                cache_dirty = True
                logger.info(f"Read character script: {pdf_path.stem}, {len(content)} chars")
            else:
                logger.warning(f"Failed to read character script: {pdf_path.stem}")

        if cache_dirty:
            self._save_ocr_cache()
        return scripts

    def _summarize_character_scripts(self) -> dict[str, str]:
        """Summarize each character's script using LLM."""
        summaries = {}

        for char_name, script_content in self.character_scripts.items():
            if not script_content.strip():
                logger.warning(f"Empty script for {char_name}, skipping summary")
                summaries[char_name] = f'{{"identity": "未知", "background": "角色{char_name}的剧本内容为空"}}'
                continue

            logger.info(f"Summarizing script for {char_name}...")

            prompt = f"""请仔细阅读以下角色剧本，并提取关键信息生成一个详细的剧本梗概。

角色名：{char_name}
剧本内容：
{script_content}

请生成一个JSON格式的剧本梗概，包含以下内容：
{{
    "identity": "角色身份（职业、地位等）",
    "background": "背景故事（200-400字，要详细）",
    "personality_traits": ["性格特点1", "性格特点2", "性格特点3"],
    "values": ["价值观1", "价值观2"],
    "secrets": ["秘密1", "秘密2", "关键隐瞒信息"],
    "goals": ["目标1", "目标2"],
    "relationships": {{"其他角色": "关系描述"}},
    "key_info": ["关键信息1", "关键信息2"],
    "past_events": ["过去发生的重要事件1", "过去发生的重要事件2"],
    "murderer": true或false（是否是凶手）,
    "murder_method": "如果是凶手，作案手法（如果不是凶手则为空字符串）"
}}

请直接输出JSON，不要有其他内容。确保提取的信息准确完整，尤其是背景故事、秘密和关键信息要尽可能详细。"""

            try:
                response = self.llm.invoke([
                    SystemMessage(content="你是一个专业的剧本分析师，擅长从剧本中提取角色关键信息。请仔细分析并输出准确的JSON。"),
                    HumanMessage(content=prompt),
                ])
                content = response.content

                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                # Validate JSON
                parsed = json.loads(content.strip())
                if not parsed.get("background") or not parsed.get("secrets"):
                    logger.warning(f"Summary for {char_name} missing key fields, retrying...")
                    raise ValueError("Incomplete summary")

                summaries[char_name] = content.strip()
                logger.info(f"Successfully summarized script for {char_name}")

            except Exception as e:
                logger.error(f"Failed to summarize script for {char_name}: {e}")
                # Retry with simpler prompt
                try:
                    retry_prompt = f"请用中文总结以下角色的关键信息（身份、背景、秘密、目标、是否凶手），输出JSON格式：\n\n角色名：{char_name}\n\n{script_content[:3000]}"
                    response = self.llm.invoke([HumanMessage(content=retry_prompt)])
                    retry_content = response.content
                    if "```" in retry_content:
                        retry_content = retry_content.split("```json")[-1].split("```")[0] if "```json" in retry_content else retry_content.split("```")[1].split("```")[0]
                    summaries[char_name] = retry_content.strip()
                except Exception:
                    summaries[char_name] = f'{{"identity": "未知", "background": "角色{char_name}，剧本总结失败"}}'

        return summaries

    def _read_all_clues(
        self,
        event_callback: Callable[[dict], None] | None = None,
    ) -> dict[str, list[dict]]:
        """Read all clue images from 线索/ folder, using disk cache when available."""
        clues: dict[str, list[dict]] = {}
        clue_folder = self.script_folder / "线索"

        if not clue_folder.exists():
            logger.warning(f"Clue folder not found: {clue_folder}")
            return clues

        # Collect all image paths first so we can report progress
        all_images: list[Path] = []
        for category_folder in sorted(clue_folder.iterdir()):
            if category_folder.is_dir():
                all_images.extend(
                    p for p in sorted(category_folder.glob("*"))
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
                )

        total = len(all_images)
        cache_hits = sum(1 for p in all_images if self._get_cached_text(p) is not None)
        needs_ocr = total - cache_hits
        logger.info(f"Clue images: {total} total, {cache_hits} cached, {needs_ocr} need OCR")

        cache_dirty = False
        processed = 0
        for category_folder in sorted(clue_folder.iterdir()):
            if not category_folder.is_dir():
                continue

            category_name = category_folder.name
            clues[category_name] = []

            for img_path in sorted(category_folder.glob("*")):
                if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                    continue

                processed += 1

                # Try cache first
                cached = self._get_cached_text(img_path)
                if cached is not None:
                    clues[category_name].append({
                        "file": img_path.name,
                        "path": str(img_path),
                        "content": cached,
                    })
                    continue

                # Cache miss — run OCR
                ocr_num = processed - (cache_hits - sum(
                    1 for p in all_images[:processed - 1]
                    if self._get_cached_text(p) is not None
                ))
                if event_callback:
                    event_callback({
                        "type": "initializing",
                        "message": f"OCR线索图片 {processed}/{total}（{img_path.name}）...",
                    })
                logger.info(f"OCR {processed}/{total}: {img_path.name}")

                try:
                    result = self.image_reader.execute({"image_path": str(img_path)})
                    text = result.get("text", "")
                    clues[category_name].append({
                        "file": img_path.name,
                        "path": str(img_path),
                        "content": text,
                    })
                    self._store_cached_text(img_path, text)
                    cache_dirty = True
                except Exception as e:
                    logger.warning(f"Failed to OCR {img_path.name}: {e}")
                    clues[category_name].append({
                        "file": img_path.name,
                        "path": str(img_path),
                        "content": "",
                    })

            logger.info(f"Read {len(clues[category_name])} clues from {category_name}")

        if cache_dirty:
            self._save_ocr_cache()
        return clues

    def _load_clues_to_manager(self) -> None:
        """Load clues data into ClueManager and prepare search batches."""
        for category, clue_list in self.clues_data.items():
            for i, clue_info in enumerate(clue_list):
                clue_id = f"{category}_{i:02d}"
                clue = Clue(
                    id=clue_id,
                    category=category,
                    file_name=clue_info["file"],
                    content=clue_info["content"],
                    image_path=clue_info["path"],
                )
                self.clue_manager.add_clue(clue)

        # Randomly split all clues into 2 batches for the two search rounds
        all_ids = list(self.clue_manager.clues.keys())
        random.shuffle(all_ids)
        mid = len(all_ids) // 2
        self._search_batches = [all_ids[:mid], all_ids[mid:]]
        logger.info(
            f"Prepared search batches: {len(self._search_batches[0])} + "
            f"{len(self._search_batches[1])} clues"
        )

    # ── Game Flow Generation ──────────────────────────────────────────

    def generate_game_flow(self) -> dict[str, Any]:
        """Generate game flow using LLM based on the script documents."""
        logger.info("Generating game flow using LLM...")

        prompt = f"""你是一个剧本杀游戏的主持人。请根据以下信息生成游戏流程：

背景故事：
{self.background}

游戏流程文档：
{self.game_flow_doc}

角色列表：
{', '.join(self.character_scripts.keys())}

请生成一个JSON格式的游戏流程，包含以下内容：
1. phases: 游戏阶段列表，每个阶段包含：
   - name: 阶段名称
   - description: 阶段描述
   - allowed_actions: 允许的行动列表
   - npc_order: NPC行动顺序（角色名称列表）
   - objectives: 阶段目标列表

请确保：
- 最后一个阶段必须是投票指认阶段（名称包含"投票"二字）
- 阶段数量合理（通常3-5个阶段）
- 每个阶段都有明确的任务
- NPC行动顺序合理
- 允许的行动符合剧本杀玩法

请直接输出JSON，不要有其他内容。"""

        response = self.llm.invoke([
            SystemMessage(content=GAME_MASTER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content = response.content

        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            flow = json.loads(content.strip())

            if "phases" in flow:
                phases = []
                for i, phase_data in enumerate(flow["phases"]):
                    phase = Phase(
                        id=f"phase_{i}",
                        name=phase_data.get("name", f"阶段{i+1}"),
                        description=phase_data.get("description", ""),
                        allowed_actions=phase_data.get("allowed_actions", ["talk", "search"]),
                        npc_order=phase_data.get("npc_order", list(self.character_scripts.keys())),
                        objectives=phase_data.get("objectives", []),
                    )
                    phases.append(phase)

                from annie.world_engine.game_master.phase_controller import PhaseController
                self.game_master._phase_controller = PhaseController(phases)

                if self.game_master._phase_controller.get_current_phase():
                    self.game_master._phase_controller.get_current_phase().status = "active"

                logger.info(f"Generated {len(phases)} game phases")

            return flow

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse game flow JSON: {e}")
            return self._create_default_flow()

    def _create_default_flow(self) -> dict[str, Any]:
        """Create a default game flow if LLM generation fails."""
        npc_names = list(self.character_scripts.keys())

        default_flow = {
            "phases": [
                {
                    "name": "第一幕：开场介绍",
                    "description": "故事开始，各角色登场自我介绍",
                    "allowed_actions": ["talk", "observe"],
                    "npc_order": npc_names,
                    "objectives": ["了解背景", "认识其他角色"],
                },
                {
                    "name": "第二幕：自由调查",
                    "description": "深入调查，收集线索，互相质疑",
                    "allowed_actions": ["talk", "search", "investigate", "deduce"],
                    "npc_order": npc_names,
                    "objectives": ["收集线索", "推理分析"],
                },
                {
                    "name": "第三幕：投票指认",
                    "description": "根据调查结果投票指认凶手",
                    "allowed_actions": ["talk", "accuse", "vote"],
                    "npc_order": npc_names,
                    "objectives": ["指认凶手", "投票表决"],
                },
            ]
        }

        # Also set up phases in game master
        phases = []
        for i, phase_data in enumerate(default_flow["phases"]):
            phase = Phase(
                id=f"phase_{i}",
                name=phase_data["name"],
                description=phase_data["description"],
                allowed_actions=phase_data["allowed_actions"],
                npc_order=phase_data["npc_order"],
                objectives=phase_data["objectives"],
            )
            phases.append(phase)

        from annie.world_engine.game_master.phase_controller import PhaseController
        self.game_master._phase_controller = PhaseController(phases)
        if self.game_master._phase_controller.get_current_phase():
            self.game_master._phase_controller.get_current_phase().status = "active"

        return default_flow

    # ── NPC Initialization ────────────────────────────────────────────

    def initialize_npcs(self) -> None:
        """Initialize all NPCs from character scripts."""
        logger.info("Initializing NPCs...")

        for char_name, script_content in self.character_scripts.items():
            logger.info(f"Initializing NPC: {char_name}")

            script_summary = self.character_summaries.get(char_name, "")
            profile = self._extract_npc_profile(char_name, script_content, script_summary)
            self._validate_profile(char_name, profile)
            self.npc_profiles[char_name] = profile

            self.social_graph.add_npc(char_name)
            for rel in profile.relationships:
                self.social_graph.add_npc(rel.target)
                # Add directed edge so graph has real data from the start
                edge = SocialRelationshipEdge(
                    source=char_name,
                    target=rel.target,
                    type=rel.type,
                    intensity=rel.intensity,
                    trust=0.5,
                    familiarity=rel.intensity,
                    emotional_valence=0.0,
                )
                self.social_graph.set_edge(edge)

            try:
                profile_path = Path(f"data/npcs/{char_name}/profile.yaml")
                profile_path.parent.mkdir(parents=True, exist_ok=True)

                import yaml
                with open(profile_path, "w", encoding="utf-8") as f:
                    yaml.dump({"npc": profile.model_dump()}, f, allow_unicode=True)

                npc = NPCAgent(
                    profile_path,
                    chroma_client=self._chroma_client,
                    social_graph=self.social_graph,
                    event_log=self.event_log,
                )
                self.npcs[char_name] = npc

                # Set script summary on the executor (always available, not just voting)
                if script_summary:
                    npc._executor.set_script_summary(script_summary)
                    npc._script_summary = script_summary

                logger.info(f"Successfully initialized NPC: {char_name}")

            except Exception as e:
                logger.error(f"Failed to initialize NPC {char_name}: {e}")

        # Propagate full NPC name list to all executors
        all_names = list(self.npcs.keys())
        for npc in self.npcs.values():
            npc._executor._all_npc_names = all_names

        if self.npcs:
            self.game_master._npc_names = all_names
            from annie.world_engine.game_master.turn_manager import TurnManager
            self.game_master._turn_manager = TurnManager(all_names)

    def _extract_npc_profile(self, name: str, script: str, script_summary: str = "") -> NPCProfile:
        """Extract NPC profile from character script summary.

        Prefers parsing the summary JSON directly; falls back to LLM extraction.
        """
        # Try to parse directly from summary JSON (skip extra LLM call)
        if script_summary:
            try:
                info = json.loads(script_summary)
                return self._build_profile_from_info(name, info)
            except (json.JSONDecodeError, KeyError):
                logger.info(f"Could not parse summary JSON for {name}, using LLM extraction")

        # Fallback: LLM extraction from raw script
        prompt = f"""从以下人物剧本中提取角色信息：

角色名：{name}
剧本内容：
{script[:3000]}

请提取以下信息并以JSON格式输出：
{{
    "identity": "角色身份",
    "background": "背景故事（100-200字）",
    "personality_traits": ["性格特点1", "性格特点2"],
    "values": ["价值观1", "价值观2"],
    "goals": ["目标1", "目标2"],
    "secrets": ["秘密1"],
    "relationships": {{"其他角色名": "关系类型"}},
    "past_events": ["过去发生的事件"],
    "murderer": true或false
}}

请直接输出JSON，不要有其他内容。"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content

            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            info = json.loads(content.strip())
            return self._build_profile_from_info(name, info)

        except Exception as e:
            logger.error(f"Failed to extract NPC profile for {name}: {e}")
            return NPCProfile(
                name=name,
                personality=Personality(traits=["神秘"]),
                background=Background(biography=script[:200]),
                goals=Goals(),
                relationships=[],
                memory_seed=[],
                tools=["image_reader"],
                skills=[],
            )

    def _build_profile_from_info(self, name: str, info: dict) -> NPCProfile:
        """Build NPCProfile from a parsed info dict."""
        # Handle both field naming conventions
        traits = info.get("personality_traits", info.get("traits", []))
        if not traits:
            traits = ["神秘"]

        values = info.get("values", [])
        biography = info.get("background", info.get("biography", ""))
        if info.get("identity"):
            biography = f"身份: {info['identity']}。{biography}"

        goals = info.get("goals", [])
        secrets = info.get("secrets", [])
        past_events = info.get("past_events", [])

        # Build relationship list
        relationships = []
        raw_rels = info.get("relationships", {})
        if isinstance(raw_rels, dict):
            for target, rel_type in raw_rels.items():
                relationships.append(
                    RelationshipDef(target=target, type=str(rel_type), intensity=0.5)
                )

        # Memory seeds = secrets + key_info
        memory_seed = list(secrets)
        for ki in info.get("key_info", []):
            if ki not in memory_seed:
                memory_seed.append(ki)

        return NPCProfile(
            name=name,
            personality=Personality(traits=traits, values=values),
            background=Background(biography=biography, past_events=past_events),
            goals=Goals(
                short_term=goals[:2],
                long_term=goals[2:],
            ),
            relationships=relationships,
            memory_seed=memory_seed,
            tools=["image_reader"],
            skills=[],
        )

    def _validate_profile(self, name: str, profile: NPCProfile) -> None:
        """Validate that a profile has minimum required fields."""
        issues = []
        if not profile.personality.traits or profile.personality.traits == ["神秘"]:
            issues.append("traits为空或默认")
        if not profile.background.biography:
            issues.append("biography为空")
        if not profile.goals.short_term and not profile.goals.long_term:
            issues.append("goals为空")
        if not profile.memory_seed:
            issues.append("memory_seed为空（无秘密/关键信息）")

        if issues:
            logger.warning(f"Profile for {name} has issues: {', '.join(issues)}")

    # ── Game Control ──────────────────────────────────────────────────

    def start_game(self) -> None:
        """Start the game."""
        self._game_started = True
        self._start_time = datetime.now(UTC)
        self.game_master.start_game()
        logger.info("Game started")

    def is_game_over(self) -> bool:
        """Check if the game is over."""
        return self.game_master.is_game_over()

    def get_current_phase(self) -> Phase | None:
        """Get the current game phase."""
        return self.game_master.get_current_phase()

    def get_npc_order(self) -> list[str]:
        """Get the NPC action order for current phase."""
        return self.game_master.get_npc_order()

    def should_advance_phase(self) -> bool:
        """Check if should advance to next phase."""
        return self.game_master.should_advance_phase()

    def advance_phase(self) -> bool:
        """Advance to next phase."""
        advanced = self.game_master.advance_phase()
        if advanced:
            # Reset turn manager for new phase
            self.game_master._turn_manager.reset()
        return advanced

    def announce_phase(self, phase: Phase) -> str:
        """Generate announcement for the current phase using LLM."""
        # Include summary of previous phase dialogue
        prev_dialogue = ""
        if self.dialogue_history:
            recent = self.dialogue_history[-6:]
            prev_dialogue = "\n".join([
                f"{d['npc']}说: {d['spoken_words'][:100]}"
                for d in recent if d.get("spoken_words")
            ])

        prompt = f"""当前进入新的阶段：

阶段名称：{phase.name}
阶段描述：{phase.description}
阶段目标：{', '.join(phase.objectives) if phase.objectives else '无特定目标'}
允许的行动：{', '.join(phase.allowed_actions)}

{"之前的对话摘要：" + prev_dialogue if prev_dialogue else "这是游戏的第一个阶段。"}

请生成一段主持人引导语（100-200字），介绍当前阶段并引导角色开始行动。
要求：语言生动有感染力，不要透露关键剧情，鼓励角色积极参与。"""

        response = self.llm.invoke([
            SystemMessage(content=GAME_MASTER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        return response.content

    def build_npc_context(self, npc_name: str) -> str:
        """Build context for an NPC's turn, including dialogue history."""
        context_parts = []

        current_phase = self.get_current_phase()
        if current_phase:
            context_parts.append(f"当前阶段：{current_phase.name}")
            context_parts.append(f"阶段描述：{current_phase.description}")

        if self.background:
            context_parts.append(f"\n背景故事：\n{self.background[:500]}")

        script_summary = self.character_summaries.get(npc_name, "")
        if script_summary:
            context_parts.append(f"\n你的剧本梗概：\n{script_summary}")

        # Add dialogue history from current phase
        if self.dialogue_history and current_phase:
            phase_dialogues = [
                d for d in self.dialogue_history
                if d.get("phase") == current_phase.name and d.get("spoken_words")
            ]
            if phase_dialogues:
                dialogue_text = "\n".join([
                    f"{d['npc']}说: {d['spoken_words'][:200]}"
                    for d in phase_dialogues[-12:]
                ])
                context_parts.append(f"\n之前的对话记录：\n{dialogue_text}")

        # Add newly revealed clues from this search round (full content)
        if self._last_revealed_clues:
            clue_texts = [
                f"- 【{c.category}】{c.file_name}: {c.content}"
                for c in self._last_revealed_clues
            ]
            context_parts.append(
                f"\n本轮搜证结果（公开线索）：\n" + "\n".join(clue_texts)
            )
        elif self.clue_manager.get_discovered_clues():
            # Non-search rounds: include previously discovered clues as summary
            discovered = self.clue_manager.get_discovered_clues()
            clue_texts = [f"- 【{c.category}】{c.content[:80]}" for c in discovered[:8]]
            context_parts.append(f"\n已知线索：\n" + "\n".join(clue_texts))

        # List other characters
        other_npcs = [n for n in self.npcs.keys() if n != npc_name]
        if other_npcs:
            context_parts.append(f"\n在场的其他角色：{'、'.join(other_npcs)}")

        return "\n".join(context_parts)

    def process_npc_action(self, npc_name: str, action_result: dict) -> None:
        """Process an NPC's action result."""
        self.game_master.execute_action(npc_name, action_result)
        # Clue discovery is handled explicitly by _reveal_search_batch(), not string matching.

    # ── Live Streaming Helpers ────────────────────────────────────────

    def get_initial_state(self) -> dict:
        """Return serializable initial game state for the SSE game_ready event.

        Secrets and murderer flag are intentionally omitted to avoid spoiling the game.
        """
        characters = []
        for name, summary_str in self.character_summaries.items():
            try:
                info = json.loads(summary_str)
            except (json.JSONDecodeError, ValueError):
                info = {}
            characters.append({
                "name": name,
                "identity": info.get("identity", ""),
                "background": info.get("background", ""),
                "personality_traits": info.get("personality_traits", []),
                "values": info.get("values", []),
                "goals": info.get("goals", []),
                "secrets": [],
                "relationships": info.get("relationships", {}),
                "is_murderer": False,
                "color": "",
            })

        phases = []
        for phase in self.game_master._phase_controller.get_all_phases():
            phases.append({
                "id": getattr(phase, "id", phase.name),
                "name": phase.name,
                "description": phase.description,
                "allowed_actions": getattr(phase, "allowed_actions", []),
                "npc_order": getattr(phase, "npc_order", []),
                "objectives": getattr(phase, "objectives", []),
                "status": "upcoming",
            })

        clues = []
        for clue in self.clue_manager.clues.values():
            clues.append({
                "id": clue.id,
                "category": clue.category,
                "file_name": clue.file_name,
                "content": clue.content,
                "discovered": clue.discovered,
                "discovered_by": clue.discovered_by,
                "discovered_at_turn": None,  # not yet tracked as turn index
                "importance": getattr(clue, "importance", 1),
            })

        return {
            "characters": characters,
            "phases": phases,
            "clues": clues,
            "social_graph": self._get_social_graph_data(),
        }

    def _get_social_graph_data(self) -> dict:
        """Serialize social graph in frontend-compatible format."""
        raw = self.social_graph.to_dict()
        return {
            "nodes": [{"id": n, "label": n} for n in raw.get("nodes", [])],
            "edges": [
                {
                    "source": e["source"],
                    "target": e["target"],
                    "trust": e.get("trust", 0.5),
                    "familiarity": e.get("familiarity", 0.5),
                    "emotional_valence": e.get("emotional_valence", 0.0),
                    "type": e.get("type", "unknown"),
                    "status": e.get("status", "active"),
                }
                for e in raw.get("edges", [])
            ],
        }

    def _reveal_search_batch(
        self,
        turn_index: int,
        event_callback: Callable[[dict], None] | None = None,
    ) -> list[Clue]:
        """Reveal next batch of search clues. Returns the newly revealed clues."""
        if self._search_batch_revealed >= len(self._search_batches):
            return []

        batch_ids = self._search_batches[self._search_batch_revealed]
        self._search_batch_revealed += 1
        revealed: list[Clue] = []

        for clue_id in batch_ids:
            if self.clue_manager.reveal_clue(clue_id, "搜证", turn_index=turn_index):
                clue = self.clue_manager.get_clue(clue_id)
                if clue:
                    revealed.append(clue)
                    if event_callback:
                        event_callback({
                            "type": "clue_discovered",
                            "clue": {
                                "id": clue.id,
                                "category": clue.category,
                                "file_name": clue.file_name,
                                "content": clue.content,
                                "discovered": True,
                                "discovered_by": "搜证",
                                "discovered_at_turn": turn_index,
                                "importance": clue.importance,
                            },
                        })

        self._last_revealed_clues = revealed
        logger.info(
            f"Search batch {self._search_batch_revealed} revealed: "
            f"{len(revealed)} clues"
        )
        return revealed

    # ── Main Game Loop ────────────────────────────────────────────────

    def run_game_loop(
        self,
        max_rounds: int = 2,
        event_callback: Callable[[dict], None] | None = None,
    ) -> None:
        """Run the main game loop.

        Args:
            max_rounds: Maximum number of rounds to run per phase.
            event_callback: Optional callback invoked with game events for live streaming.
                Signature: ``callback(event: dict) -> None``.
                Events: npc_thinking, dialogue, phase_change, game_over.
        """
        all_votes: dict[str, str] = {}

        while not self.is_game_over():
            phase = self.get_current_phase()
            if not phase:
                print(f"\n{DIM}[系统] 没有当前阶段，游戏结束{RESET}")
                break

            print(f"\n{'='*70}")
            print(f"  {BOLD}{phase.name}{RESET}")
            print(f"{'='*70}")

            announcement = self.announce_phase(phase)
            print(f"\n{CYAN}[主持人]{RESET} {announcement}\n")

            if event_callback:
                event_callback({
                    "type": "phase_change",
                    "phase_name": phase.name,
                    "phase_description": phase.description,
                    "announcement": announcement,
                })

            phase_rounds = 0
            is_voting_phase = "投票" in phase.name or "真相" in phase.name or "指认" in phase.name
            is_search_phase = (
                "search" in phase.allowed_actions
                or "investigate" in phase.allowed_actions
                or "搜证" in phase.name
                or "调查" in phase.name
            )
            # Clear last revealed clues at the start of each phase
            self._last_revealed_clues = []

            while phase_rounds < max_rounds and not self.is_game_over():
                print(f"\n{DIM}--- 第 {phase_rounds + 1} 轮 ---{RESET}")

                # In search phases, reveal the next clue batch at the start of each round
                current_turn = len(self.dialogue_history)
                if is_search_phase and self._search_batch_revealed < len(self._search_batches):
                    revealed = self._reveal_search_batch(current_turn, event_callback)
                    if revealed:
                        batch_num = self._search_batch_revealed
                        summary = "、".join(
                            f"【{c.category}】{c.file_name}" for c in revealed[:5]
                        )
                        if len(revealed) > 5:
                            summary += f" 等{len(revealed)}条线索"
                        print(f"\n{GREEN}[搜证]{RESET} 第{batch_num}轮搜证完成，发现：{summary}")
                        if event_callback:
                            event_callback({
                                "type": "phase_change",
                                "phase_name": phase.name,
                                "phase_description": (
                                    f"第{batch_num}轮搜证结束，共发现{len(revealed)}条线索。"
                                ),
                                "announcement": (
                                    f"搜证完成！本轮共发现{len(revealed)}条线索：{summary}。"
                                    f"请各位根据线索进行分析讨论。"
                                ),
                            })

                npc_order = self.get_npc_order()
                for npc_name in npc_order:
                    if npc_name not in self.npcs:
                        continue

                    print(f"\n{CYAN}{'─'*50}{RESET}")
                    print(f"{CYAN}  {npc_name} 的回合{RESET}")
                    print(f"{CYAN}{'─'*50}{RESET}")

                    try:
                        context = self.build_npc_context(npc_name)

                        npc = self.npcs[npc_name]
                        script_summary = getattr(npc, '_script_summary', "")

                        npc._executor.set_voting_phase(is_voting_phase, script_summary)

                        if event_callback:
                            event_callback({
                                "type": "npc_thinking",
                                "npc": npc_name,
                                "phase": phase.name,
                                "round": phase_rounds + 1,
                            })

                        result = npc.run(context)

                        if result.execution_results:
                            exec_result = result.execution_results[0]
                            inner_thoughts = exec_result.get("inner_thoughts", "")
                            spoken_words = exec_result.get("spoken_words", "")
                            vote = exec_result.get("vote", "")

                            if inner_thoughts:
                                print(f"\n{DIM}【内心活动】{RESET}")
                                print(f"{DIM}{inner_thoughts}{RESET}")

                            if spoken_words:
                                print(f"\n{BOLD}【说的话】{RESET}")
                                print(f"{spoken_words}")

                            if vote:
                                all_votes[npc_name] = vote
                                print(f"\n{YELLOW}{BOLD}【投票】{vote}{RESET}")

                            turn_index = len(self.dialogue_history)
                            # Record to dialogue history
                            self.dialogue_history.append({
                                "npc": npc_name,
                                "inner_thoughts": inner_thoughts,
                                "spoken_words": spoken_words,
                                "vote": vote,
                                "phase": phase.name,
                            })

                            if event_callback:
                                event_callback({
                                    "type": "dialogue",
                                    "turn_index": turn_index,
                                    "npc": npc_name,
                                    "inner_thoughts": inner_thoughts,
                                    "spoken_words": spoken_words,
                                    "vote": vote or None,
                                    "phase": phase.name,
                                })

                            # Emit social graph snapshot after each NPC turn
                            snapshot = {
                                "turn_index": turn_index,
                                "phase": phase.name,
                                "graph": self._get_social_graph_data(),
                            }
                            self._graph_snapshots.append(snapshot)
                            if event_callback:
                                event_callback({
                                    "type": "social_graph_snapshot",
                                    **snapshot,
                                })

                        self.process_npc_action(npc_name, {
                            "action": result.execution_results,
                            "reflection": result.reflection,
                        })

                    except Exception as e:
                        logger.error(f"Error in NPC {npc_name} action: {e}")
                        print(f"  {RED}[错误] {e}{RESET}")

                # After all NPCs in a search round have acted, clear "just revealed" clues
                # so they don't keep showing as "新线索" in subsequent rounds
                if is_search_phase:
                    self._last_revealed_clues = []

                phase_rounds += 1

                if self.should_advance_phase():
                    break

            # Advance to next phase
            advanced = self.advance_phase()
            if not advanced:
                print(f"\n{DIM}[系统] 已到达最后阶段{RESET}")
                break

        print(f"\n{'='*70}")
        print(f"  {BOLD}游戏结束{RESET}")
        print(f"{'='*70}\n")

        final_results = self._announce_final_results(all_votes)
        self._final_results = final_results

        if event_callback:
            event_callback({
                "type": "game_over",
                "vote_results": {
                    "votes": final_results["votes"],
                    "counts": final_results["counts"],
                    "top_suspect": final_results["top_suspect"],
                    "real_murderer": final_results["real_murderer"],
                    "is_correct": final_results["is_correct"],
                },
                "truth_reveal": {
                    "real_murderer": final_results["real_murderer"],
                    "murder_method": "",
                    "narration": final_results["narration"],
                    "is_correct": final_results["is_correct"],
                },
            })

    # ── Final Results ─────────────────────────────────────────────────

    def _find_real_murderer(self) -> str:
        """Find the real murderer from character summaries."""
        for char_name, summary in self.character_summaries.items():
            try:
                info = json.loads(summary)
                if info.get("murderer") is True:
                    return char_name
            except (json.JSONDecodeError, KeyError):
                # Try searching for keywords in the summary text
                if "凶手" in summary and "true" in summary.lower():
                    return char_name
        return "未知"

    def _announce_final_results(self, votes: dict[str, str]) -> dict:
        """Announce final results with deterministic vote counting + LLM narration.

        Returns:
            dict with keys: votes, counts, top_suspect, real_murderer, is_correct, narration
        """

        # Step 1: Deterministic vote counting
        print(f"\n{BOLD}{'─'*50}{RESET}")
        print(f"{BOLD}  投票统计{RESET}")
        print(f"{'─'*50}")

        if votes:
            vote_counts = Counter(votes.values())
            for voter, target in votes.items():
                print(f"  {voter} → {target}")

            print(f"\n  {BOLD}票数统计:{RESET}")
            for suspect, count in vote_counts.most_common():
                bar = "█" * count
                print(f"  {suspect}: {bar} ({count}票)")

            # Determine who got most votes
            max_votes = vote_counts.most_common(1)[0][1]
            top_suspects = [name for name, count in vote_counts.items() if count == max_votes]
            voted_murderer = top_suspects[0]

            print(f"\n  {YELLOW}被指认的嫌疑人: {voted_murderer} ({max_votes}票){RESET}")
        else:
            vote_counts = Counter()
            voted_murderer = "无人被投票"
            print(f"  {RED}没有人进行投票{RESET}")

        # Step 2: Find real murderer
        real_murderer = self._find_real_murderer()
        is_correct = voted_murderer == real_murderer

        # Step 3: LLM narration for dramatic reveal
        vote_summary = "\n".join([f"  - {npc} 投票给: {target}" for npc, target in votes.items()])

        dialogue_summary = ""
        for d in self.dialogue_history[-12:]:
            if d.get("spoken_words"):
                dialogue_summary += f"\n{d['npc']}: {d['spoken_words'][:150]}"

        prompt = f"""游戏刚刚结束，请你以主持人的身份公布最终结果。

投票结果：
{vote_summary if vote_summary else "没有人投票"}

被投票最多的嫌疑人：{voted_murderer}（{Counter(votes.values()).get(voted_murderer, 0)}票）
真正的凶手是：{real_murderer}
投票结果{"正确！玩家们成功找出了凶手！" if is_correct else "错误。真正的凶手逃脱了法律的制裁。"}

最近的对话记录：
{dialogue_summary if dialogue_summary else "无对话记录"}

真相参考（用于你的叙述）：
{self.truth[:1500]}

请以主持人的身份，用生动有趣的语言公布最终结果。要求：
1. 先公布投票结果和被指认的嫌疑人
2. 制造一点悬念，然后揭示真正的凶手
3. 简要说明作案手法和动机
4. 如果投票正确，祝贺大家；如果错误，解释为什么会被误导
5. 用300-500字完成叙述"""

        narration = ""
        try:
            response = self.llm.invoke([
                SystemMessage(content=GAME_MASTER_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            narration = response.content

            print(f"\n{'='*50}")
            print(f"{BOLD}{CYAN}  [主持人] 真相揭晓{RESET}")
            print(f"{'='*50}")
            print(f"\n{narration}")

        except Exception as e:
            logger.error(f"Failed to announce results: {e}")
            # Deterministic fallback
            narration = f"投票结果: {voted_murderer}。真正的凶手: {real_murderer}。"
            if is_correct:
                narration += "恭喜！投票正确！"
            else:
                narration += f"很遗憾，投票错误。真凶是{real_murderer}。"
            print(f"\n{BOLD}[主持人] 真相揭晓{RESET}")
            print(f"\n{narration}")

        # Print final verdict
        print(f"\n{'─'*50}")
        if is_correct:
            print(f"{GREEN}{BOLD}  结局: 正义获胜！凶手 {real_murderer} 被成功指认！{RESET}")
        else:
            print(f"{RED}{BOLD}  结局: 凶手 {real_murderer} 逃脱了！被冤枉的是 {voted_murderer}。{RESET}")
        print(f"{'─'*50}")

        return {
            "votes": votes,
            "counts": dict(vote_counts),
            "top_suspect": voted_murderer,
            "real_murderer": real_murderer,
            "is_correct": is_correct,
            "narration": narration,
        }

    def reveal_truth(self) -> str:
        """Reveal the truth through LLM narration."""
        if not self.truth:
            return "真相文件缺失。"

        try:
            response = self.llm.invoke([
                SystemMessage(content=GAME_MASTER_SYSTEM_PROMPT),
                HumanMessage(content=f"请以主持人的身份，用200-300字生动地揭示以下真相：\n\n{self.truth[:2000]}"),
            ])
            return response.content
        except Exception:
            return self.truth

    def save_session(self, save_path: str | Path, game_id: str = "") -> Path:
        """Save the complete game session to a JSON file for replay.

        Args:
            save_path: Directory to save the session file.
            game_id: Optional game ID to embed in the filename.

        Returns:
            Path to the saved file.
        """
        save_dir = Path(save_path)
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"session_{timestamp}_{game_id}.json" if game_id else f"session_{timestamp}.json"
        filepath = save_dir / filename

        initial_state = self.get_initial_state()

        # Build full clue list with discovered state
        clues = []
        for clue in self.clue_manager.clues.values():
            clues.append({
                "id": clue.id,
                "category": clue.category,
                "file_name": clue.file_name,
                "content": clue.content,
                "discovered": clue.discovered,
                "discovered_by": clue.discovered_by,
                "discovered_at_turn": clue.discovered_at_turn,
                "importance": clue.importance,
            })

        # Build dialogue list with turn indices
        dialogue = []
        for i, d in enumerate(self.dialogue_history):
            dialogue.append({
                "turn_index": i,
                "npc": d.get("npc", ""),
                "inner_thoughts": d.get("inner_thoughts", ""),
                "spoken_words": d.get("spoken_words", ""),
                "vote": d.get("vote") or None,
                "phase": d.get("phase", ""),
                "timestamp": 0,
            })

        fr = self._final_results or {}
        session_data = {
            "metadata": {
                "game_id": game_id,
                "game_name": "午夜列车",
                "game_name_en": "Midnight Train",
                "total_turns": len(self.dialogue_history),
                "total_phases": len(self.game_master._phase_controller.get_all_phases()),
                "npc_count": len(self.npcs),
                "created_at": datetime.now(UTC).isoformat(),
            },
            "characters": initial_state["characters"],
            "phases": initial_state["phases"],
            "dialogue": dialogue,
            "social_graph_snapshots": self._graph_snapshots,
            "clues": clues,
            "vote_results": {
                "votes": fr.get("votes", {}),
                "counts": fr.get("counts", {}),
                "top_suspect": fr.get("top_suspect", ""),
                "real_murderer": fr.get("real_murderer", ""),
                "is_correct": fr.get("is_correct", False),
            },
            "truth_reveal": {
                "real_murderer": fr.get("real_murderer", ""),
                "murder_method": "",
                "narration": fr.get("narration", ""),
                "is_correct": fr.get("is_correct", False),
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Session saved to {filepath}")
        return filepath
