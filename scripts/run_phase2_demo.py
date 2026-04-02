#!/usr/bin/env python3
"""ANNIE Phase 2 Demo — Multi-NPC Social Graph with Information Asymmetry.

Demonstrates:
  - 3 NPCs sharing a global SocialGraph
  - Preset historical events with different visibility levels
  - Propagation-driven information asymmetry
  - Per-NPC subjective worldviews via the Perception Pipeline
  - Belief evaluation (ACCEPTED / SKEPTICAL / DOUBTED / REJECTED)

Usage:
    python scripts/run_phase2_demo.py

Requires DEEPSEEK_API_KEY environment variable to be set.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from annie.npc.agent import NPCAgent
from annie.npc.tracing import TraceFormatter
from annie.social_graph.event_log import SocialEventLog
from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import (
    EventVisibility,
    RelationshipEdge,
    SocialEvent,
)
from annie.social_graph.perception.belief_evaluator import BeliefEvaluator
from annie.social_graph.perception.knowledge_filter import KnowledgeFilter
from annie.social_graph.perception.perception_builder import PerceptionBuilder
from annie.social_graph.propagation import PropagationEngine

# ANSI colors
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

ALL_NPCS = ["Village Elder", "Blacksmith Gareth", "Merchant Lina"]


def header(text: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {BOLD}{text}{RESET}")
    print(f"{'=' * 70}\n")


def setup_social_graph() -> tuple[SocialGraph, SocialEventLog, PropagationEngine]:
    """Create and seed the shared Social Graph."""
    graph = SocialGraph()
    event_log = SocialEventLog()
    engine = PropagationEngine(graph, event_log)

    # --- Directed relationship edges (god's-eye truth) ---
    edges = [
        ("Village Elder", "Blacksmith Gareth", "trusted_ally", 0.8, 0.7, 0.9, 0.4),
        ("Village Elder", "Merchant Lina", "trade_partner", 0.6, 0.5, 0.6, 0.2),
        ("Blacksmith Gareth", "Village Elder", "trusted_ally", 0.7, 0.8, 0.9, 0.5),
        ("Blacksmith Gareth", "Merchant Lina", "acquaintance", 0.3, 0.2, 0.4, -0.1),
        ("Merchant Lina", "Village Elder", "trade_partner", 0.5, 0.4, 0.6, 0.1),
        ("Merchant Lina", "Blacksmith Gareth", "acquaintance", 0.3, 0.3, 0.4, 0.0),
    ]
    for src, tgt, rtype, intensity, trust, familiarity, valence in edges:
        graph.set_edge(RelationshipEdge(
            source=src, target=tgt, type=rtype,
            intensity=intensity, trust=trust,
            familiarity=familiarity, emotional_valence=valence,
        ))

    # --- Preset historical events ---
    now = datetime.now(UTC)

    event1 = SocialEvent(
        id="preset_accusation",
        actor="Blacksmith Gareth",
        target="Carpenter",
        action="publicly accused",
        description="Blacksmith Gareth publicly accused the carpenter of stealing his customers by undercutting prices unfairly",
        witnesses=["Village Elder"],
        visibility=EventVisibility.WITNESSED,
        tags=["conflict", "accusation"],
        timestamp=now - timedelta(days=7),
    )

    event2 = SocialEvent(
        id="preset_tampering",
        actor="Merchant Lina",
        action="discovered tampering",
        description="Merchant Lina discovered that trade goods on the eastern supply route have been tampered with, possibly by someone in the village",
        visibility=EventVisibility.PRIVATE,
        tags=["trade", "tampering", "secret"],
        timestamp=now - timedelta(days=3),
    )

    event_log.load_preset_events([event1, event2])

    # Propagate preset events.
    engine.propagate_event(event1, ALL_NPCS)
    engine.propagate_event(event2, ALL_NPCS)

    return graph, event_log, engine


def print_knowledge_status(graph: SocialGraph) -> None:
    """Show who knows what."""
    kf = KnowledgeFilter(graph)
    for npc in ALL_NPCS:
        items = kf.get_known_events(npc)
        print(f"  {CYAN}{npc}{RESET}: knows {len(items)} event(s)")
        for ki in items:
            source = "first-hand" if ki.source_npc is None else f"from {ki.source_npc}"
            print(f"    - [{ki.event_id}] {source}, distortion={ki.distortion:.2f}")


def print_subjective_views(graph: SocialGraph) -> None:
    """Show each NPC's subjective worldview side by side."""
    kf = KnowledgeFilter(graph)
    be = BeliefEvaluator(graph)
    builder = PerceptionBuilder(kf, be)

    for npc in ALL_NPCS:
        print(f"\n  {BOLD}{CYAN}--- {npc}'s Worldview ---{RESET}")
        ctx = builder.build_social_context(npc)
        for line in ctx.split("\n"):
            print(f"  {line}")


