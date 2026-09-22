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


def test_compute_lexical_density() -> None:
    from src.rag.retriever import compute_lexical_density

    assert compute_lexical_density("", "Nội dung điều luật") == 0.0
    assert compute_lexical_density("vượt đèn đỏ", "") == 0.0

    # No overlapping words
    score_zero = compute_lexical_density("nấu phở bò", "Xử phạt vi phạm giao thông")
    assert score_zero == 0.0

    # Partial match
    score_partial = compute_lexical_density("vượt đèn đỏ ô tô", "Phạt người đi bộ vượt đèn đỏ")
    # Full match
    score_full = compute_lexical_density("vượt đèn đỏ ô tô", "Phạt người điều khiển xe ô tô vượt đèn đỏ")

    assert score_full > score_partial > 0.0

    # Traffic light query should score traffic light chunk higher than overtaking chunk
    score_light = compute_lexical_density(
        "vượt đèn đỏ xe máy",
        "Xử phạt người điều khiển xe mô tô, xe gắn máy không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
    )
    score_overtake = compute_lexical_density(
        "vượt đèn đỏ xe máy",
        "Xử phạt người điều khiển xe mô tô vượt xe trong các trường hợp không được vượt",
    )
    assert score_light > score_overtake


def test_query_articles_fulltext() -> None:
    mock_session = MagicMock()
    mock_session.run.return_value = [
        {"id": "168_2024_ND-CP_D5", "title": "Điều 5", "content": "Nội dung Điều 5", "number": "5", "score": 14.5},
        {"id": "168_2024_ND-CP_D6", "title": "Điều 6", "content": "Nội dung Điều 6", "number": "6", "score": 9.2},
    ]

    retriever = HybridRetriever()
    articles = retriever._query_articles_fulltext(
        session=mock_session,
        query_text="vượt đèn đỏ",
        candidate_k=5,
    )

    assert len(articles) == 2
    assert articles[0]["id"] == "168_2024_ND-CP_D5"
    assert articles[0]["article_rank"] == 1
    assert articles[1]["id"] == "168_2024_ND-CP_D6"
    assert articles[1]["article_rank"] == 2


def test_expand_and_filter_article_units() -> None:
    mock_session = MagicMock()
    # Traversal returns 4 semantic units for Article D5
    mock_session.run.return_value = [
        {
            "article_id": "168_2024_ND-CP_D5",
            "id": "168_2024_ND-CP_D5_K1",
            "text": "Phạt tiền từ 200.000 đến 400.000 đồng...",
            "raw_text": "Phạt tiền từ 200.000 đến 400.000 đồng...",
            "document_id": "168_2024_ND-CP",
            "dieu": "5",
            "khoan": "1",
            "diem": None,
            "tieu_de_dieu": "Điều 5",
            "chuong": "II",
            "tieu_de_chuong": "XỬ PHẠT",
            "level": 3,
            "hieu_luc_tu": None,
        },
        {
            "article_id": "168_2024_ND-CP_D5",
            "id": "168_2024_ND-CP_D5_K5_Da",
            "text": "Phạt tiền người lái ô tô vượt đèn đỏ tín hiệu...",
            "raw_text": "Phạt tiền người lái ô tô vượt đèn đỏ tín hiệu...",
            "document_id": "168_2024_ND-CP",
            "dieu": "5",
            "khoan": "5",
            "diem": "a",
            "tieu_de_dieu": "Điều 5",
            "chuong": "II",
            "tieu_de_chuong": "XỬ PHẠT",
            "level": 4,
            "hieu_luc_tu": None,
        },
        {
            "article_id": "168_2024_ND-CP_D5",
            "id": "168_2024_ND-CP_D5_K2",
            "text": "Phạt hành vi bấm còi trong đô thị...",
            "raw_text": "Phạt hành vi bấm còi trong đô thị...",
            "document_id": "168_2024_ND-CP",
            "dieu": "5",
            "khoan": "2",
            "diem": None,
            "tieu_de_dieu": "Điều 5",
            "chuong": "II",
            "tieu_de_chuong": "XỬ PHẠT",
            "level": 3,
            "hieu_luc_tu": None,
        },
    ]

    articles = [
        {"id": "168_2024_ND-CP_D5", "article_score": 15.0, "article_rank": 1}
    ]

    retriever = HybridRetriever()
    selected = retriever._expand_and_filter_article_units(
        session=mock_session,
        articles=articles,
        query_text="vượt đèn đỏ ô tô",
        top_k_per_article=2,
    )

    # We requested top 2 units out of 3:
    assert len(selected) == 2
    # D5_K5_Da has full match on "vượt đèn đỏ ô tô", so it must be rank 1:
    assert selected[0]["id"] == "168_2024_ND-CP_D5_K5_Da"
    assert selected[0]["sparse_rank"] == 1
    assert selected[0]["sparse_score"] == 15.0
    # Next best is rank 2:
    assert selected[1]["sparse_rank"] == 2


def test_retrieve_hierarchical_mocked() -> None:
    config = RAGConfig(rrf_k=60)

    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    mock_emb = MagicMock()
    mock_emb.embed_query.return_value = [0.1] * 1024

    # 1st call: Vector search over SemanticUnits
    # 2nd call: Fulltext search over Articles
    # 3rd call: Graph traversal expanding Article -> SemanticUnits
    mock_session.run.side_effect = [
        # Call 1: Vector search
        [
            {
                "id": "doc_1",
                "text": "Text 1",
                "document_id": "168",
                "dieu": "5",
                "dense_score": 0.9,
            }
        ],
        # Call 2: Article fulltext search
        [
            {
                "id": "art_1",
                "title": "Điều 5",
                "content": "Nội dung Điều 5",
                "number": "5",
                "score": 10.0,
            }
        ],
        # Call 3: Graph traversal
        [
            {
                "article_id": "art_1",
                "id": "doc_1",
                "text": "Text 1 vượt đèn đỏ",
                "raw_text": "Text 1 vượt đèn đỏ",
                "document_id": "168",
                "dieu": "5",
                "level": 4,
            },
            {
                "article_id": "art_1",
                "id": "doc_2",
                "text": "Text 2",
                "raw_text": "Text 2",
                "document_id": "168",
                "dieu": "5",
                "level": 4,
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


def test_retrieve_fallback_when_no_articles() -> None:
    config = RAGConfig(rrf_k=60)

    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    mock_emb = MagicMock()
    mock_emb.embed_query.return_value = [0.1] * 1024

    # Call 1: Vector search returns doc_1
    # Call 2: Article fulltext returns []
    # Call 3: Fallback direct semantic unit fulltext returns doc_2
    mock_session.run.side_effect = [
        # Call 1: Vector search
        [
            {
                "id": "doc_1",
                "text": "Text 1",
                "document_id": "168",
                "dieu": "5",
                "dense_score": 0.9,
            }
        ],
        # Call 2: Article fulltext (empty)
        [],
        # Call 3: Fallback direct fulltext
        [
            {
                "id": "doc_2",
                "text": "Text 2",
                "document_id": "168",
                "dieu": "6",
                "sparse_score": 8.0,
            }
        ],
    ]

    retriever = HybridRetriever(
        client=mock_client,
        embedding_manager=mock_emb,
        config=config,
    )

    result = retriever.retrieve("vượt đèn đỏ ô tô", top_k=2)

    assert len(result.chunks) == 2
    assert result.chunks[0].id == "doc_1"
    assert result.chunks[1].id == "doc_2"
