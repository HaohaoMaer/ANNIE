"""Data models for script parsing.

Defines the structure of parsed script data including characters,
phases, events, clues, and endings.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field


class CharacterInfo(BaseModel):
    """Information about a single character in the script."""

    name: str
    biography: str = ""
    personality: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    relationships: dict[str, str] = Field(default_factory=dict)
    visible_sections: list[str] = Field(default_factory=list)
    script_pages: list[int] = Field(default_factory=list)
    initial_location: str = ""


class Phase(BaseModel):
    """A game phase with specific rules and allowed actions."""

    name: str
    description: str = ""
    allowed_actions: list[str] = Field(default_factory=list)
    duration: timedelta | None = None
    npc_order: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)


class PlotPoint(BaseModel):
    """A key plot point in the story."""

    id: str
    name: str
    description: str = ""
    trigger_conditions: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    required_items: list[str] = Field(default_factory=list)
    required_knowledge: list[str] = Field(default_factory=list)
    phase: str = ""
    optional: bool = False


class ScriptedEvent(BaseModel):
    """A scripted event that occurs during the game."""

    id: str
    name: str
    description: str = ""
    trigger_time: datetime | None = None
    trigger_condition: str = ""
    content: str = ""
    affected_npcs: list[str] = Field(default_factory=list)
    visibility: str = "public"
    phase: str = ""


class Clue(BaseModel):
    """A clue that can be discovered by NPCs."""

    id: str
    name: str
    description: str = ""
    location: str = ""
    item_id: str = ""
    discoverable_by: list[str] = Field(default_factory=list)
    related_to: list[str] = Field(default_factory=list)
    importance: int = 1
    discovered: bool = False


class Ending(BaseModel):
    """A possible ending for the script."""

    id: str
    name: str
    description: str = ""
    conditions: list[str] = Field(default_factory=list)
    required_clues: list[str] = Field(default_factory=list)
    required_decisions: list[str] = Field(default_factory=list)


class Location(BaseModel):
    """A location in the script world."""

    name: str
    description: str = ""
    items: list[str] = Field(default_factory=list)
    npcs_present: list[str] = Field(default_factory=list)
    connections: list[str] = Field(default_factory=list)
    visibility: str = "public"


class Item(BaseModel):
    """An item in the script world."""

    id: str
    name: str
    description: str = ""
    location: str = ""
    holder: str = ""
    clues: list[str] = Field(default_factory=list)
    inspectable: bool = True
    takeable: bool = False


class ParsedScript(BaseModel):
    """Complete parsed script data."""

    title: str = ""
    author: str = ""
    description: str = ""
    player_count: int = 0
    estimated_duration: timedelta | None = None

    characters: list[CharacterInfo] = Field(default_factory=list)
    phases: list[Phase] = Field(default_factory=list)
    plot_points: list[PlotPoint] = Field(default_factory=list)
    events: list[ScriptedEvent] = Field(default_factory=list)
    clues: list[Clue] = Field(default_factory=list)
    endings: list[Ending] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)

    background_story: str = ""
    rules: list[str] = Field(default_factory=list)
    shared_knowledge: list[str] = Field(default_factory=list)

    raw_content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get_character(self, name: str) -> CharacterInfo | None:
        """Get a character by name."""
        for char in self.characters:
            if char.name == name:
                return char
        return None

    def get_phase(self, name: str) -> Phase | None:
        """Get a phase by name."""
        for phase in self.phases:
            if phase.name == name:
                return phase
        return None

    def get_clue(self, clue_id: str) -> Clue | None:
        """Get a clue by ID."""
        for clue in self.clues:
            if clue.id == clue_id:
                return clue
        return None

    def get_location(self, name: str) -> Location | None:
        """Get a location by name."""
        for loc in self.locations:
            if loc.name == name:
                return loc
        return None
