"""Unit tests for QueryRewriter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import requests  # type: ignore[import-untyped]

from src.extraction.key_manager import KeyManager
from src.pipeline.config import PipelineConfig
from src.pipeline.rewriter import QueryRewriter


def test_rewriter_empty_query() -> None:
    """Test that empty query is returned immediately without API calls."""
    config = PipelineConfig(enable_query_rewrite=True)
    rewriter = QueryRewriter(config=config)
    res = rewriter.rewrite("   ")
    assert res.original_query == ""
    assert res.search_query == ""
    assert res.identified_keywords == []


def test_rewriter_disabled_by_config() -> None:
    """Test that query rewriting can be bypassed via configuration."""
    config = PipelineConfig(enable_query_rewrite=False)
    rewriter = QueryRewriter(config=config)
    res = rewriter.rewrite("vượt đèn đỏ xe máy")
    assert res.original_query == "vượt đèn đỏ xe máy"
    assert res.search_query == "vượt đèn đỏ xe máy"
    assert res.identified_keywords == []


def test_rewriter_successful_call() -> None:
    """Test successful rewrite with valid JSON response from Gemini."""
    config = PipelineConfig(enable_query_rewrite=True)
    km = KeyManager(api_keys=["test-key-1"])
    mock_session = MagicMock(spec=requests.Session)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "search_query": "không chấp hành hiệu lệnh của đèn tín hiệu giao thông xe mô tô",
                                    "rule_query": "quy tắc tín hiệu giao thông đường bộ",
                                    "sanction_query": "mức phạt tiền trừ điểm giấy phép lái xe vượt đèn đỏ xe mô tô",
                                    "identified_keywords": [
                                        "đèn tín hiệu giao thông",
                                        "xe mô tô",
                                    ],
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, key_manager=km, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ xe máy")

    assert res.original_query == "vượt đèn đỏ xe máy"
    assert "không chấp hành hiệu lệnh" in res.search_query
    assert res.rule_query == "quy tắc tín hiệu giao thông đường bộ"
    assert "mức phạt tiền" in (res.sanction_query or "")
    assert "xe mô tô" in res.identified_keywords


def test_rewriter_key_rotation_on_429() -> None:
    """Test automatic key rotation when receiving HTTP 429."""
    config = PipelineConfig(enable_query_rewrite=True, max_retries=2)
    km = KeyManager(api_keys=["key-1", "key-2"], default_cooldown=10.0)
    mock_session = MagicMock(spec=requests.Session)

    # First call returns 429, second call returns 200
    resp_429 = MagicMock()
    resp_429.status_code = 429

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "search_query": "điều khiển phương tiện có nồng độ cồn",
                                    "identified_keywords": ["nồng độ cồn"],
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }

    mock_session.post.side_effect = [resp_429, resp_200]

    rewriter = QueryRewriter(config=config, key_manager=km, session=mock_session)
    res = rewriter.rewrite("uống rượu lái xe")

    assert mock_session.post.call_count == 2
    assert "nồng độ cồn" in res.search_query


def test_rewriter_fallback_on_network_error() -> None:
    """Test fallback to original query when API requests fail."""
    config = PipelineConfig(enable_query_rewrite=True, max_retries=1)
    km = KeyManager(api_keys=["test-key"])
    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = requests.RequestException("Connection timed out")

    rewriter = QueryRewriter(config=config, key_manager=km, session=mock_session)
    res = rewriter.rewrite("chạy quá tốc độ")

    assert res.original_query == "chạy quá tốc độ"
    assert res.search_query == "chạy quá tốc độ"
    assert res.identified_keywords == []


def test_rewriter_document_amendment_intent() -> None:
    """Test classification of document amendment intent and extraction of document IDs."""
    config = PipelineConfig(enable_query_rewrite=True)
    km = KeyManager(api_keys=["test-key-1"])
    mock_session = MagicMock(spec=requests.Session)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "intent": "document_amendment",
                                    "source_doc": "238",
                                    "target_doc": "168",
                                    "search_query": "Nghị định 238 sửa đổi bổ sung các điều khoản trong Nghị định 168",
                                    "identified_keywords": [
                                        "sửa đổi",
                                        "Nghị định 238",
                                        "Nghị định 168",
                                    ],
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, key_manager=km, session=mock_session)
    res = rewriter.rewrite(
        "những điều khoản nào trong nghị định 168 đã được sửa đổi bởi ND 238"
    )

    assert res.intent == "document_amendment"
    assert res.source_doc == "238_2026_ND-CP"
    assert res.target_doc == "168_2024_ND-CP"
    assert "Nghị định 238" in res.search_query


def test_rewriter_deterministic_doc_extraction() -> None:
    """Test deterministic document and intent extraction when LLM is bypassed or fails."""
    from src.pipeline.rewriter import extract_document_intent_and_numbers

    # Case 1: Passive 'bởi ND 238'
    intent, src, tgt = extract_document_intent_and_numbers(
        "những điều khoản nào trong nghị định 168 đã được sửa đổi bởi ND 238"
    )
    assert intent == "document_amendment"
    assert src == "238_2026_ND-CP"
    assert tgt == "168_2024_ND-CP"

    # Case 2: Active 'ND 238 sửa đổi ND 168'
    intent2, src2, tgt2 = extract_document_intent_and_numbers(
        "Nghị định 238 sửa đổi bổ sung những gì trong Nghị định 168"
    )
    assert intent2 == "document_amendment"
    assert src2 == "238_2026_ND-CP"
    assert tgt2 == "168_2024_ND-CP"

    # Case 3: Standard violation query
    intent3, src3, tgt3 = extract_document_intent_and_numbers(
        "vượt đèn đỏ xe máy phạt bao nhiêu"
    )
    assert intent3 == "violation_sanction"
    assert src3 is None
    assert tgt3 is None


def test_rewriter_system_meta_query_intent() -> None:
    """Test deterministic identification of system meta query intent."""
    from src.pipeline.rewriter import extract_document_intent_and_numbers

    # Case 1: User asks for known documents
    intent1, _, _ = extract_document_intent_and_numbers(
        "Liệt kê Các luật,nghị định mà bạn nắm rõ"
    )
    assert intent1 == "system_meta_query"

    # Case 2: User asks about system database
    intent2, _, _ = extract_document_intent_and_numbers(
        "Hệ thống có những văn bản nào trong cơ sở dữ liệu?"
    )
    assert intent2 == "system_meta_query"


def test_rewriter_check_bypass_rewrite() -> None:
    """Test conditional bypass of LLM rewrite for meta-queries and exact citation requests."""
    from src.pipeline.rewriter import check_bypass_rewrite

    # 1. Meta-query bypass
    bypass1, rq1 = check_bypass_rewrite("Liệt kê Các luật,nghị định mà bạn nắm rõ")
    assert bypass1 is True
    assert rq1 is not None
    assert rq1.intent == "system_meta_query"
    assert rq1.search_query == "Liệt kê Các luật,nghị định mà bạn nắm rõ"

    # 2. Direct statutory quote query bypass
    bypass2, rq2 = check_bypass_rewrite("Trích toàn bộ điều 1 của ND168")
    assert bypass2 is True
    assert rq2 is not None
    assert rq2.intent == "general_rule"
    assert "Trích toàn bộ điều 1 của ND168" in rq2.search_query

    # 3. Colloquial query should NOT be bypassed
    bypass3, rq3 = check_bypass_rewrite("uống rượu lái xe bị phạt bao nhiêu tiền")
    assert bypass3 is False
    assert rq3 is None
