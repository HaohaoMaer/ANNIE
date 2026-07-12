"""Configuration loader for ANNIE NPC system.

Reads model_config.yaml and provides typed configuration objects.
"""

import os
import importlib
from pathlib import Path

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str
    model_name: str
    base_url: str
    api_key_env: str
    temperature: float = 0.7


class EmbeddingConfig(BaseModel):
    provider: str
    model: str


class MemoryConfig(BaseModel):
    vector_store: str = "chromadb"
    persist_directory: str = "./data/vector_store"


class WorldConfig(BaseModel):
    tick_interval_seconds: float = 1.0
    default_time_scale: float = 1.0


class ModelConfig(BaseModel):
    model: LLMConfig = Field(alias="model")
    embedding: EmbeddingConfig
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    world: WorldConfig = Field(default_factory=WorldConfig)

    model_config = {"populate_by_name": True}

    @property
    def api_key(self) -> str | None:
        """Resolve the API key from the environment variable specified in config."""
        return os.environ.get(self.model.api_key_env)


def load_model_config(path: str | Path = "config/model_config.yaml") -> ModelConfig:
    """Load model configuration from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A validated ModelConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = importlib.import_module("yaml").safe_load(f)

    return ModelConfig(**raw)
