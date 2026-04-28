"""Tests for state models."""

import pytest

from annie.npc.state import (
    AgentState,
    Task,
    TaskStatus,
)


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
        state: AgentState = {
            "input_event": "A stranger approaches.",
        }
        assert state["input_event"] == "A stranger approaches."

    def test_construct_full(self):
        task = Task(description="Observe stranger")
        state: AgentState = {
            "input_event": "A stranger approaches.",
            "tasks": [task],
            "current_task": task,
            "execution_results": [{"action": "observe"}],
            "reflection": "The stranger seems friendly.",
            "memory_context": "Previously met traders.",
        }
        assert len(state["tasks"]) == 1
        assert state["reflection"] == "The stranger seems friendly."
