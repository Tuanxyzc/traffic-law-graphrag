"""Pydantic data models for Traditional RAG: chunk metadata, retrieved results, and ingestion stats."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChunkMetadata(BaseModel):
    """Metadata representing the structural and temporal position of a legal semantic unit."""

    document_id: str = Field(
        description="Normalized document identifier, e.g., '168_2024_ND-CP'"
    )
    dieu: str = Field(description="Article number or code, e.g., '5'")
    khoan: str | None = Field(
        default=None, description="Clause number if applicable, e.g., '1'"
    )
    diem: str | None = Field(
        default=None, description="Point letter if applicable, e.g., 'a'"
    )
    tieu_de_dieu: str | None = Field(
        default=None, description="Title of the containing article"
    )
    chuong: str | None = Field(
        default=None, description="Chapter Roman numeral, e.g., 'II'"
    )
    tieu_de_chuong: str | None = Field(default=None, description="Chapter title")
    level: int = Field(
        default=4, description="Hierarchy level: 4 for Point, 3 for Clause"
    )
    hieu_luc_tu: str | None = Field(
        default=None, description="Effective date in ISO format if known"
    )


class RetrievedChunk(BaseModel):
    """A single retrieved legal semantic unit enriched with dense, sparse, and fused RRF scores."""

    id: str = Field(
        description="Canonical SemanticUnit ID, matches Graph node ID exactly"
    )
    text: str = Field(
        description="Full metadata-enriched legal text containing hierarchy preamble"
    )
    raw_text: str | None = Field(
        default=None,
        description="Original raw standardized legal text without metadata headers",
    )
    score: float = Field(description="Combined Reciprocal Rank Fusion (RRF) score")
    dense_score: float | None = Field(
        default=None, description="Cosine similarity score from vector index"
    )
    dense_rank: int | None = Field(
        default=None, description="1-based rank in dense vector retrieval"
    )
    sparse_score: float | None = Field(
        default=None, description="BM25 score from fulltext index"
    )
    sparse_rank: int | None = Field(
        default=None, description="1-based rank in sparse fulltext retrieval"
    )
    metadata: ChunkMetadata = Field(
        description="Structural and contextual metadata of the unit"
    )


class RetrievalResult(BaseModel):
    """Aggregated retrieval response containing ranked candidate chunks and execution latency."""

    query: str = Field(description="Original user search query")
    top_k: int = Field(description="Requested number of top candidate chunks")
    chunks: list[RetrievedChunk] = Field(
        default_factory=list, description="Ranked list of retrieved chunks"
    )
    execution_time_ms: float = Field(
        default=0.0, description="Total retrieval duration in milliseconds"
    )


class IngestionStats(BaseModel):
    """Statistics summarizing a corpus indexing run into Neo4j."""

    total_documents: int = 0
    total_units: int = 0
    indexed_units: int = 0
    failed_units: int = 0
    vector_index_status: str = "UNKNOWN"
    fulltext_index_status: str = "UNKNOWN"
    elapsed_seconds: float = 0.0
