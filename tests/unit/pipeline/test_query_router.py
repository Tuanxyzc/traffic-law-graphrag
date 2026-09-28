"""Unit tests for Universal MCP Query Router & Entity Parser (SPEC-query-router)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import requests  # type: ignore[import-untyped]

from src.extraction.key_manager import KeyManager
from src.pipeline.config import PipelineConfig
from src.pipeline.models import (
    RewrittenQuery,
    RoutingAction,
    ValidatedProvision,
)
from src.pipeline.pipeline import GraphRAGPipeline
from src.pipeline.prompts import (
    MCP_TOOL_LOOKUP_LEGAL_PROVISION,
    get_gemini_tool_declaration,
    get_openai_tool_schema,
)
from src.pipeline.router import QueryRouter


def test_router_empty_query() -> None:
    """Tests that empty or whitespace query is routed immediately to HYBRID_SEARCH."""
    router = QueryRouter()
    res = router.route("   ")
    assert res.action == RoutingAction.HYBRID_SEARCH
    assert res.query == ""
    assert res.unit_id is None
    assert res.extracted_by == "tier1_regex"


def test_router_direct_lookup_shorthand_arabic() -> None:
    """Tests Tier 1 direct lookup with Arabic numerals, shorthand abbreviations, and varied order."""
    router = QueryRouter()

    # 1. Clause, Article, Decree shorthand: "khoản 5 d6 nd168"
    r1 = router.route("khoản 5 d6 nd168")
    assert r1.action == RoutingAction.DIRECT_LOOKUP
    assert r1.unit_id == "168_2024_ND-CP_D6_K5"

    # 2. Article only with full decree name: "cho xem điều 7 nghị định 168"
    r2 = router.route("cho xem điều 7 nghị định 168")
    assert r2.action == RoutingAction.DIRECT_LOOKUP
    assert r2.unit_id == "168_2024_ND-CP_D7"

    # 3. Point, Clause, Article, Law 36: "điểm b khoản 2 điều 11 luật 36"
    r3 = router.route("điểm b khoản 2 điều 11 luật 36")
    assert r3.action == RoutingAction.DIRECT_LOOKUP
    assert r3.unit_id == "36_2024_QH15_D11_K2_Db"

    # 4. Circular 72: "điều 15 thông tư 72"
    r4 = router.route("điều 15 thông tư 72")
    assert r4.action == RoutingAction.DIRECT_LOOKUP
    assert r4.unit_id == "72_2024_TT-BCA_D15"

    # 5. Law 35 Road: "khoản 3 điều 8 luật đường bộ"
    r5 = router.route("khoản 3 điều 8 luật đường bộ")
    assert r5.action == RoutingAction.DIRECT_LOOKUP
    assert r5.unit_id == "35_2024_QH15_D8_K3"

    # 6. Compact prefix shorthand: "k.5 d.6 bên nd168 với"
    r6 = router.route("k.5 d.6 bên nd168 với")
    assert r6.action == RoutingAction.DIRECT_LOOKUP
    assert r6.unit_id == "168_2024_ND-CP_D6_K5"


def test_router_direct_lookup_vietnamese_word_numbers() -> None:
    """Tests Tier 1 extraction when coordinates and document numbers are spelled out in Vietnamese."""
    router = QueryRouter()

    # Spelled-out point, clause, article, and document: "nghị định một trăm sáu mươi tám"
    r1 = router.route(
        "nội dung của điểm đ khoản năm điều sáu nghị định một trăm sáu mươi tám"
    )
    assert r1.action == RoutingAction.DIRECT_LOOKUP
    assert r1.unit_id == "168_2024_ND-CP_D6_K5_Dđ"

    # Textual alias: "luật trật tự an toàn giao thông" -> Law 36
    r2 = router.route("điều bảy luật trật tự an toàn giao thông")
    assert r2.action == RoutingAction.DIRECT_LOOKUP
    assert r2.unit_id == "36_2024_QH15_D7"


def test_router_strict_zero_hallucination_missing_doc() -> None:
    """Strict Policy: Has coordinates but lacks document name -> MUST route to HYBRID_SEARCH."""
    router = QueryRouter()

    # Query has article number and penalty keywords, but lacks document
    r1 = router.route("điều 6 xử phạt thế nào")
    assert r1.action == RoutingAction.HYBRID_SEARCH
    assert r1.unit_id is None
    assert "thiếu tên văn bản" in r1.reason.lower()

    # Query has clause and article, but lacks document
    r2 = router.route("khoản 5 điều 6 quy định gì")
    assert r2.action == RoutingAction.HYBRID_SEARCH
    assert r2.unit_id is None

    # Query asks to view article without document
    r3 = router.route("cho tôi xem nội dung điều 15")
    assert r3.action == RoutingAction.HYBRID_SEARCH
    assert r3.unit_id is None


def test_router_anti_hallucination_asking_for_article() -> None:
    """Anti-hallucination: Queries asking for article number based on offense MUST route to HYBRID_SEARCH."""
    router = QueryRouter()

    # Asking what article governs motorcycle sanctions
    r1 = router.route("quy định xử phạt xe máy là điều mấy?")
    assert r1.action == RoutingAction.HYBRID_SEARCH
    assert r1.unit_id is None
    assert "tìm số điều" in r1.reason.lower()

    # Asking what article in Decree 168 governs expressway offense
    r2 = router.route("mức phạt xe máy đi vào đường cao tốc nghị định 168 là điều mấy?")
    assert r2.action == RoutingAction.HYBRID_SEARCH
    assert r2.unit_id is None

    # Asking what article governs red light violation
    r3 = router.route("lỗi vượt đèn đỏ quy định ở điều nào?")
    assert r3.action == RoutingAction.HYBRID_SEARCH
    assert r3.unit_id is None


def test_router_pure_violation_inquiry() -> None:
    """Citizen questions describing an offense or asking for sanctions MUST route to HYBRID_SEARCH."""
    router = QueryRouter()

    r1 = router.route(
        "xe máy vượt đèn đỏ phạt bao nhiêu tiền và có bị tước bằng không?"
    )
    assert r1.action == RoutingAction.HYBRID_SEARCH
    assert r1.unit_id is None

    r2 = router.route("lỗi không gương phạt mấy tiền")
    assert r2.action == RoutingAction.HYBRID_SEARCH
    assert r2.unit_id is None


def test_mcp_tool_schema_and_adapters() -> None:
    """Verifies standard MCP Tool Schema and multi-provider adapters for OpenAI and Gemini."""
    assert MCP_TOOL_LOOKUP_LEGAL_PROVISION["name"] == "lookup_legal_provision"
    assert "unit_id" in MCP_TOOL_LOOKUP_LEGAL_PROVISION["inputSchema"]["properties"]
    assert MCP_TOOL_LOOKUP_LEGAL_PROVISION["inputSchema"]["required"] == ["unit_id"]

    # OpenAI format adapter
    openai_tool = get_openai_tool_schema(MCP_TOOL_LOOKUP_LEGAL_PROVISION)
    assert openai_tool["type"] == "function"
    assert openai_tool["function"]["name"] == "lookup_legal_provision"
    assert "unit_id" in openai_tool["function"]["parameters"]["properties"]

    # Gemini format adapter
    gemini_decl = get_gemini_tool_declaration(MCP_TOOL_LOOKUP_LEGAL_PROVISION)
    assert "function_declarations" in gemini_decl
    assert gemini_decl["function_declarations"][0]["name"] == "lookup_legal_provision"
    assert (
        "unit_id" in gemini_decl["function_declarations"][0]["parameters"]["properties"]
    )


def test_router_tier2_gemini_tool_call() -> None:
    """Tests Tier 2 LLM fallback when Gemini executes a tool call."""
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "lookup_legal_provision",
                                "args": {"unit_id": "168_2024_ND-CP_D6_K5_Da"},
                            }
                        }
                    ]
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    km = KeyManager(api_keys=["test-key-1"])
    config = PipelineConfig()
    router = QueryRouter(config=config, key_manager=km, session=mock_session)

    # Force Tier 2 by calling _route_tier2_multi_provider directly
    res = router._route_tier2_multi_provider("câu hỏi phức tạp")
    assert res.action == RoutingAction.DIRECT_LOOKUP
    assert res.unit_id == "168_2024_ND-CP_D6_K5_Da"
    assert res.extracted_by == "tier2_llm"


def test_router_tier2_openai_tool_call() -> None:
    """Tests Tier 2 LLM fallback when OpenAI/Groq executes a tool call."""
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "lookup_legal_provision",
                                "arguments": json.dumps(
                                    {"unit_id": "36_2024_QH15_D11_K2_Db"}
                                ),
                            }
                        }
                    ]
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    # Configure mock provider as openai-compatible
    km = MagicMock(spec=KeyManager)
    mock_key = MagicMock()
    mock_key.provider = "groq"
    mock_key.key = "test-groq-key"
    mock_key.model = "llama-3.3-70b-versatile"
    mock_key.endpoint = "https://api.groq.com/openai/v1"
    mock_key.api_type = "openai"
    km.get_provider_key.return_value = mock_key

    config = PipelineConfig()
    router = QueryRouter(config=config, key_manager=km, session=mock_session)

    res = router._route_tier2_multi_provider("câu hỏi mở rộng")
    assert res.action == RoutingAction.DIRECT_LOOKUP
    assert res.unit_id == "36_2024_QH15_D11_K2_Db"
    assert res.extracted_by == "tier2_llm"


def test_router_tier2_json_fallback() -> None:
    """Tests Tier 2 LLM fallback when LLM returns structured HYBRID_SEARCH JSON."""
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
                                    "action": "HYBRID_SEARCH",
                                    "query": "lỗi không chấp hành hiệu lệnh",
                                    "reason": "Truy vấn tình huống vi phạm, đẩy qua Hybrid Search.",
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    km = KeyManager(api_keys=["test-key-1"])
    config = PipelineConfig()
    router = QueryRouter(config=config, key_manager=km, session=mock_session)

    res = router._route_tier2_multi_provider("câu hỏi tình huống")
    assert res.action == RoutingAction.HYBRID_SEARCH
    assert res.query == "lỗi không chấp hành hiệu lệnh"
    assert res.extracted_by == "tier2_llm"


def test_pipeline_integration_direct_lookup() -> None:
    """Tests that GraphRAGPipeline executes DIRECT_LOOKUP, bypassing BM25/Vector retrieval."""
    mock_validator = MagicMock()
    mock_node = ValidatedProvision(
        provision_id="168_2024_ND-CP_D6_K5",
        level="CLAUSE",
        content_text="Xử phạt người điều khiển xe mô tô...",
    )
    mock_validator.lookup_legal_provision_neighborhood.return_value = [mock_node]
    mock_validator.lookup_legal_provision_node.return_value = mock_node

    mock_generator = MagicMock()
    mock_generator.generate.return_value = MagicMock(
        answer="Nội dung Khoản 5 Điều 6 Nghị định 168...",
        citations=["168_2024_ND-CP_D6_K5"],
        grounding_verified=True,
        verification_warnings=[],
    )

    mock_retriever = MagicMock()
    mock_rewriter = MagicMock()

    pipeline = GraphRAGPipeline(
        rewriter=mock_rewriter,
        retriever=mock_retriever,
        validator=mock_validator,
        generator=mock_generator,
    )

    res = pipeline.run("khoản 5 d6 nd168")
    assert res.routing_action == RoutingAction.DIRECT_LOOKUP
    assert res.matched_unit_id == "168_2024_ND-CP_D6_K5"
    assert "168_2024_ND-CP_D6_K5" in res.citations

    # Verify that retrieval was completely bypassed
    assert not mock_retriever.retrieve.called
    assert not mock_rewriter.rewrite.called
    # Verify that graph lookup was called with exact unit_id
    mock_validator.lookup_legal_provision_neighborhood.assert_called_once_with(
        "168_2024_ND-CP_D6_K5"
    )


def test_pipeline_integration_hybrid_search() -> None:
    """Tests that GraphRAGPipeline executes HYBRID_SEARCH for general questions."""
    mock_validator = MagicMock()
    mock_generator = MagicMock()
    mock_generator.generate.return_value = MagicMock(
        answer="Mức phạt vượt đèn đỏ xe máy...",
        citations=["168_2024_ND-CP_D6_K4"],
        grounding_verified=True,
        verification_warnings=[],
    )

    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = MagicMock(chunks=[])

    mock_rewriter = MagicMock()
    mock_rewriter.rewrite.return_value = RewrittenQuery(
        original_query="xe máy vượt đèn đỏ phạt bao nhiêu?",
        search_query="xử phạt hành vi không chấp hành đèn tín hiệu giao thông",
        rule_query="quy tắc đèn tín hiệu",
        sanction_query="mức phạt vượt đèn đỏ xe mô tô",
        identified_keywords=["đèn tín hiệu"],
        must_have_terms=["đèn tín hiệu"],
        must_not_have_terms=[],
        target_entities=["xe_mo_to"],
        intent="violation_sanction",
        source_doc=None,
        target_doc=None,
    )

    pipeline = GraphRAGPipeline(
        rewriter=mock_rewriter,
        retriever=mock_retriever,
        validator=mock_validator,
        generator=mock_generator,
    )

    res = pipeline.run("xe máy vượt đèn đỏ phạt bao nhiêu?")
    assert res.routing_action == RoutingAction.HYBRID_SEARCH
    assert res.matched_unit_id is None
    # Verify that rewriter and retriever were engaged
    assert mock_rewriter.rewrite.called
    assert mock_retriever.retrieve.called
