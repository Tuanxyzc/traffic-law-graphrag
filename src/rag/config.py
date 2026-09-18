"""RAG Configuration: models, dimensions, indexing, and fusion constants."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RAGConfig:
    """Immutable configuration dataclass for the Traditional RAG module."""

    # Embedding Model Settings (SentenceTransformers BAAI/bge-m3)
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 32

    # Neo4j Index & Constraint Identifiers
    vector_index_name: str = "semantic_unit_vector"
    fulltext_index_name: str = "semantic_unit_fulltext"
    constraint_name: str = "constraint_semanticunit_id_unique"

    # Search & RRF Parameters
    rrf_k: int = 60
    dense_weight: float = 1.0
    sparse_weight: float = 1.0
    default_top_k: int = 4
    min_candidate_k: int = 20

    # Layer 1 & Layer 2 Retrieval Defense Parameters
    min_similarity_threshold: float = 0.50
    enable_dynamic_k: bool = True
    relative_dropoff_ratio: float = 0.80
    max_score_gap: float = 0.15

    # Ingestion Settings
    ingest_batch_size: int = 50
    parsed_dir: str = os.getenv("PARSED_DIR", "data/parsed")

    @classmethod
    def from_env(cls) -> RAGConfig:
        """Instantiates RAGConfig overriding defaults with environment variables if present."""
        return cls(
            embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_dim=int(os.getenv("RAG_EMBEDDING_DIM", "1024")),
            embedding_batch_size=int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "32")),
            vector_index_name=os.getenv("RAG_VECTOR_INDEX", "semantic_unit_vector"),
            fulltext_index_name=os.getenv(
                "RAG_FULLTEXT_INDEX", "semantic_unit_fulltext"
            ),
            rrf_k=int(os.getenv("RAG_RRF_K", "60")),
            dense_weight=float(os.getenv("RAG_DENSE_WEIGHT", "1.0")),
            sparse_weight=float(os.getenv("RAG_SPARSE_WEIGHT", "1.0")),
            default_top_k=int(os.getenv("RAG_DEFAULT_TOP_K", "4")),
            min_candidate_k=int(os.getenv("RAG_MIN_CANDIDATE_K", "20")),
            min_similarity_threshold=float(
                os.getenv("RAG_MIN_SIMILARITY_THRESHOLD", "0.50")
            ),
            enable_dynamic_k=os.getenv("RAG_ENABLE_DYNAMIC_K", "true").lower()
            in ("true", "1", "yes"),
            relative_dropoff_ratio=float(
                os.getenv("RAG_RELATIVE_DROPOFF_RATIO", "0.80")
            ),
            max_score_gap=float(os.getenv("RAG_MAX_SCORE_GAP", "0.15")),
            ingest_batch_size=int(os.getenv("RAG_INGEST_BATCH_SIZE", "50")),
            parsed_dir=os.getenv("PARSED_DIR", "data/parsed"),
        )
