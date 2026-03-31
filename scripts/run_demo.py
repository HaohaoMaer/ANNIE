#!/usr/bin/env python3
"""ANNIE Demo Script - Runs the Village Elder NPC through a sequence of events.

Usage:
    python scripts/run_demo.py

Requires DEEPSEEK_API_KEY environment variable to be set.
"""

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from annie.npc.agent import NPCAgent
from annie.npc.tracing import TraceFormatter


def main():
    print("=" * 70)
    print("  ANNIE Demo - Village Elder NPC")
    print("=" * 70)
    print()

    # Initialize the NPC
    print("Initializing Village Elder...")
    agent = NPCAgent("data/npcs/village_elder.yaml")
    print(f"NPC loaded: {agent.npc_profile.name}")
    print(f"Traits: {', '.join(agent.npc_profile.personality.traits)}")
    print(f"Skills available: {agent.skill_registry.list_skills()}")
    print()

    # Define a sequence of events
    events = [
        "A dusty traveler arrives at the village gate, asking for directions to the eastern trade route.",
        "The blacksmith Gareth storms in, complaining that the carpenter has been stealing his customers.",
        "A scout reports seeing movement near the northern pass - possibly bandits returning.",
    ]

    for i, event in enumerate(events, 1):
        print("=" * 70)
        print(f"  Event {i}/{len(events)}")
        print("=" * 70)
        print(f"\n  {event}\n")

        # Run the agent
        result = agent.run(event)

        # Print trace
        tracer = agent.get_last_trace()
        print(TraceFormatter.format_for_console(tracer))
        print()

        # Print results
        print(f"\033[1mTasks:\033[0m")
        for task in result.tasks:
            print(f"  [{task.status.value}] {task.description} (priority={task.priority})")
        print()

        print(f"\033[1mActions:\033[0m")
        for r in result.execution_results:
            print(f"  - {r['action'][:200]}")
        print()

        print(f"\033[1mReflection:\033[0m")
        print(f"  {result.reflection[:300]}")
        print()

    # Save final trace to file
    trace_path = "data/traces/demo_trace.json"
    TraceFormatter.format_for_file(agent.get_last_trace(), trace_path)
    print(f"Last trace saved to {trace_path}")
    print("\nDemo complete.")


if __name__ == "__main__":
    main()
