"""Unit tests for Multi-Provider LLM Key Management and Failover (Gemini, Groq, Cerebras, Cohere)."""

import json
from unittest.mock import MagicMock

import requests

from src.extraction.key_manager import KeyManager
from src.pipeline.config import PipelineConfig
from src.pipeline.generator import AnswerGenerator
from src.pipeline.models import (
    EvidenceItem,
    EvidencePackage,
    LegalValidityStatus,
    ValidatedProvision,
)
from src.pipeline.rewriter import QueryRewriter


def test_key_manager_multi_provider_init() -> None:
    """Test initializing KeyManager with explicit multiple provider key pools."""
    pools = {
        "gemini": ["gem-key-1", "gem-key-2"],
        "groq": ["groq-key-1"],
        "cerebras": ["cere-key-1"],
        "cohere": ["coh-key-1"],
    }
    km = KeyManager(
        api_keys=pools,
        provider_order=["gemini", "groq", "cerebras", "cohere"],
    )

    assert km.active_providers == ["gemini", "groq", "cerebras", "cohere"]
    assert km.active_provider == "gemini"
    assert km.key_count == 5


def test_key_manager_intra_provider_rotation() -> None:
    """Test that rate limiting a key rotates to the next key of the SAME provider first."""
    pools = {
        "gemini": ["gem-1", "gem-2"],
        "groq": ["groq-1"],
    }
    km = KeyManager(api_keys=pools, default_cooldown=60.0)

    # First key should be gem-1
    pk1 = km.get_provider_key()
    assert pk1.provider == "gemini"
    assert pk1.key == "gem-1"

    # Rate limit gem-1
    km.mark_rate_limited("gem-1", provider="gemini")

    # Second key should be gem-2 (same provider)
    pk2 = km.get_provider_key()
    assert pk2.provider == "gemini"
    assert pk2.key == "gem-2"


def test_key_manager_inter_provider_failover() -> None:
    """Test that when all keys of Gemini are exhausted, KeyManager fails over to Groq, then Cerebras, then Cohere."""
    pools = {
        "gemini": ["gem-1", "gem-2"],
        "groq": ["groq-1"],
        "cerebras": ["cere-1"],
        "cohere": ["coh-1"],
    }
    km = KeyManager(
        api_keys=pools,
        provider_order=["gemini", "groq", "cerebras", "cohere"],
        default_cooldown=60.0,
    )

    # 1. Exhaust Gemini keys
    km.mark_rate_limited("gem-1", provider="gemini")
    km.mark_rate_limited("gem-2", provider="gemini")

    # Should failover to Groq!
    pk_groq = km.get_provider_key()
    assert pk_groq.provider == "groq"
    assert pk_groq.key == "groq-1"
    assert pk_groq.api_type == "openai"
    assert "groq.com" in pk_groq.endpoint

    # 2. Exhaust Groq key
    km.mark_rate_limited("groq-1", provider="groq")

    # Should failover to Cerebras!
    pk_cere = km.get_provider_key()
    assert pk_cere.provider == "cerebras"
    assert pk_cere.key == "cere-1"
    assert pk_cere.api_type == "openai"
    assert "cerebras.ai" in pk_cere.endpoint

    # 3. Exhaust Cerebras key
    km.mark_rate_limited("cere-1", provider="cerebras")

    # Should failover to Cohere!
    pk_coh = km.get_provider_key()
    assert pk_coh.provider == "cohere"
    assert pk_coh.key == "coh-1"
    assert pk_coh.api_type == "openai"
    assert "cohere" in pk_coh.endpoint


