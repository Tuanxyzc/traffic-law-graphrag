"""API Configuration and environment settings."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class APISettings(BaseModel):
    """Configuration settings for the FastAPI server."""

    title: str = "Traffic Law GraphRAG API"
    version: str = "1.0.0"
    description: str = (
        "RESTful and Streaming API for Vietnamese Traffic Law GraphRAG system "
        "providing multi-query retrieval, Neo4j temporal graph validation, and grounded legal advice."
    )
    host: str = Field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("API_PORT", "8000")))
    debug: bool = Field(
        default_factory=lambda: os.getenv("API_DEBUG", "false").lower() in ("true", "1", "yes")
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            origin.strip()
            for origin in os.getenv("API_CORS_ORIGINS", "*").split(",")
            if origin.strip()
        ]
    )
    default_top_k: int = Field(default_factory=lambda: int(os.getenv("DEFAULT_TOP_K", "5")))
    max_top_k: int = Field(default_factory=lambda: int(os.getenv("MAX_TOP_K", "20")))


def get_api_settings() -> APISettings:
    """Returns singleton APISettings instance."""
    return APISettings()
