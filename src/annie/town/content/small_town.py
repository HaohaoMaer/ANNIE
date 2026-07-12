"""Small-town fixture compatibility wrapper backed by scenario content."""

from __future__ import annotations

from annie.town.content.scenario import create_small_town_state_from_scenario
from annie.town.domain import TownState


def create_small_town_state() -> TownState:
    """Create the canonical semantic town fixture from project-owned YAML."""
    return create_small_town_state_from_scenario()
