"""Pipeline configuration dataclass for GraphRAG."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration settings for the GraphRAG pipeline."""

    # Gemini LLM Settings
    model_name: str = "gemini-2.5-flash"
    rewrite_model_name: str = "gemini-2.5-flash"
    temperature_rewrite: float = 0.1
    temperature_generate: float = 0.2
    max_retries: int = 5
    timeout_seconds: float = 60.0

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
    def from_env(cls) -> PipelineConfig:
        """Instantiates PipelineConfig overriding defaults with environment variables."""
        return cls(
            model_name=os.getenv(
                "GEMINI_MODEL", os.getenv("PIPELINE_MODEL", "gemini-2.5-flash")
            ),
            rewrite_model_name=os.getenv(
                "PIPELINE_REWRITE_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            ),
            temperature_rewrite=float(os.getenv("PIPELINE_TEMP_REWRITE", "0.1")),
            temperature_generate=float(os.getenv("PIPELINE_TEMP_GENERATE", "0.2")),
            max_retries=int(os.getenv("PIPELINE_MAX_RETRIES", "5")),
            timeout_seconds=float(os.getenv("PIPELINE_TIMEOUT", "60.0")),
            enable_query_rewrite=os.getenv("PIPELINE_ENABLE_REWRITE", "true").lower()
            in ("true", "1", "yes"),
            enable_dual_query=os.getenv("PIPELINE_ENABLE_DUAL_QUERY", "true").lower()
            in ("true", "1", "yes"),
            top_k=int(os.getenv("PIPELINE_TOP_K", "5")),
            max_reference_hops=int(os.getenv("PIPELINE_MAX_REF_HOPS", "1")),
            include_superseded_warning=os.getenv(
                "PIPELINE_SUPERSEDED_WARNING", "true"
            ).lower()
            in ("true", "1", "yes"),
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        )
