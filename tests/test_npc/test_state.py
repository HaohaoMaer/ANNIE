"""Tests for state models."""

import pytest

from annie.npc.state import (
    AgentState,
    NPCProfile,
    Task,
    TaskStatus,
    load_npc_profile,
)


class TestNPCProfile:
    def test_load_example_npc(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert isinstance(profile, NPCProfile)
        assert profile.name == "Example NPC"
        assert "calm" in profile.personality.traits
        assert "rational" in profile.personality.traits
        assert "logic" in profile.personality.values

    def test_relationships(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert len(profile.relationships) == 1
        rel = profile.relationships[0]
        assert rel.target == "NPC_B"
        assert rel.type == "friend"
        assert rel.intensity == 0.7

    def test_memory_seed(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert "Initial important memory" in profile.memory_seed

    def test_skills_default_empty(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert profile.skills == []

    def test_tools_default_empty(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert profile.tools == []

    def test_skills_and_tools_from_dict(self):
        profile = NPCProfile(
            name="Test",
            skills=["negotiation", "storytelling"],
            tools=["perception"],
        )
        assert profile.skills == ["negotiation", "storytelling"]
        assert profile.tools == ["perception"]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError, match="NPC definition file not found"):
            load_npc_profile("nonexistent/npc.yaml")


class TestTask:
    def test_default_values(self):
        task = Task(description="Test task")
        assert task.status == TaskStatus.PENDING
        assert task.priority == 0
        assert task.result is None
        assert len(task.id) == 8

    def test_status_values(self):
        for status in TaskStatus:
            task = Task(description="test", status=status)
            assert task.status == status

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            Task(description="test", status="invalid_status")


class TestAgentState:
    def test_construct_minimal(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        state: AgentState = {
            "npc_profile": profile,
            "input_event": "A stranger approaches.",
        }
        assert state["npc_profile"].name == "Example NPC"
        assert state["input_event"] == "A stranger approaches."

    def test_construct_full(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        task = Task(description="Observe stranger")
        state: AgentState = {
            "npc_profile": profile,
            "input_event": "A stranger approaches.",
            "tasks": [task],
            "current_task": task,
            "execution_results": [{"action": "observe"}],
            "reflection": "The stranger seems friendly.",
            "memory_context": "Previously met traders.",
        }
        assert len(state["tasks"]) == 1
        assert state["reflection"] == "The stranger seems friendly."
