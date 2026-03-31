"""Tests for LLM integration layer."""

import pytest

from annie.npc.config import load_model_config
from annie.npc.llm import create_chat_model, create_embeddings


@pytest.fixture
def config():
    return load_model_config("config/model_config.yaml")


class TestCreateChatModel:
    def test_returns_chat_model(self, config, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        model = create_chat_model(config)
        assert model is not None
        assert model.model_name == "deepseek-chat"

    def test_base_url_set(self, config, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        model = create_chat_model(config)
        assert "deepseek" in str(model.openai_api_base)

    def test_temperature_set(self, config, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        model = create_chat_model(config)
        assert model.temperature == 0.7


class TestCreateEmbeddings:
    def test_returns_embeddings_for_local(self, config):
        embeddings = create_embeddings(config)
        assert embeddings is not None
        assert config.embedding.provider == "local"


@pytest.mark.integration
class TestLLMIntegration:
    def test_chat_model_responds(self, config):
        model = create_chat_model(config)
        response = model.invoke("Say hello in one word.")
        assert response.content
        assert len(response.content) > 0
