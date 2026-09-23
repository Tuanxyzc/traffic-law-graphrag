"""Pipeline configuration dataclass for GraphRAG."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration settings for the GraphRAG pipeline."""

    # Gemini Cloud LLM Settings
    model_name: str = "gemini-2.5-flash"
    rewrite_model_name: str = "gemini-2.5-flash"
    temperature_rewrite: float = 0.1
    temperature_generate: float = 0.2
    max_retries: int = 5
    timeout_seconds: float = 60.0

    # Multi-Provider Settings (Gemini, Groq, Cerebras, Cohere)
    provider_order: tuple[str, ...] = ("gemini", "groq", "cerebras", "cohere")
    groq_model: str = "qwen/qwen3.8-27b"
    cerebras_model: str = "qwen-3.8-27b"
    cohere_model: str = "command-r-08-2024"
    groq_endpoint: str = "https://api.groq.com/openai/v1"
    cerebras_endpoint: str = "https://api.cerebras.ai/v1"
    cohere_endpoint: str = "https://api.cohere.ai/compatibility/v1"

    # Local LLM Settings for Answer Generator
    generator_use_local: bool = False
    generator_local_endpoint: str = "http://localhost:11434/v1"
    generator_local_model: str = "Qwen2.5:1.5b"
    generator_local_temperature: float = 0.2
    generator_local_timeout: float = 120.0
    generator_local_api_key: str = "ollama"

    # Local LLM Settings for Query Rewriter
    rewriter_use_local: bool = False
    rewriter_local_endpoint: str = "http://localhost:11434/v1"
    rewriter_local_model: str = "Qwen2.5:1.5b"
    rewriter_local_temperature: float = 0.1
    rewriter_local_timeout: float = 60.0
    rewriter_local_api_key: str = "ollama"

    # Pipeline Behaviors
    enable_query_rewrite: bool = True
    enable_dual_query: bool = True
    top_k: int = 5
    max_reference_hops: int = 1
    include_superseded_warning: bool = True

    # Neo4j Settings
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "password")

    @classmethod
    def from_env(cls, config_path: str | None = None) -> PipelineConfig:
        """Instantiates PipelineConfig overriding defaults with config.yaml and environment variables."""
        yaml_data: dict[str, Any] = {}
        actual_path: str = config_path or os.getenv("CONFIG_PATH") or "config.yaml"
        if os.path.exists(actual_path):
            try:
                with open(actual_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        yaml_data = loaded
            except Exception as e:
                logger.warning("Failed to load config file %s: %s", actual_path, e)

        def _get_yaml(*keys: str, default: Any = None) -> Any:
            curr: Any = yaml_data
            for k in keys:
                if isinstance(curr, dict) and k in curr:
                    curr = curr[k]
                else:
                    return default
            return curr

        # 1. Generator local vs gemini
        gen_local_val = os.getenv("GENERATOR_USE_LOCAL") or os.getenv(
            "PIPELINE_GENERATOR_USE_LOCAL"
        )
        if gen_local_val is not None:
            generator_use_local = gen_local_val.lower() in ("true", "1", "yes")
        else:
            y_gen_local = _get_yaml("llm", "generator", "use_local")
            generator_use_local = (
                bool(y_gen_local) if y_gen_local is not None else False
            )

        generator_local_endpoint = (
            os.getenv("GENERATOR_LOCAL_ENDPOINT")
            or _get_yaml("llm", "generator", "local", "endpoint")
            or "http://localhost:11434/v1"
        )
        generator_local_model = (
            os.getenv("GENERATOR_LOCAL_MODEL")
            or _get_yaml("llm", "generator", "local", "model_name")
            or "Qwen2.5:1.5b"
        )
        generator_local_temp = float(
            os.getenv("GENERATOR_LOCAL_TEMP")
            or _get_yaml("llm", "generator", "local", "temperature")
            or 0.2
        )
        generator_local_timeout = float(
            os.getenv("GENERATOR_LOCAL_TIMEOUT")
            or _get_yaml("llm", "generator", "local", "timeout_seconds")
            or 120.0
        )
        generator_local_api_key = (
            os.getenv("GENERATOR_LOCAL_API_KEY")
            or _get_yaml("llm", "generator", "local", "api_key")
            or "ollama"
        )

        # 2. Rewriter local vs gemini
        rewriter_local_val = os.getenv("REWRITER_USE_LOCAL") or os.getenv(
            "PIPELINE_REWRITER_USE_LOCAL"
        )
        if rewriter_local_val is not None:
            rewriter_use_local = rewriter_local_val.lower() in ("true", "1", "yes")
        else:
            y_rew_local = _get_yaml("llm", "rewriter", "use_local")
            rewriter_use_local = bool(y_rew_local) if y_rew_local is not None else False

        rewriter_local_endpoint = (
            os.getenv("REWRITER_LOCAL_ENDPOINT")
            or _get_yaml("llm", "rewriter", "local", "endpoint")
            or "http://localhost:11434/v1"
        )
        rewriter_local_model = (
            os.getenv("REWRITER_LOCAL_MODEL")
            or _get_yaml("llm", "rewriter", "local", "model_name")
            or "Qwen2.5:1.5b"
        )
        rewriter_local_temp = float(
            os.getenv("REWRITER_LOCAL_TEMP")
            or _get_yaml("llm", "rewriter", "local", "temperature")
            or 0.1
        )
        rewriter_local_timeout = float(
            os.getenv("REWRITER_LOCAL_TIMEOUT")
            or _get_yaml("llm", "rewriter", "local", "timeout_seconds")
            or 60.0
        )
        rewriter_local_api_key = (
            os.getenv("REWRITER_LOCAL_API_KEY")
            or _get_yaml("llm", "rewriter", "local", "api_key")
            or "ollama"
        )

        # 3. Gemini cloud models
        gemini_model = (
            os.getenv("GEMINI_MODEL")
            or os.getenv("PIPELINE_MODEL")
            or _get_yaml("llm", "generator", "gemini", "model_name")
            or "gemini-2.5-flash"
        )
        rewrite_model = (
            os.getenv("PIPELINE_REWRITE_MODEL")
            or _get_yaml("llm", "rewriter", "gemini", "model_name")
            or os.getenv("GEMINI_MODEL")
            or "gemini-2.5-flash"
        )
        temp_rewrite = float(
            os.getenv("PIPELINE_TEMP_REWRITE")
            or _get_yaml("llm", "rewriter", "gemini", "temperature")
            or 0.1
        )
        temp_generate = float(
            os.getenv("PIPELINE_TEMP_GENERATE")
            or _get_yaml("llm", "generator", "gemini", "temperature")
            or 0.2
        )
        max_retries = int(
            os.getenv("PIPELINE_MAX_RETRIES") or _get_yaml("llm", "max_retries") or 5
        )
        timeout_seconds = float(
            os.getenv("PIPELINE_TIMEOUT")
            or _get_yaml("llm", "generator", "gemini", "timeout_seconds")
            or 60.0
        )

        # 4. Pipeline settings
        enable_query_rewrite = os.getenv("ENABLE_QUERY_REWRITE") or os.getenv(
            "PIPELINE_ENABLE_REWRITE"
        )
        if enable_query_rewrite is not None:
            enable_query_rewrite_val = enable_query_rewrite.lower() in (
                "true",
                "1",
                "yes",
            )
        else:
            val = _get_yaml("llm", "rewriter", "enable_rewrite")
            if val is None:
                val = _get_yaml("pipeline", "enable_query_rewrite")
            enable_query_rewrite_val = bool(val) if val is not None else True

        enable_dual_query = os.getenv("PIPELINE_ENABLE_DUAL_QUERY")
        if enable_dual_query is not None:
            enable_dual_query_val = enable_dual_query.lower() in ("true", "1", "yes")
        else:
            val = _get_yaml("pipeline", "enable_dual_query")
            enable_dual_query_val = bool(val) if val is not None else True

        top_k = int(os.getenv("PIPELINE_TOP_K") or _get_yaml("pipeline", "top_k") or 5)
        max_reference_hops = int(
            os.getenv("PIPELINE_MAX_REF_HOPS")
            or _get_yaml("pipeline", "max_reference_hops")
            or 1
        )
        include_superseded_warning = os.getenv("PIPELINE_SUPERSEDED_WARNING")
        if include_superseded_warning is not None:
            include_superseded_warning_val = include_superseded_warning.lower() in (
                "true",
                "1",
                "yes",
            )
        else:
            val = _get_yaml("pipeline", "include_superseded_warning")
            include_superseded_warning_val = bool(val) if val is not None else True

        # 5. Multi-provider settings (Gemini, Groq, Cerebras, Cohere)
        raw_provider_order = (
            os.getenv("LLM_PROVIDER_ORDER")
            or _get_yaml("llm", "provider_order")
            or _get_yaml("llm", "providers_order")
        )
        if raw_provider_order:
            if isinstance(raw_provider_order, str):
                provider_order = tuple(
                    p.strip().lower()
                    for p in raw_provider_order.split(",")
                    if p.strip()
                )
            elif isinstance(raw_provider_order, (list, tuple)):
                provider_order = tuple(
                    str(p).strip().lower() for p in raw_provider_order if str(p).strip()
                )
            else:
                provider_order = ("gemini", "groq", "cerebras", "cohere")
        else:
            provider_order = ("gemini", "groq", "cerebras", "cohere")

        groq_model = (
            os.getenv("GROQ_MODEL")
            or _get_yaml("llm", "providers", "groq", "model")
            or "qwen/qwen3.8-27b"
        )
        cerebras_model = (
            os.getenv("CEREBRAS_MODEL")
            or _get_yaml("llm", "providers", "cerebras", "model")
            or "qwen-3.8-27b"
        )
        cohere_model = (
            os.getenv("COHERE_MODEL")
            or _get_yaml("llm", "providers", "cohere", "model")
            or "command-r-08-2024"
        )
        groq_endpoint = (
            os.getenv("GROQ_ENDPOINT")
            or _get_yaml("llm", "providers", "groq", "endpoint")
            or "https://api.groq.com/openai/v1"
        )
        cerebras_endpoint = (
            os.getenv("CEREBRAS_ENDPOINT")
            or _get_yaml("llm", "providers", "cerebras", "endpoint")
            or "https://api.cerebras.ai/v1"
        )
        cohere_endpoint = (
            os.getenv("COHERE_ENDPOINT")
            or _get_yaml("llm", "providers", "cohere", "endpoint")
            or "https://api.cohere.ai/compatibility/v1"
        )

        return cls(
            model_name=gemini_model,
            rewrite_model_name=rewrite_model,
            temperature_rewrite=temp_rewrite,
            temperature_generate=temp_generate,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            provider_order=provider_order,
            groq_model=groq_model,
            cerebras_model=cerebras_model,
            cohere_model=cohere_model,
            groq_endpoint=groq_endpoint,
            cerebras_endpoint=cerebras_endpoint,
            cohere_endpoint=cohere_endpoint,
            generator_use_local=generator_use_local,
            generator_local_endpoint=generator_local_endpoint,
            generator_local_model=generator_local_model,
            generator_local_temperature=generator_local_temp,
            generator_local_timeout=generator_local_timeout,
            generator_local_api_key=generator_local_api_key,
            rewriter_use_local=rewriter_use_local,
            rewriter_local_endpoint=rewriter_local_endpoint,
            rewriter_local_model=rewriter_local_model,
            rewriter_local_temperature=rewriter_local_temp,
            rewriter_local_timeout=rewriter_local_timeout,
            rewriter_local_api_key=rewriter_local_api_key,
            enable_query_rewrite=enable_query_rewrite_val,
            enable_dual_query=enable_dual_query_val,
            top_k=top_k,
            max_reference_hops=max_reference_hops,
            include_superseded_warning=include_superseded_warning_val,
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        )