def test_generator_multi_provider_failover_gemini_to_groq() -> None:
    """Test AnswerGenerator seamlessly failing over from Gemini to Groq when Gemini hits quota."""
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D6_K1",
        level="CLAUSE",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Phạt tiền từ 400.000 đến 600.000 đồng vượt đèn đỏ xe máy.",
    )
    item = EvidenceItem(
        chunk_id="c1",
        original_chunk_text="Phạt 400.000 - 600.000 đồng",
        validated_provision=vp,
    )
    package = EvidencePackage(
        user_query="Vượt đèn đỏ xe máy phạt bao nhiêu?",
        rewritten_query="mức xử phạt không chấp hành đèn tín hiệu giao thông xe mô tô",
        items=[item],
    )

    pools = {
        "gemini": ["gem-1"],
        "groq": ["groq-1"],
    }
    km = KeyManager(
        api_keys=pools, provider_order=["gemini", "groq"], default_cooldown=10.0
    )

    mock_session = MagicMock(spec=requests.Session)

    # 1. First request to Gemini returns HTTP 429
    resp_gemini_429 = MagicMock()
    resp_gemini_429.status_code = 429

    # 2. Second request goes to Groq OpenAI endpoint and succeeds (HTTP 200)
    resp_groq_200 = MagicMock()
    resp_groq_200.status_code = 200
    groq_openai_response = {
        "choices": [
            {
                "message": {
                    "content": "Theo quy định tại Khoản 1 Điều 6 Nghị định 168/2024/NĐ-CP, phạt tiền từ 400.000 đồng đến 600.000 đồng."
                }
            }
        ]
    }
    resp_groq_200.json.return_value = groq_openai_response

    mock_session.post.side_effect = [resp_gemini_429, resp_groq_200]

    config = PipelineConfig(max_retries=3, generator_use_local=False)
    generator = AnswerGenerator(config=config, key_manager=km, session=mock_session)
    result = generator.generate(package)

    assert mock_session.post.call_count == 2
    # Verify first call was to Gemini
    first_url = mock_session.post.call_args_list[0][0][0]
    assert "generativelanguage.googleapis.com" in first_url
    assert "key=gem-1" in first_url

    # Verify second call failed over to Groq OpenAI endpoint
    second_url = mock_session.post.call_args_list[1][0][0]
    second_headers = mock_session.post.call_args_list[1][1]["headers"]
    assert "api.groq.com" in second_url
    assert second_headers["Authorization"] == "Bearer groq-1"

    assert "400.000 đồng đến 600.000 đồng" in result.answer
    assert any("Điều 6" in c for c in result.citations)


def test_rewriter_multi_provider_failover_gemini_to_cerebras() -> None:
    """Test QueryRewriter seamlessly failing over from Gemini to Cerebras (OpenAI JSON format)."""
    pools = {
        "gemini": ["gem-1"],
        "cerebras": ["cere-1"],
    }
    km = KeyManager(
        api_keys=pools, provider_order=["gemini", "cerebras"], default_cooldown=10.0
    )

    mock_session = MagicMock(spec=requests.Session)

    # 1. Gemini fails with 503
    resp_gemini_503 = MagicMock()
    resp_gemini_503.status_code = 503

    # 2. Cerebras succeeds with structured JSON output
    resp_cerebras_200 = MagicMock()
    resp_cerebras_200.status_code = 200
    cerebras_payload = {
        "intent": "violation_sanction",
        "search_query": "không chấp hành hiệu lệnh của đèn tín hiệu giao thông xe mô tô",
        "rule_query": "quy tắc chấp hành đèn tín hiệu giao thông",
        "sanction_query": "mức phạt tiền trừ điểm giấy phép lái xe",
        "identified_keywords": ["vượt đèn đỏ", "xe máy"],
        "target_entities": ["xe_mo_to"],
    }
    resp_cerebras_200.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(cerebras_payload),
                }
            }
        ]
    }

    mock_session.post.side_effect = [resp_gemini_503, resp_cerebras_200]

    config = PipelineConfig(
        enable_query_rewrite=True, rewriter_use_local=False, max_retries=3
    )
    rewriter = QueryRewriter(config=config, key_manager=km, session=mock_session)
    res = rewriter.rewrite("vượt đèn đỏ xe máy")

    assert mock_session.post.call_count == 2
    # First was Gemini
    assert (
        "generativelanguage.googleapis.com" in mock_session.post.call_args_list[0][0][0]
    )
    # Second was Cerebras
    second_url = mock_session.post.call_args_list[1][0][0]
    second_headers = mock_session.post.call_args_list[1][1]["headers"]
    assert "api.cerebras.ai" in second_url
    assert second_headers["Authorization"] == "Bearer cere-1"

    assert "không chấp hành hiệu lệnh" in res.search_query
    assert res.target_entities == ["xe_mo_to"]


def test_key_manager_cooldown_expiry_recovery() -> None:
    """Test that when a provider's cooldown expires, it becomes available again."""
    pools = {
        "gemini": ["gem-1"],
        "groq": ["groq-1"],
    }
    km = KeyManager(
        api_keys=pools, provider_order=["gemini", "groq"], default_cooldown=0.05
    )

    # Rate limit gem-1 with 0.05s cooldown
    km.mark_rate_limited("gem-1", cooldown_seconds=0.05, provider="gemini")

    # Immediately after, gemini is exhausted, so Groq is active
    pk_groq = km.get_provider_key()
    assert pk_groq.provider == "groq"

    # Wait for Gemini cooldown to expire
    import time

    time.sleep(0.06)

    # Next call after cooldown should be able to pick up Gemini when Groq also exhausts or cycles
    km.mark_rate_limited("groq-1", cooldown_seconds=10.0, provider="groq")
    pk_gem_recovered = km.get_provider_key()
    assert pk_gem_recovered.provider == "gemini"
    assert pk_gem_recovered.key == "gem-1"
