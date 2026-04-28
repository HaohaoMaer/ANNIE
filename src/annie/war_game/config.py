"""Tunable game parameters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GameConfig:
    """All tunable balance / flow parameters for the war game."""

    initial_forces: int = 1000
    production_per_city: int = 50
    max_diplomacy_rounds: int = 3
    max_negotiation_rounds: int = 2
