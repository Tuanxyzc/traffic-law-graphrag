"""Unit and integration tests for Layer 1 Floor Threshold and Layer 2 Dynamic-K Pruning."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.pipeline.models import EvidencePackage, GenerationResult
from src.pipeline.pipeline import GraphRAGPipeline
from src.rag.config import RAGConfig
from src.rag.models import RetrievalResult
from src.rag.retriever import HybridRetriever


def test_layer1_floor_threshold_pruning() -> None:
    """When Top-1 dense_score is below min_similarity_threshold, _fuse_rrf returns empty list."""
    config = RAGConfig(min_similarity_threshold=0.50)
    retriever = HybridRetriever(config=config)

    # Simulated off-topic query results with low semantic similarity
    dense_results = [
        {"id": "doc_1", "text": "Traffic law text", "dense_score": 0.42},
        {"id": "doc_2", "text": "Another law text", "dense_score": 0.38},
    ]
    sparse_results = [
        {"id": "doc_1", "text": "Traffic law text", "sparse_score": 5.0},
    ]

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=5)
    assert len(fused) == 0


def test_layer1_floor_threshold_boundary() -> None:
    """When Top-1 dense_score equals or exceeds min_similarity_threshold, candidates are retained."""
    config = RAGConfig(min_similarity_threshold=0.50)
    retriever = HybridRetriever(config=config)

    dense_results = [
        {"id": "doc_1", "text": "Traffic law text", "dense_score": 0.50},
        {"id": "doc_2", "text": "Another law text", "dense_score": 0.49},
    ]
    sparse_results: list[dict[str, Any]] = []

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=5)
    assert len(fused) >= 1
    assert fused[0].id == "doc_1"


def test_layer1_retrieve_early_exit_skips_fulltext() -> None:
    """HybridRetriever.retrieve() early exits without running fulltext search when Top-1 < threshold."""
    config = RAGConfig(min_similarity_threshold=0.50)
    retriever = HybridRetriever(config=config)

    # Mock embedding manager
    retriever.embedding_manager = MagicMock()
    retriever.embedding_manager.embed_query.return_value = [0.1] * 1024

    # Mock Neo4j client and session
    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session
    retriever.client = mock_client

    # Mock _query_vector returning low-similarity result
    retriever._query_vector = MagicMock(  # type: ignore[method-assign]
        return_value=[{"id": "doc_1", "text": "Some text", "dense_score": 0.35}]
    )
    retriever._query_fulltext = MagicMock()  # type: ignore[method-assign]

    res = retriever.retrieve("công thức nấu phở")

    assert len(res.chunks) == 0
    assert res.query == "công thức nấu phở"
    retriever._query_vector.assert_called_once()
    retriever._query_fulltext.assert_not_called()


def test_layer2_dynamic_k_relative_dropoff_pruning() -> None:
    """Trailing candidates with steep dense_score drop-off are pruned."""
    config = RAGConfig(
        min_similarity_threshold=0.50,
        enable_dynamic_k=True,
        relative_dropoff_ratio=0.80,
        max_score_gap=0.15,
    )
    retriever = HybridRetriever(config=config)

    # Top-1 is 0.80.
    # relative_dropoff: 0.80 * 0.80 = 0.64
    # max_score_gap: 0.80 - 0.15 = 0.65
    # min_allowed_dense = max(0.64, 0.65) = 0.65
    dense_results = [
        {"id": "doc_top", "text": "Top relevant chunk", "dense_score": 0.80},
        {"id": "doc_close", "text": "Close candidate", "dense_score": 0.75},
        {"id": "doc_dropped", "text": "Distant candidate", "dense_score": 0.63},
        {"id": "doc_far", "text": "Far candidate", "dense_score": 0.52},
    ]
    sparse_results: list[dict[str, Any]] = []

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=5)
    retained_ids = [c.id for c in fused]

    assert "doc_top" in retained_ids
    assert "doc_close" in retained_ids
    assert "doc_dropped" not in retained_ids
    assert "doc_far" not in retained_ids
    assert len(fused) == 2


def test_layer2_dynamic_k_preserves_at_least_one_chunk() -> None:
    """Dynamic-K always preserves at least the top-1 candidate even if all trailing drop off."""
    config = RAGConfig(
        min_similarity_threshold=0.50,
        enable_dynamic_k=True,
        relative_dropoff_ratio=0.80,
        max_score_gap=0.15,
    )
    retriever = HybridRetriever(config=config)

    dense_results = [
        {"id": "doc_only", "text": "Only relevant", "dense_score": 0.60},
        {"id": "doc_steep", "text": "Steep drop", "dense_score": 0.30},
    ]
    sparse_results: list[dict[str, Any]] = []

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=5)
    assert len(fused) == 1
    assert fused[0].id == "doc_only"


def test_layer2_dynamic_k_disabled() -> None:
    """When enable_dynamic_k is False, all top_k candidates are retained."""
    config = RAGConfig(
        min_similarity_threshold=0.50,
        enable_dynamic_k=False,
    )
    retriever = HybridRetriever(config=config)

    dense_results = [
        {"id": "doc_1", "text": "T1", "dense_score": 0.90},
        {"id": "doc_2", "text": "T2", "dense_score": 0.55},
        {"id": "doc_3", "text": "T3", "dense_score": 0.51},
    ]
    sparse_results: list[dict[str, Any]] = []

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=3)
    assert len(fused) == 3


def test_layer2_dynamic_k_preserves_sparse_candidate() -> None:
    """Sparse-only candidate without dense_score is preserved if Top-1 dense is valid."""
    config = RAGConfig(
        min_similarity_threshold=0.50,
        enable_dynamic_k=True,
        relative_dropoff_ratio=0.80,
        max_score_gap=0.15,
    )
    retriever = HybridRetriever(config=config)

    dense_results = [
        {"id": "doc_dense", "text": "Dense hit", "dense_score": 0.85},
    ]
    sparse_results = [
        {"id": "doc_dense", "text": "Dense hit", "sparse_score": 10.0},
        {"id": "doc_sparse", "text": "Keyword exact match", "sparse_score": 12.0},
    ]

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=5)
    retained_ids = [c.id for c in fused]
    assert "doc_dense" in retained_ids
    assert "doc_sparse" in retained_ids


def test_pipeline_zero_context_flow() -> None:
    """Integration: Empty chunks from Layer 1 bypass graph validation and generate conversational response."""
    mock_rewriter = MagicMock()
    mock_rewriter.rewrite.return_value = MagicMock(
        intent="violation_sanction",
        search_query="xin chào bạn",
        rule_query=None,
        sanction_query=None,
        source_doc=None,
        target_doc=None,
    )

    # Retriever returns 0 chunks (simulating Layer 1 drop)
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = RetrievalResult(
        query="xin chào bạn",
        top_k=5,
        chunks=[],
        execution_time_ms=5.0,
    )

    mock_validator = MagicMock()
    mock_generator = MagicMock()
    mock_generator.generate.return_value = GenerationResult(
        answer="Xin chào bạn! Tôi là Trợ lý AI Cố vấn Pháp luật Giao thông Đường bộ Việt Nam.",
        citations=[],
    )

    pipeline = GraphRAGPipeline(
        rewriter=mock_rewriter,
        retriever=mock_retriever,
        validator=mock_validator,
        generator=mock_generator,
    )

    result = pipeline.run("Xin chào bạn")

    # 1. Graph validation was bypassed completely
    mock_validator.validate_provisions.assert_not_called()

    # 2. Generator received empty evidence package
    called_package: EvidencePackage = mock_generator.generate.call_args[0][0]
    assert len(called_package.items) == 0
    assert len(called_package.document_amendments) == 0

    # 3. Answer returned naturally with 0 citations
    assert "Trợ lý AI Cố vấn Pháp luật Giao thông" in result.answer
    assert result.citations == []
    assert result.execution_time_ms > 0.0
