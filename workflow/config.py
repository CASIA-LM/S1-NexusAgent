"""Configurable parameters for NexusAgent.

All sensitive values (API keys, internal URLs) are loaded from environment
variables. Copy .env.template to .env and fill in your own values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Annotated, Optional

from langchain_core.runnables import RunnableConfig, ensure_config


# ---------------------------------------------------------------------------
# LLM model configs — plain class attributes, accessed as ClassName.attr
# ---------------------------------------------------------------------------

class DeepSeekV3:
    """DeepSeek-V3 — primary reasoning model."""
    model: str = os.environ.get("DEEPSEEK_V3_MODEL", "deepseek-chat")
    api_key: str = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url: str = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    temperature: float = 0.6


class DeepSeekV3_2:
    """DeepSeek-V3 (planner/executor model — can point to a different endpoint)."""
    model: str = os.environ.get("DEEPSEEK_V3_2_MODEL", "deepseek-chat")
    api_key: str = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url: str = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    temperature: float = 0.6


class Qwen3:
    """Qwen3-8B — lightweight model for classification tasks."""
    model: str = os.environ.get("QWEN3_MODEL", "qwen3-8b")
    api_key: str = os.environ.get("QWEN3_API_KEY", "")
    base_url: str = os.environ.get("QWEN3_BASE_URL", "https://api.openai.com/v1")
    temperature: float = 0.6


class Qwen72B:
    """Qwen2.5-72B — large reasoning model."""
    model: str = os.environ.get("QWEN72B_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    api_key: str = os.environ.get("QWEN72B_API_KEY", "")
    base_url: str = os.environ.get("QWEN72B_BASE_URL", "https://api.openai.com/v1")
    temperature: float = 0.3
    max_tokens: int = 50000
    check_embedding_ctx_length: bool = False


class QwQ32B:
    """QwQ-32B — reasoning model."""
    model: str = os.environ.get("QWQ32B_MODEL", "QwQ-32b")
    api_key: str = os.environ.get("QWQ32B_API_KEY", "")
    base_url: str = os.environ.get("QWQ32B_BASE_URL", "https://api.openai.com/v1")
    temperature: float = 0.1
    max_tokens: int = 30000


class Ark:
    """Volcano Engine Ark model."""
    model: str = os.environ.get("ARK_MODEL", "")
    api_key: str = os.environ.get("ARK_API_KEY", "")
    base_url: str = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    temperature: float = 0.1
    max_tokens: int = 30000


# ---------------------------------------------------------------------------
# Embedding model configs
# ---------------------------------------------------------------------------

class Qwen3Embedding:
    """Qwen3-Embedding-8B — tool retrieval embeddings."""
    model: str = os.environ.get("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
    api_key: str = os.environ.get("EMBEDDING_API_KEY", "")
    base_url: str = os.environ.get("EMBEDDING_BASE_URL", "https://api.openai.com/v1")


# ---------------------------------------------------------------------------
# Specialised model endpoint configs (optional — for self-hosted AI services)
# ---------------------------------------------------------------------------

class EVO2:
    """DNA generation model endpoint (self-hosted)."""
    DNA_GENERATE_URL: str = os.environ.get("EVO2_URL", "")


class ESM3:
    """Protein structure generation model endpoint (self-hosted)."""
    GENERATE_SEQUENCE: str = os.environ.get("ESM3_SEQUENCE_URL", "")
    GENERATE_PDB: str = os.environ.get("ESM3_STRUCTURE_URL", "")


class MassSpec:
    """Mass spectrometry analysis model endpoint (self-hosted)."""
    CHAT: str = os.environ.get("MASSSPEC_URL", "")


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

@dataclass(kw_only=True)
class Configuration:
    system_prompt: str = field(
        default="You are helpful.",
        metadata={"description": "System prompt for the agent."},
    )
    model: Annotated[str, ] = field(
        default="openai/deepseek-chat",
        metadata={"description": "Language model in provider/model-name format."},
    )
    history_length: int = field(default=50)
    max_execute_time: int = field(default=3)
    max_search_results: int = field(
        default=2,
        metadata={"description": "Maximum search results per query."},
    )

    @classmethod
    def from_runnable_config(cls, config: Optional[RunnableConfig] = None) -> Configuration:
        config = ensure_config(config)
        configurable = config.get("configurable") or {}
        _fields = {f.name for f in fields(cls) if f.init}
        return cls(**{k: v for k, v in configurable.items() if k in _fields})


# ---------------------------------------------------------------------------
# Storage configs
# ---------------------------------------------------------------------------

class MinioConfig:
    """MinIO object storage — used for saving large tool outputs."""
    minio_url: str = os.environ.get("MINIO_URL", "")
    minio_access_key: str = os.environ.get("MINIO_ACCESS_KEY", "")
    minio_secret_key: str = os.environ.get("MINIO_SECRET_KEY", "")
    minio_bucket_name: str = os.environ.get("MINIO_BUCKET_NAME", "nexusagent")
    minio_secure: str = os.environ.get("MINIO_SECURE", "false")


class Common:
    proxy_url: str = os.environ.get("PROXY_URL", "")


@dataclass(kw_only=True)
class SandboxConfig:
    """Code execution sandbox endpoint."""
    base_url: str = field(
        default=os.environ.get("SANDBOX_URL", "http://localhost:9001")
    )
