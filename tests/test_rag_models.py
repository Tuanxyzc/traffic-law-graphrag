"""Tests for RAG models and configurations."""

from src.rag.config import RAGConfig
from src.rag.models import (
    ChunkMetadata,
    IngestionStats,
    RetrievalResult,
    RetrievedChunk,
)


def test_rag_config_defaults() -> None:
    config = RAGConfig()
    assert config.embedding_model == "BAAI/bge-m3"
    assert config.embedding_dim == 1024
    assert config.rrf_k == 60
    assert config.dense_weight == 1.0
    assert config.sparse_weight == 1.0
    assert config.vector_index_name == "semantic_unit_vector"
    assert config.fulltext_index_name == "semantic_unit_fulltext"


def test_chunk_metadata_serialization() -> None:
    meta = ChunkMetadata(
        document_id="168_2024_ND-CP",
        dieu="5",
        khoan="1",
        diem="a",
        tieu_de_dieu="Xử phạt vi phạm",
        chuong="II",
        level=4,
    )
    dumped = meta.model_dump()
    assert dumped["document_id"] == "168_2024_ND-CP"
    assert dumped["dieu"] == "5"
    assert dumped["khoan"] == "1"
    assert dumped["diem"] == "a"
    assert dumped["level"] == 4


def test_retrieved_chunk_creation() -> None:
    meta = ChunkMetadata(document_id="168_2024_ND-CP", dieu="5")
    chunk = RetrievedChunk(
        id="168_2024_ND-CP_D5_K1_Da",
        text="Điều 5. Khoản 1: a) Vượt đèn đỏ",
        score=0.032,
        dense_score=0.88,
        dense_rank=1,
        sparse_score=14.5,
        sparse_rank=2,
        metadata=meta,
    )
    assert chunk.id == "168_2024_ND-CP_D5_K1_Da"
    assert chunk.dense_rank == 1
    assert chunk.sparse_rank == 2
    assert chunk.score == 0.032


def test_retrieval_result() -> None:
    res = RetrievalResult(
        query="vượt đèn đỏ phạt bao nhiêu",
        top_k=2,
        chunks=[],
        execution_time_ms=12.5,
    )
    assert res.query == "vượt đèn đỏ phạt bao nhiêu"
    assert res.top_k == 2
    assert res.execution_time_ms == 12.5
    assert len(res.chunks) == 0


def test_ingestion_stats() -> None:
    stats = IngestionStats(
        total_documents=1,
        total_units=50,
        indexed_units=50,
        vector_index_status="ONLINE",
        fulltext_index_status="ONLINE",
    )
    assert stats.total_units == 50
    assert stats.indexed_units == 50
    assert stats.failed_units == 0
