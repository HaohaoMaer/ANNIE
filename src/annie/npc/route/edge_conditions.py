"""Generic route-local edge condition helpers."""

from __future__ import annotations

from annie.npc.core.state import AgentState, TaskStatus


def always(_state: AgentState) -> bool:
    return True


def has_tasks(state: AgentState) -> bool:
    return bool(state.get("tasks"))


def action_done(state: AgentState) -> bool:
    return not needs_replan(state)


def needs_replan(state: AgentState) -> bool:
    results = state.get("execution_results", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 0)
    all_failed = bool(state.get("tasks")) and all(
        t.status == TaskStatus.FAILED for t in state.get("tasks", [])
    )
    return (not results or all_failed) and retry_count < max_retries


def consume_replan_retry(state: AgentState) -> bool:
    if not needs_replan(state):
        return False
    state["retry_count"] = state.get("retry_count", 0) + 1
    state["loop_reason"] = "executor produced no results"
    return True
