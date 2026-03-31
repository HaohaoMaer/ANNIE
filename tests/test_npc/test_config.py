"""Tests for config loader."""

import os
from pathlib import Path

import pytest

from annie.npc.config import ModelConfig, load_model_config


class TestLoadModelConfig:
    def test_loads_default_config(self):
        config = load_model_config("config/model_config.yaml")
        assert isinstance(config, ModelConfig)
        assert config.model.provider == "deepseek"
        assert config.model.model_name == "deepseek-chat"
        assert config.model.base_url == "https://api.deepseek.com"
        assert config.model.api_key_env == "DEEPSEEK_API_KEY"
        assert config.model.temperature == 0.7

    def test_embedding_config(self):
        config = load_model_config("config/model_config.yaml")
        assert config.embedding.provider == "local"
        assert config.embedding.model == "BAAI/bge-m3"

    def test_memory_config(self):
        config = load_model_config("config/model_config.yaml")
        assert config.memory.vector_store == "chromadb"
        assert config.memory.persist_directory == "./data/vector_store"

    def test_world_config(self):
        config = load_model_config("config/model_config.yaml")
        assert config.world.tick_interval_seconds == 1
        assert config.world.default_time_scale == 1.0

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_model_config("nonexistent/config.yaml")

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-123")
        config = load_model_config("config/model_config.yaml")
        assert config.api_key == "test-key-123"

    def test_api_key_missing_env(self):
        os.environ.pop("DEEPSEEK_API_KEY", None)
        config = load_model_config("config/model_config.yaml")
        assert config.api_key is None
