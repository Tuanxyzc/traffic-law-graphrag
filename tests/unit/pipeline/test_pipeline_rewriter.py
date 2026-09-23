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


def test_rewriter_local_llm_call() -> None:
    """Test query rewriting using Localhost LLM OpenAI-compatible endpoint."""
    config = PipelineConfig(
        enable_query_rewrite=True,
        rewriter_use_local=True,
        rewriter_local_endpoint="http://localhost:11434/v1",
        rewriter_local_model="Qwen2.5:1.5b",
    )
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "search_query": "mức phạt người điều khiển xe mô tô vượt đèn đỏ",
                            "rule_query": "quy tắc chấp hành hiệu lệnh đèn giao thông xe máy",
                            "sanction_query": "mức tiền phạt trừ điểm giấy phép lái xe vượt đèn đỏ xe mô tô",
                            "identified_keywords": ["vượt đèn đỏ", "xe mô tô"],
                        }
                    )
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ xe máy")

    assert res.original_query == "vượt đèn đỏ xe máy"
    assert "mức phạt người điều khiển xe mô tô" in res.search_query
    assert "quy tắc chấp hành hiệu lệnh" in (res.rule_query or "")
    assert "mức tiền phạt" in (res.sanction_query or "")
    assert "vượt đèn đỏ" in res.identified_keywords

    called_url = mock_session.post.call_args[0][0]
    assert "http://localhost:11434/v1/chat/completions" in called_url


def test_rewriter_local_llm_failure_fallback() -> None:
    """Test graceful fallback to original query when Local LLM endpoint fails."""
    config = PipelineConfig(
        enable_query_rewrite=True,
        rewriter_use_local=True,
        rewriter_local_endpoint="http://localhost:11434/v1",
    )
    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = requests.ConnectionError("Connection refused")

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ xe máy")

    assert res.original_query == "vượt đèn đỏ xe máy"
    assert res.search_query == "vượt đèn đỏ xe máy"
    assert res.rule_query is None
    assert res.sanction_query is None


def test_rewriter_null_values_in_json() -> None:
    """Test that null values in JSON response (e.g. search_query: null) do not cause AttributeError: 'NoneType' has no attribute 'strip'."""
    config = PipelineConfig(
        enable_query_rewrite=True,
        rewriter_use_local=True,
    )
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "search_query": None,
                            "rule_query": None,
                            "sanction_query": None,
                            "identified_keywords": None,
                            "intent": None,
                        }
                    )
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ xe máy")

    assert res.original_query == "vượt đèn đỏ xe máy"
    # Should safely fallback search_query to clean original query
    assert res.search_query == "vượt đèn đỏ xe máy"
    assert res.rule_query is None
    assert res.sanction_query is None
    assert res.identified_keywords == []


def test_rewriter_null_message_content() -> None:
    """Test that null content in message choices safely triggers fallback without crashing."""
    config = PipelineConfig(
        enable_query_rewrite=True,
        rewriter_use_local=True,
    )
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": None}}]}
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ")

    assert res.original_query == "vượt đèn đỏ"
    assert res.search_query == "vượt đèn đỏ"
    assert res.rule_query is None


def test_rewriter_json_with_trailing_commas() -> None:
    """Test that JSON with trailing commas produced by small local LLMs is gracefully repaired."""
    config = PipelineConfig(
        enable_query_rewrite=True,
        rewriter_use_local=True,
    )
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Imperfect JSON with trailing comma
    imperfect_json = """
    {
        "search_query": "mức phạt xe máy vượt đèn đỏ",
        "rule_query": "quy tắc đèn giao thông",
        "sanction_query": "mức phạt tiền xe máy",
    }
    """
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": imperfect_json}}]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ xe máy")

    assert res.search_query == "mức phạt xe máy vượt đèn đỏ"
    assert res.rule_query == "quy tắc đèn giao thông"
    assert res.sanction_query == "mức phạt tiền xe máy"


def test_normalize_colloquial_terms() -> None:
    """Test standardizing colloquial traffic phrases into formal legal terminology."""
    from src.pipeline.rewriter import normalize_colloquial_terms

    res = normalize_colloquial_terms("vượt đèn đỏ ở xe máy")
    assert "không chấp hành hiệu lệnh của đèn tín hiệu giao thông" in res
    assert "xe mô tô, xe gắn máy" in res

    res_alcohol = normalize_colloquial_terms("uống rượu lái xe")
    assert "nồng độ cồn" in res_alcohol

    assert normalize_colloquial_terms("") == ""
    assert normalize_colloquial_terms(None) == ""


