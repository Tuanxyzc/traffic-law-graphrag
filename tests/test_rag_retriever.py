"""Tests for HybridRetriever and Reciprocal Rank Fusion (RRF)."""

from unittest.mock import MagicMock

import pytest

from src.rag.config import RAGConfig
from src.rag.retriever import HybridRetriever, sanitize_lucene_query


def test_sanitize_lucene_query() -> None:
    assert sanitize_lucene_query("") == ""
    assert sanitize_lucene_query("   ") == ""

    # Check escaping of slash, colon, parens, question mark
    query = "Nghị định 168/2024/NĐ-CP: Điều 5 (khoản 1)?"
    sanitized = sanitize_lucene_query(query)
    assert r"\/" in sanitized
    assert r"\:" in sanitized
    assert r"\(" in sanitized
    assert r"\)" in sanitized
    assert r"\?" in sanitized


def test_fuse_rrf_scoring() -> None:
    config = RAGConfig(rrf_k=60, dense_weight=1.0, sparse_weight=1.0)
    retriever = HybridRetriever(config=config)

    dense_results = [
        {
            "id": "doc_A",
            "text": "Text A",
            "dense_score": 0.95,
            "document_id": "168",
            "dieu": "5",
        },
        {
            "id": "doc_B",
            "text": "Text B",
            "dense_score": 0.85,
            "document_id": "168",
            "dieu": "6",
        },
    ]
    sparse_results = [
        {
            "id": "doc_B",
            "text": "Text B",
            "sparse_score": 12.0,
            "document_id": "168",
            "dieu": "6",
        },
        {
            "id": "doc_C",
            "text": "Text C",
            "sparse_score": 8.0,
            "document_id": "168",
            "dieu": "7",
        },
    ]

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=3)
    assert len(fused) == 3

    # doc_B is in dense (rank 2) AND sparse (rank 1):
    # RRF score = 1/(60+2) + 1/(60+1) = 1/62 + 1/61 = 0.016129 + 0.016393 = 0.032522
    # doc_A is in dense only (rank 1): 1/61 = 0.016393
    # doc_C is in sparse only (rank 2): 1/62 = 0.016129
    # Therefore, doc_B must be rank 1 in fused results!
    assert fused[0].id == "doc_B"
    assert fused[0].dense_rank == 2
    assert fused[0].sparse_rank == 1
    assert fused[0].score == pytest.approx(round(1 / 62 + 1 / 61, 6))

    assert fused[1].id == "doc_A"
    assert fused[1].dense_rank == 1
    assert fused[1].sparse_rank is None

    assert fused[2].id == "doc_C"
    assert fused[2].dense_rank is None
    assert fused[2].sparse_rank == 2


def test_fuse_rrf_top_k_slice() -> None:
    config = RAGConfig(rrf_k=60)
    retriever = HybridRetriever(config=config)

    dense_results = [{"id": f"doc_{i}", "text": f"T{i}"} for i in range(10)]
    sparse_results: list[dict] = []

    fused = retriever._fuse_rrf(dense_results, sparse_results, top_k=3)
    assert len(fused) == 3
    assert [c.id for c in fused] == ["doc_0", "doc_1", "doc_2"]


def test_retrieve_empty_query() -> None:
    retriever = HybridRetriever()
    res = retriever.retrieve("")
    assert res.query == ""
    assert len(res.chunks) == 0
    assert res.execution_time_ms == 0.0


def test_retrieve_mocked() -> None:
    config = RAGConfig(rrf_k=60)

    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    mock_emb = MagicMock()
    mock_emb.embed_query.return_value = [0.1] * 1024

    # Dense query returns doc_1, fulltext returns doc_1 and doc_2
    mock_session.run.side_effect = [
        # 1st call: vector query
        [
            {
                "id": "doc_1",
                "text": "Text 1",
                "document_id": "168",
                "dieu": "5",
                "dense_score": 0.9,
            }
        ],
        # 2nd call: fulltext query
        [
            {
                "id": "doc_1",
                "text": "Text 1",
                "document_id": "168",
                "dieu": "5",
                "sparse_score": 10.0,
            },
            {
                "id": "doc_2",
                "text": "Text 2",
                "document_id": "168",
                "dieu": "6",
                "sparse_score": 5.0,
            },
        ],
    ]

    retriever = HybridRetriever(
        client=mock_client,
        embedding_manager=mock_emb,
        config=config,
    )

    result = retriever.retrieve("vượt đèn đỏ ô tô", top_k=2)

    assert result.query == "vượt đèn đỏ ô tô"
    assert result.top_k == 2
    assert len(result.chunks) == 2
    assert result.chunks[0].id == "doc_1"
    assert result.chunks[0].dense_rank == 1
    assert result.chunks[0].sparse_rank == 1
    assert result.chunks[1].id == "doc_2"
    assert result.execution_time_ms >= 0.0
