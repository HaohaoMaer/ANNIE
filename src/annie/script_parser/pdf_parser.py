"""PDF Parser for script files.

Extracts text content from PDF scripts and identifies sections.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from annie.script_parser.models import (
    CharacterInfo,
    Clue,
    Ending,
    Location,
    ParsedScript,
    Phase,
    PlotPoint,
    ScriptedEvent,
)


class ScriptPDFParser:
    """Parser for murder mystery script PDFs."""

    def __init__(self, pdf_path: str | Path) -> None:
        self.pdf_path = Path(pdf_path)
        self._raw_text: str = ""
        self._sections: dict[str, str] = {}

    def parse(self) -> ParsedScript:
        """Parse the PDF and return structured script data."""
        self._raw_text = self._extract_text()
        self._sections = self._identify_sections()

        script = ParsedScript(
            title=self._extract_title(),
            description=self._extract_description(),
            background_story=self._extract_background(),
            characters=self._extract_characters(),
            phases=self._extract_phases(),
            plot_points=self._extract_plot_points(),
            events=self._extract_events(),
            clues=self._extract_clues(),
            endings=self._extract_endings(),
            locations=self._extract_locations(),
            shared_knowledge=self._extract_shared_knowledge(),
            raw_content=self._raw_text,
            metadata=self._extract_metadata(),
        )

        script.player_count = len(script.characters)
        return script

    def _extract_text(self) -> str:
        """Extract all text from the PDF."""
        reader = PdfReader(self.pdf_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n\n".join(pages)

    def _identify_sections(self) -> dict[str, str]:
        """Identify and extract major sections from the text."""
        sections = {}

        section_patterns = [
            (r"背景[故事介绍]*(.*?)(?=人物|角色|第一幕|第一章|$)", "background"),
            (r"人物[介绍简介]*(.*?)(?=剧本|第一幕|第一章|剧情|线索|$)", "characters_intro"),
            (r"剧本[内容]*(.*?)(?=线索|结局|规则|$)", "script_content"),
            (r"线索[清单]*(.*?)(?=结局|规则|$)", "clues"),
            (r"规则[说明]*(.*?)(?=结局|$)", "rules"),
            (r"结局[分支]*(.*?)$", "endings"),
        ]

        for pattern, section_name in section_patterns:
            match = re.search(pattern, self._raw_text, re.DOTALL | re.IGNORECASE)
            if match:
                sections[section_name] = match.group(1).strip()

        return sections

    def _extract_title(self) -> str:
        """Extract script title."""
        patterns = [
            r"剧本[名称]*[：:]\s*(.+?)(?:\n|$)",
            r"^(.+?)(?:\n|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, self._raw_text, re.MULTILINE)
            if match:
                title = match.group(1).strip()
                if len(title) < 50:
                    return title

        return self.pdf_path.stem

    def _extract_description(self) -> str:
        """Extract script description."""
        if "background" in self._sections:
            lines = self._sections["background"].split("\n")[:3]
            return " ".join(lines).strip()
        return ""

    def _extract_background(self) -> str:
        """Extract background story."""
        return self._sections.get("background", "")

    def _extract_characters(self) -> list[CharacterInfo]:
        """Extract character information."""
        characters = []
        char_section = self._sections.get("characters_intro", "")
        if not char_section:
            char_section = self._raw_text

        char_pattern = r"([^\n]{2,10})[：:]\s*([^角色人物]+?)(?=[^\n]{2,10}[：:]|$)"
        matches = re.finditer(char_pattern, char_section, re.DOTALL)

        for i, match in enumerate(matches):
            name = match.group(1).strip()
            description = match.group(2).strip()

            if self._is_valid_character_name(name):
                char = self._parse_character_info(name, description, i)
                characters.append(char)

        if not characters:
            characters = self._extract_characters_by_format()

        return characters

    def _extract_characters_by_format(self) -> list[CharacterInfo]:
        """Alternative character extraction for different formats."""
        characters = []
        patterns = [
            r"角色[一二三四五六七八九十\d]*[：:]\s*([^\n]+)",
            r"人物[一二三四五六七八九十\d]*[：:]\s*([^\n]+)",
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, self._raw_text, re.MULTILINE)
            for i, match in enumerate(matches):
                name_line = match.group(1).strip()
                name = name_line.split("：")[0].split(":")[0].strip()

                if self._is_valid_character_name(name):
                    characters.append(
                        CharacterInfo(
                            name=name,
                            biography=name_line,
                            script_pages=[],
                        )
                    )
        return characters

    def _is_valid_character_name(self, name: str) -> bool:
        """Check if a string is a valid character name."""
        if len(name) < 2 or len(name) > 20:
            return False

        invalid_keywords = [
            "背景", "故事", "介绍", "剧本", "线索", "规则", "结局",
            "第一幕", "第二幕", "第三幕", "第一章", "第二章",
        ]

        name_lower = name.lower()
        for keyword in invalid_keywords:
            if keyword in name_lower:
                return False

        if re.match(r"^[\d\s\-\:：]+$", name):
            return False

        return True

    def _parse_character_info(self, name: str, description: str, index: int) -> CharacterInfo:
        """Parse detailed character information from description."""
        personality = self._extract_personality(description)
        goals = self._extract_goals(description)
        secrets = self._extract_secrets(description)
        relationships = self._extract_relationships(description)

        return CharacterInfo(
            name=name,
            biography=description[:500],
            personality=personality,
            goals=goals,
            secrets=secrets,
            relationships=relationships,
            script_pages=[],
        )

    def _extract_personality(self, text: str) -> list[str]:
        """Extract personality traits from text."""
        traits = []
        trait_keywords = ["性格", "特点", "冷静", "热情", "内向", "外向", "理性", "感性"]

        for keyword in trait_keywords:
            if keyword in text:
                pattern = rf"{keyword}[：:为是]?([^，。！？\n]{{2,10}})"
                match = re.search(pattern, text)
                if match:
                    trait = match.group(1).strip()
                    if trait:
                        traits.append(trait)
        return traits[:5]

    def _extract_goals(self, text: str) -> list[str]:
        """Extract goals from text."""
        goals = []
        goal_patterns = [
            r"目标[：:为]?([^，。！？\n]{5,50})",
            r"任务[：:为]?([^，。！？\n]{5,50})",
        ]

        for pattern in goal_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                goal = match.group(1).strip()
                if goal and goal not in goals:
                    goals.append(goal)
        return goals[:5]

    def _extract_secrets(self, text: str) -> list[str]:
        """Extract secrets from text."""
        secrets = []
        secret_patterns = [
            r"秘密[：:为]?([^，。！？\n]{5,100})",
            r"隐藏[：:为]?([^，。！？\n]{5,100})",
        ]

        for pattern in secret_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                secret = match.group(1).strip()
                if secret and secret not in secrets:
                    secrets.append(secret)
        return secrets[:3]

    def _extract_relationships(self, text: str) -> dict[str, str]:
        """Extract relationships from text."""
        relationships = {}
        rel_pattern = r"与([^\s]{2,10})的关系[：:为]?([^，。！？\n]{2,20})"

        matches = re.finditer(rel_pattern, text)
        for match in matches:
            target = match.group(1).strip()
            relation = match.group(2).strip()
            if target and relation and len(target) < 10:
                relationships[target] = relation
        return relationships

    def _extract_phases(self) -> list[Phase]:
        """Extract game phases."""
        phases = []
        phase_patterns = [
            (r"第[一二三四五六七八九十\d]+幕[：:]?\s*([^\n]+)", "幕"),
            (r"第[一二三四五六七八九十\d]+章[：:]?\s*([^\n]+)", "章"),
        ]

        for pattern, phase_type in phase_patterns:
            matches = re.finditer(pattern, self._raw_text, re.MULTILINE)
            for i, match in enumerate(matches):
                phase_name = match.group(0).strip()
                phase_desc = match.group(1).strip() if match.group(1) else ""

                phases.append(
                    Phase(
                        name=phase_name,
                        description=phase_desc,
                        allowed_actions=["investigate", "talk", "search"],
                        npc_order=[],
                    )
                )

        if not phases:
            phases = [
                Phase(name="第一幕：开场", description="故事开始", allowed_actions=["investigate", "talk"], npc_order=[]),
                Phase(name="第二幕：发展", description="剧情推进", allowed_actions=["investigate", "talk", "search"], npc_order=[]),
                Phase(name="第三幕：高潮", description="真相揭露", allowed_actions=["investigate", "talk", "deduce"], npc_order=[]),
            ]

        return phases

    def _extract_plot_points(self) -> list[PlotPoint]:
        """Extract key plot points."""
        plot_points = []
        event_pattern = r"事件[一二三四五六七八九十\d]*[：:]\s*([^\n]+)"
        matches = re.finditer(event_pattern, self._raw_text, re.MULTILINE)

        for i, match in enumerate(matches):
            event_name = match.group(1).strip()
            plot_points.append(
                PlotPoint(
                    id=f"plot_{i}",
                    name=event_name,
                    description=event_name,
                    trigger_conditions=[],
                    consequences=[],
                )
            )
        return plot_points

    def _extract_events(self) -> list[ScriptedEvent]:
        """Extract scripted events."""
        return []

    def _extract_clues(self) -> list[Clue]:
        """Extract clues from the script."""
        clues = []
        clue_section = self._sections.get("clues", "")
        if not clue_section:
            clue_section = self._raw_text

        clue_pattern = r"线索[一二三四五六七八九十\d]*[：:]\s*([^\n]+)"
        matches = re.finditer(clue_pattern, clue_section, re.MULTILINE)

        for i, match in enumerate(matches):
            clue_desc = match.group(1).strip()
            clues.append(
                Clue(
                    id=f"clue_{i}",
                    name=clue_desc[:30],
                    description=clue_desc,
                    importance=1,
                )
            )
        return clues

    def _extract_endings(self) -> list[Ending]:
        """Extract possible endings."""
        endings = []
        ending_section = self._sections.get("endings", "")
        if not ending_section:
            ending_section = self._raw_text

        ending_pattern = r"结局[一二三四五六七八九十\d]*[：:]\s*([^\n]+)"
        matches = re.finditer(ending_pattern, ending_section, re.MULTILINE)

        for i, match in enumerate(matches):
            ending_name = match.group(1).strip()
            endings.append(
                Ending(
                    id=f"ending_{i}",
                    name=ending_name,
                    description=ending_name,
                    conditions=[],
                )
            )

        if not endings:
            endings.append(
                Ending(
                    id="ending_default",
                    name="标准结局",
                    description="故事按照正常流程结束",
                    conditions=[],
                )
            )

        return endings

    def _extract_locations(self) -> list[Location]:
        """Extract locations from the script."""
        locations = []
        location_keywords = ["房间", "大厅", "花园", "厨房", "书房", "卧室"]

        for keyword in location_keywords:
            if keyword in self._raw_text:
                locations.append(
                    Location(
                        name=keyword,
                        description=f"剧本中的{keyword}",
                        items=[],
                        npcs_present=[],
                        connections=[],
                    )
                )
        return locations

    def _extract_shared_knowledge(self) -> list[str]:
        """Extract knowledge shared by all characters."""
        knowledge = []
        background = self._sections.get("background", "")
        if background:
            paragraphs = background.split("\n\n")
            knowledge.extend([p.strip() for p in paragraphs if len(p.strip()) > 20])
        return knowledge[:10]

    def _extract_metadata(self) -> dict[str, Any]:
        """Extract metadata about the script."""
        metadata = {
            "source_file": str(self.pdf_path),
            "file_size": self.pdf_path.stat().st_size if self.pdf_path.exists() else 0,
        }

        player_pattern = r"(\d+)[人名]"
        match = re.search(player_pattern, self._raw_text)
        if match:
            metadata["suggested_players"] = int(match.group(1))

        return metadata

    def get_character_script(self, character_name: str) -> str:
        """Get the script content visible to a specific character."""
        if not self._raw_text:
            self._raw_text = self._extract_text()

        char_section = self._find_character_section(character_name)
        if char_section:
            return char_section

        return self._sections.get("background", "")

    def _find_character_section(self, character_name: str) -> str:
        """Find the section of text belonging to a character."""
        pattern = rf"{re.escape(character_name)}[^\n]*\n((?:(?!{re.escape(character_name)}|角色|人物|第[一二三四五六七八九十\d]+[幕章节])[^\n]+\n)+)"
        match = re.search(pattern, self._raw_text, re.MULTILINE)

        if match:
            return match.group(1).strip()
        return ""