def test_rewriter_llm_reasoning_csgt_sanction_and_constraints() -> None:
    """Test LLM reasoning for CSGT query generating discriminative constraints and vehicle targets."""
    config = PipelineConfig(enable_query_rewrite=True, rewriter_use_local=True)
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    llm_payload = {
        "intent": "violation_sanction",
        "search_query": "không chấp hành hiệu lệnh chỉ dẫn của người điều khiển giao thông",
        "rule_query": "chấp hành hiệu lệnh của người điều khiển giao thông",
        "sanction_query": "mức phạt tiền trừ điểm giấy phép lái xe hành vi không chấp hành hiệu lệnh người điều khiển giao thông",
        "identified_keywords": ["người điều khiển giao thông", "hiệu lệnh", "xử phạt"],
        "must_have_terms": ["người điều khiển giao thông"],
        "must_not_have_terms": ["đèn tín hiệu", "biển báo hiệu", "vạch kẻ đường"],
        "target_entities": ["xe_o_to", "xe_mo_to"],
    }
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(llm_payload)}}]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite(
        "Không chấp hành hiệu lệnh cảnh sát giao thông thì xử phạt thế nào"
    )

    assert "người điều khiển giao thông" in res.search_query
    assert "cảnh sát giao thông" not in (res.sanction_query or "")
    assert res.must_have_terms == ["người điều khiển giao thông"]
    assert res.must_not_have_terms == ["đèn tín hiệu", "biển báo hiệu", "vạch kẻ đường"]
    assert res.target_entities == ["xe_o_to", "xe_mo_to"]

    # Verify JSON serialization
    json_dict = res.to_json_dict()
    assert json_dict["must_have_terms"] == ["người điều khiển giao thông"]
    assert json_dict["must_not_have_terms"] == [
        "đèn tín hiệu",
        "biển báo hiệu",
        "vạch kẻ đường",
    ]
    assert json_dict["target_entities"] == ["xe_o_to", "xe_mo_to"]


def test_rewriter_llm_reasoning_specific_vehicle() -> None:
    """Test LLM reasoning when citizen specifies a single vehicle type."""
    config = PipelineConfig(enable_query_rewrite=True, rewriter_use_local=True)
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    llm_payload = {
        "intent": "violation_sanction",
        "search_query": "người điều khiển xe ô tô không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        "rule_query": "chấp hành tín hiệu đèn giao thông của xe ô tô",
        "sanction_query": "mức phạt tiền trừ điểm giấy phép lái xe ô tô vượt đèn đỏ",
        "identified_keywords": ["xe ô tô", "đèn tín hiệu"],
        "must_have_terms": ["đèn tín hiệu"],
        "must_not_have_terms": ["người điều khiển giao thông", "biển báo hiệu"],
        "target_entities": ["xe_o_to"],
    }
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(llm_payload)}}]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite("Ô tô vượt đèn đỏ phạt bao nhiêu")

    assert res.target_entities == ["xe_o_to"]
    assert res.must_have_terms == ["đèn tín hiệu"]
    assert "người điều khiển giao thông" in res.must_not_have_terms


def test_rewriter_backward_compatibility_missing_new_fields() -> None:
    """Test graceful handling when LLM response omits new constraint fields."""
    config = PipelineConfig(enable_query_rewrite=True, rewriter_use_local=True)
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    # Old style JSON without must_have_terms, must_not_have_terms, target_entities
    old_payload = {
        "intent": "violation_sanction",
        "search_query": "chạy quá tốc độ quy định",
        "rule_query": "tốc độ tối đa cho phép",
        "sanction_query": "mức phạt chạy quá tốc độ",
        "identified_keywords": ["tốc độ"],
    }
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(old_payload)}}]
    }
    mock_session.post.return_value = mock_resp

    rewriter = QueryRewriter(config=config, session=mock_session)
    res = rewriter.rewrite("bắn tốc độ")

    assert res.search_query == "chạy quá tốc độ quy định"
    assert res.must_have_terms == []
    assert res.must_not_have_terms == []
    assert res.target_entities == []


def test_rewriter_bypass_has_default_empty_constraints() -> None:
    """Test that bypass routes initialize constraint fields as empty lists."""
    config = PipelineConfig(enable_query_rewrite=True)
    rewriter = QueryRewriter(config=config)

    # Chitchat
    res_chitchat = rewriter.rewrite("xin chào")
    assert res_chitchat.intent == "out_of_scope"
    assert res_chitchat.must_have_terms == []
    assert res_chitchat.must_not_have_terms == []
    assert res_chitchat.target_entities == []

    # System meta query
    res_meta = rewriter.rewrite("danh mục luật và nghị định mà bạn biết")
    assert res_meta.intent == "system_meta_query"
    assert res_meta.must_have_terms == []
    assert res_meta.must_not_have_terms == []
    assert res_meta.target_entities == []


def test_rewriter_gemini_rotation_on_503() -> None:
    """Test key rotation when Gemini rewriter receives 503 error."""
    from src.extraction.key_manager import KeyManager

    config = PipelineConfig(
        enable_query_rewrite=True,
        rewriter_use_local=False,
        max_retries=2,
    )
    km = KeyManager(api_keys=["key-1", "key-2"], default_cooldown=10.0)
    mock_session = MagicMock(spec=requests.Session)

    resp_503 = MagicMock()
    resp_503.status_code = 503

    resp_200 = MagicMock()
    resp_200.status_code = 200
    llm_payload = {
        "intent": "violation_sanction",
        "search_query": "không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        "rule_query": "quy tắc đèn",
        "sanction_query": "mức phạt",
        "identified_keywords": ["vượt đèn đỏ"],
    }
    resp_200.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(llm_payload)}]}}]
    }

    mock_session.post.side_effect = [resp_503, resp_200]

    rewriter = QueryRewriter(config=config, key_manager=km, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ")

    assert mock_session.post.call_count == 2
    assert "không chấp hành hiệu lệnh" in res.search_query
    first_call_url = mock_session.post.call_args_list[0][0][0]
    second_call_url = mock_session.post.call_args_list[1][0][0]
    assert "key=key-1" in first_call_url
    assert "key=key-2" in second_call_url
