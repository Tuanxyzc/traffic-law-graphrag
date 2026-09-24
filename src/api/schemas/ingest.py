"""Pydantic schemas for Corpus Ingestion and Indexing endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    """Corpus batch ingestion request."""

    json_file_path: str = Field(
        ...,
        description="Path to JSON file containing parsed legal semantic units",
        examples=["data/corpus/168_2024_ND-CP.json"],
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Batch size for embedding generation and Neo4j writing",
    )
    recreate_index: bool = Field(
        default=False,
        description="Whether to drop and recreate vector/fulltext indexes before indexing",
    )


class IngestTaskStatusResponse(BaseModel):
    """Status of an asynchronous corpus ingestion task."""

    task_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    file_path: str
    total_units: int = 0
    processed_units: int = 0
    successful_units: int = 0
    failed_units: int = 0
    elapsed_seconds: float = 0.0
    error_message: str | None = None