def print_god_eye_vs_subjective(graph: SocialGraph) -> None:
    """Compare god's-eye graph with each NPC's perceived relationships."""
    kf = KnowledgeFilter(graph)
    be = BeliefEvaluator(graph)
    builder = PerceptionBuilder(kf, be)

    print(f"  {BOLD}God's Eye (objective truth):{RESET}")
    for npc in ALL_NPCS:
        outgoing = graph.get_outgoing_edges(npc)
        for e in outgoing:
            print(f"    {e.source} -> {e.target}: {e.type} "
                  f"(trust={e.trust:.1f}, valence={e.emotional_valence:.1f})")

    print()
    for npc in ALL_NPCS:
        rels = builder.build_perceived_relationships(npc)
        print(f"  {BOLD}{npc}'s perception:{RESET}")
        for r in rels:
            print(f"    -> {r.target}: {r.type} (trust={r.trust:.1f}, valence={r.emotional_valence:.1f})")


def main():
    header("ANNIE Phase 2 Demo — Multi-NPC Social Graph")

    # ── Phase A: Setup ──
    print(f"{BOLD}Setting up Social Graph...{RESET}")
    graph, event_log, propagation = setup_social_graph()
    print(f"  {GREEN}Graph created with {len(graph.get_all_npcs())} NPCs{RESET}")
    print(f"  {GREEN}{len(event_log)} preset events loaded{RESET}")

    # ── Phase B: Show initial information asymmetry ──
    header("Initial Information Asymmetry")
    print_knowledge_status(graph)

    # ── Phase C: Show subjective worldviews BEFORE trigger event ──
    header("Subjective Worldviews (before trigger)")
    print_subjective_views(graph)

    # ── Phase D: Trigger event ──
    header("Trigger Event")
    trigger = SocialEvent(
        id="trigger_announcement",
        actor="Traveling Merchant",
        action="announced",
        description=(
            "A traveling merchant arrives in the village square and announces that "
            "Blacksmith Gareth's metalwork has been highly praised in the capital city. "
            "However, the merchant also mentions hearing disturbing rumors that someone "
            "in the village has been tampering with trade goods on the eastern route."
        ),
        visibility=EventVisibility.PUBLIC,
        tags=["trade", "praise", "rumor", "tampering"],
    )
    event_log.append(trigger)
    propagation.propagate_event(trigger, ALL_NPCS)
    print(f"  {YELLOW}Trigger: {trigger.description[:120]}...{RESET}")
    print()
    print(f"  Knowledge after trigger:")
    print_knowledge_status(graph)

    # ── Phase E: Each NPC processes the event ──
    header("NPC Responses")

    npc_yamls = [
        "data/npcs/village_elder.yaml",
        "data/npcs/blacksmith_gareth.yaml",
        "data/npcs/merchant_lina.yaml",
    ]

    for yaml_path in npc_yamls:
        npc_name = Path(yaml_path).stem.replace("_", " ").title()
        print(f"\n  {BOLD}{CYAN}Processing: {npc_name}{RESET}")
        print(f"  {DIM}{'─' * 50}{RESET}")

        try:
            agent = NPCAgent(
                yaml_path,
                social_graph=graph,
                event_log=event_log,
            )
            result = agent.run(trigger.description)

            # Print trace summary
            tracer = agent.get_last_trace()
            if tracer:
                print(f"  {DIM}Trace: {tracer.summary()}{RESET}")

            # Print tasks
            print(f"\n  {BOLD}Tasks:{RESET}")
            for task in result.tasks:
                print(f"    [{task.status.value}] {task.description} (p={task.priority})")

            # Print actions
            print(f"\n  {BOLD}Actions:{RESET}")
            for r in result.execution_results:
                action_text = r["action"][:250]
                print(f"    {action_text}")

            # Print reflection
            print(f"\n  {BOLD}Reflection:{RESET}")
            print(f"    {result.reflection[:300]}")

            # Run propagation tick after this NPC acts.
            propagation.tick(ALL_NPCS)

        except Exception as e:
            print(f"  {RED}Error: {e}{RESET}")

    # ── Phase F: Final comparison ──
    header("Final State — God's Eye vs. Subjective Views")
    print_god_eye_vs_subjective(graph)

    header("Final Subjective Worldviews")
    print_subjective_views(graph)

    header("Final Knowledge Status")
    print_knowledge_status(graph)

    print(f"\n{GREEN}Demo complete.{RESET}\n")


if __name__ == "__main__":
    main()
