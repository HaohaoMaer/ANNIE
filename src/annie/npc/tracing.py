"""Execution tracing system for ANNIE NPC agents.

Provides structured, domain-aware tracing that flows through AgentState.
Each LangGraph node uses the Tracer to record events, producing an
observable log of the agent's execution.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    NODE_ENTER = "node_enter"
    NODE_EXIT = "node_exit"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    SKILL_INVOKE = "skill_invoke"
    TOOL_INVOKE = "tool_invoke"
    TASK_CREATED = "task_created"
    ERROR = "error"


class TraceEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    node_name: str
    agent_name: str
    event_type: EventType
    input_summary: str = ""
    output_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = None


class Tracer:
    """Accumulates TraceEvents during a single agent run."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.events: list[TraceEvent] = []
        self._start_time = time.monotonic()

    def trace(
        self,
        node_name: str,
        event_type: EventType,
        *,
        input_summary: str = "",
        output_summary: str = "",
        metadata: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> TraceEvent:
        """Record a single trace event."""
        event = TraceEvent(
            node_name=node_name,
            agent_name=self.agent_name,
            event_type=event_type,
            input_summary=input_summary,
            output_summary=output_summary,
            metadata=metadata or {},
            duration_ms=duration_ms,
        )
        self.events.append(event)
        return event

    @contextmanager
    def node_span(self, node_name: str):
        """Context manager that records NODE_ENTER on entry and NODE_EXIT with duration on exit."""
        self.trace(node_name, EventType.NODE_ENTER)
        start = time.monotonic()
        try:
            yield
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            self.trace(
                node_name,
                EventType.ERROR,
                output_summary=str(exc),
                duration_ms=elapsed,
            )
            raise
        else:
            elapsed = (time.monotonic() - start) * 1000
            self.trace(node_name, EventType.NODE_EXIT, duration_ms=elapsed)

    def to_log_lines(self) -> list[str]:
        """Return human-readable formatted lines for console output."""
        lines = []
        for e in self.events:
            ts = e.timestamp.strftime("%H:%M:%S.%f")[:-3]
            dur = f" ({e.duration_ms:.0f}ms)" if e.duration_ms is not None else ""
            parts = [f"[{ts}]", f"[{e.node_name}]", e.event_type.value]
            if e.input_summary:
                parts.append(f"in={e.input_summary}")
            if e.output_summary:
                parts.append(f"out={e.output_summary}")
            parts.append(dur)
            lines.append(" ".join(p for p in parts if p))
        return lines

    def to_json(self) -> str:
        """Return JSON array of all events for persistence or analysis."""
        return json.dumps(
            [e.model_dump(mode="json") for e in self.events],
            ensure_ascii=False,
            indent=2,
        )

    def summary(self) -> str:
        """Return a compact one-line summary of the run.

        Example: "Planner(3 tasks) -> Executor(2 results) -> Reflector(ok) [1247ms]"
        """
        node_summaries: dict[str, str] = {}
        for e in self.events:
            if e.event_type == EventType.NODE_EXIT:
                label = e.output_summary if e.output_summary else "ok"
                node_summaries[e.node_name] = f"{e.node_name.capitalize()}({label})"
            elif e.event_type == EventType.TASK_CREATED and e.output_summary:
                node_summaries.setdefault(
                    e.node_name, f"{e.node_name.capitalize()}({e.output_summary})"
                )

        total_ms = (time.monotonic() - self._start_time) * 1000
        chain = " -> ".join(node_summaries.values()) if node_summaries else "empty"
        return f"{chain} [{total_ms:.0f}ms]"


class TraceFormatter:
    """Formats trace output for console and file."""

    # ANSI color codes
    COLORS = {
        EventType.NODE_ENTER: "\033[1;36m",  # bold cyan
        EventType.NODE_EXIT: "\033[1;32m",  # bold green
        EventType.LLM_CALL: "\033[33m",  # yellow
        EventType.LLM_RESPONSE: "\033[33m",  # yellow
        EventType.MEMORY_READ: "\033[35m",  # magenta
        EventType.MEMORY_WRITE: "\033[35m",  # magenta
        EventType.SKILL_INVOKE: "\033[34m",  # blue
        EventType.TOOL_INVOKE: "\033[36m",  # cyan
        EventType.TASK_CREATED: "\033[1;37m",  # bold white
        EventType.ERROR: "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    @classmethod
    def format_for_console(cls, tracer: Tracer) -> str:
        """Format trace events with colors and indentation for terminal display."""
        lines = []
        indent = 0
        for e in tracer.events:
            color = cls.COLORS.get(e.event_type, "")
            ts = e.timestamp.strftime("%H:%M:%S.%f")[:-3]

            if e.event_type == EventType.NODE_EXIT:
                indent = max(0, indent - 1)

            prefix = "  " * indent
            dur = (
                f" {cls.DIM}({e.duration_ms:.0f}ms){cls.RESET}" if e.duration_ms is not None else ""
            )

            # Build the line
            parts = [f"{cls.DIM}[{ts}]{cls.RESET}"]
            parts.append(f"{color}{e.event_type.value}{cls.RESET}")
            parts.append(f"[{e.node_name}]")

            if e.input_summary:
                parts.append(f"in={e.input_summary[:80]}")
            if e.output_summary:
                parts.append(f"out={e.output_summary[:80]}")
            parts.append(dur)

            lines.append(prefix + " ".join(p for p in parts if p))

            if e.event_type == EventType.NODE_ENTER:
                indent += 1

        # Append summary
        lines.append("")
        lines.append(f"\033[1mSummary:\033[0m {tracer.summary()}")
        return "\n".join(lines)

    @staticmethod
    def format_for_file(tracer: Tracer, path: str) -> None:
        """Write JSON trace to a file."""
        from pathlib import Path as P

        P(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(tracer.to_json())
