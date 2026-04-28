"""World-engine-owned NPC profile loading and prompt rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class Personality(BaseModel):
    traits: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)


class Background(BaseModel):
    biography: str = ""
    past_events: list[str] = Field(default_factory=list)


class Goals(BaseModel):
    short_term: list[str] = Field(default_factory=list)
    long_term: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    target: str
    type: str = ""
    intensity: float | None = None
    description: str = ""


class NPCProfile(BaseModel):
    """Structured NPC definition owned by the World Engine layer."""

    name: str
    personality: Personality = Field(default_factory=Personality)
    background: Background = Field(default_factory=Background)
    goals: Goals = Field(default_factory=Goals)
    relationships: list[Relationship] = Field(default_factory=list)
    memory_seed: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


def load_npc_profile(path: str | Path) -> NPCProfile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"NPC definition file not found: {path}")

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    npc_data: dict[str, Any] = raw.get("npc", raw)
    return NPCProfile(**npc_data)


def profile_to_character_prompt(profile: NPCProfile) -> str:
    parts: list[str] = [f"Name: {profile.name}"]
    if profile.personality.traits:
        parts.append("Traits: " + ", ".join(profile.personality.traits))
    if profile.personality.values:
        parts.append("Values: " + ", ".join(profile.personality.values))
    if profile.background.biography:
        parts.append(f"Biography: {profile.background.biography}")
    if profile.background.past_events:
        parts.append("Past events:\n" + "\n".join(f"- {e}" for e in profile.background.past_events))
    if profile.goals.short_term:
        parts.append("Short-term goals:\n" + "\n".join(f"- {g}" for g in profile.goals.short_term))
    if profile.goals.long_term:
        parts.append("Long-term goals:\n" + "\n".join(f"- {g}" for g in profile.goals.long_term))
    if profile.relationships:
        rel_lines = []
        for rel in profile.relationships:
            detail = rel.description or rel.type or "known relation"
            if rel.intensity is not None:
                detail = f"{detail} (intensity {rel.intensity:g})"
            rel_lines.append(f"- {rel.target}: {detail}")
        parts.append("Relationships:\n" + "\n".join(rel_lines))
    return "\n\n".join(parts)
