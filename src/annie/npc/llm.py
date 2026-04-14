"""LLM integration layer for ANNIE NPC system.

Thin factory functions that create LangChain model instances from config.
"""

from __future__ import annotations

import os

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc.config import ModelConfig


def create_chat_model(config: ModelConfig) -> BaseChatModel:
    """Create a LangChain chat model from config.

    DeepSeek and other OpenAI-compatible providers use ChatOpenAI with base_url override.
    """
    api_key = os.environ.get(config.model.api_key_env, "")
    return ChatOpenAI(
        model=config.model.model_name,
        base_url=config.model.base_url,
        api_key=SecretStr(api_key) if api_key else None,
        temperature=config.model.temperature,
    )


def create_embeddings(config: ModelConfig) -> Embeddings:
    """Create an embeddings model from config.

    For local provider, uses HuggingFace sentence-transformers.
    """
    if config.embedding.provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings  # type: ignore[import-not-found]

        return HuggingFaceEmbeddings(model_name=config.embedding.model)

    # Fallback for OpenAI-compatible embedding providers
    from langchain_openai import OpenAIEmbeddings

    api_key = os.environ.get(config.model.api_key_env, "")
    return OpenAIEmbeddings(
        model=config.embedding.model,
        api_key=SecretStr(api_key) if api_key else None,
    )