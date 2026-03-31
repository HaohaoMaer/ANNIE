"""Main NPC Agent - LangGraph-based orchestrator for a single NPC.

Coordinates Planner, Executor, and Reflector nodes within a LangGraph workflow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from annie.npc.config import ModelConfig, load_model_config
from annie.npc.executor import Executor
from annie.npc.llm import create_chat_model
from annie.npc.memory.episodic import EpisodicMemory
from annie.npc.memory.relationship import RelationshipMemory
from annie.npc.memory.semantic import SemanticMemory
from annie.npc.planner import Planner
from annie.npc.reflector import Reflector
from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.state import AgentState, Task, load_npc_profile
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.tracing import Tracer

logger = logging.getLogger(__name__)


class AgentRunResult(BaseModel):
    """Result of a single NPCAgent run."""

    tasks: list[Task] = Field(default_factory=list)
    execution_results: list[dict[str, Any]] = Field(default_factory=list)
    reflection: str = ""
    trace_summary: str = ""


class NPCAgent:
    """Top-level NPC agent that wires Planner -> Executor -> Reflector in LangGraph."""

    def __init__(
        self,
        npc_yaml_path: str | Path,
        config_path: str | Path = "config/model_config.yaml",
        chroma_client: chromadb.ClientAPI | None = None,
    ):
        # Load configuration
        self.config: ModelConfig = load_model_config(config_path)
        self.npc_profile = load_npc_profile(npc_yaml_path)

        # Create LLM
        self.llm = create_chat_model(self.config)

        # Create memory system
        self._chroma_client = chroma_client or chromadb.PersistentClient(
            path=self.config.memory.persist_directory
        )
        self._episodic = EpisodicMemory(self.npc_profile.name, client=self._chroma_client)
        self._semantic = SemanticMemory(self.npc_profile.name, client=self._chroma_client)
        self._relationship = RelationshipMemory(
            self.npc_profile.name,
            initial_relationships=self.npc_profile.relationships,
        )
        self.memory_agent = MemoryAgent(self._episodic, self._semantic, self._relationship)

        # Seed initial memories from NPC profile
        self._seed_memories()

        # Create skill registry
        self.skill_registry = SkillRegistry("data/skills")

        # Create node instances
        self._planner = Planner(self.llm)
        self._executor = Executor(self.llm, self.memory_agent, self.skill_registry)
        self._reflector = Reflector(self.llm, self.memory_agent)

        # Build LangGraph
        self._graph = self._build_graph()

        # Track last tracer for inspection
        self._last_tracer: Tracer | None = None

    def _seed_memories(self) -> None:
        """Seed initial memories from the NPC profile's memory_seed."""
        for seed in self.npc_profile.memory_seed:
            self._semantic.store(seed, category="seed")

    def _build_graph(self):
        """Build and compile the LangGraph StateGraph."""
        graph = StateGraph(AgentState)
        graph.add_node("planner", self._planner)
        graph.add_node("executor", self._executor)
        graph.add_node("reflector", self._reflector)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "executor")
        graph.add_edge("executor", "reflector")
        graph.add_edge("reflector", END)
        return graph.compile()

    def run(self, event: str) -> AgentRunResult:
        """Run the NPC agent with a given input event.

        Args:
            event: The input event or interaction to respond to.

        Returns:
            AgentRunResult with tasks, execution results, reflection, and trace summary.
        """
        tracer = Tracer(self.npc_profile.name)

        # Build memory context for the event
        memory_context = self.memory_agent.build_context(event)

        # Construct initial state
        initial_state: AgentState = {
            "npc_profile": self.npc_profile,
            "input_event": event,
            "tasks": [],
            "current_task": None,
            "execution_results": [],
            "reflection": "",
            "memory_context": memory_context,
            "tracer": tracer,
        }

        # Execute the graph
        final_state = self._graph.invoke(initial_state)

        self._last_tracer = tracer

        # Log trace
        for line in tracer.to_log_lines():
            logger.info(line)

        return AgentRunResult(
            tasks=final_state.get("tasks", []),
            execution_results=final_state.get("execution_results", []),
            reflection=final_state.get("reflection", ""),
            trace_summary=tracer.summary(),
        )

    def get_last_trace(self) -> Tracer | None:
        """Return the tracer from the most recent run for inspection."""
        return self._last_tracer
