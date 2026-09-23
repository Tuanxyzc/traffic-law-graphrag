"""Unit tests for AnswerGenerator."""

from __future__ import annotations

from unittest.mock import MagicMock

import requests  # type: ignore[import-untyped]

from src.extraction.key_manager import KeyManager
from src.pipeline.config import PipelineConfig
from src.pipeline.generator import (
    AnswerGenerator,
    clean_generated_answer,
    extract_citations_from_text,
    has_sanctions_in_package,
)
from src.pipeline.models import (
    EvidenceItem,
    EvidencePackage,
    LegalValidityStatus,
    ReferencedProvision,
    ValidatedProvision,
)


def test_extract_citations_from_text() -> None:
    """Test citation regex extraction from generated text."""
    sample_text = (
        "Theo quy định tại Điểm a Khoản 1 Điều 5 Nghị định 168/2024/ND-CP, "
        "người vi phạm sẽ bị phạt tiền. Ngoài ra, Khoản 2 Điều 8 cũng quy định..."
    )
    citations = extract_citations_from_text(sample_text)
    assert len(citations) >= 2
    assert any("Điểm a Khoản 1 Điều 5" in c for c in citations)
    assert any("Khoản 2 Điều 8" in c for c in citations)

    # Test suppression when package is system_meta_query
    meta_package = EvidencePackage(
        user_query="danh mục",
        rewritten_query="danh mục",
        system_documents=[
            {"so_hieu": "165/2024/NĐ-CP", "ten": "Nghị định quy định Điều 77"}
        ],
    )
    assert extract_citations_from_text(sample_text, package=meta_package) == []

    # Test suppression when package has 0 items and 0 amendments
    empty_package = EvidencePackage(
        user_query="câu hỏi",
        rewritten_query="câu hỏi",
        items=[],
    )
    assert extract_citations_from_text(sample_text, package=empty_package) == []


def test_generator_empty_evidence() -> None:
    """Test generator behavior when evidence package is empty (prompts LLM for conversational greeting/refusal)."""
    package = EvidencePackage(
        user_query="Xin chào bạn",
        rewritten_query="xin chào",
        items=[],
    )
    km = KeyManager(api_keys=["test-key"])
    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "Xin chào bạn! Tôi là Trợ lý AI Cố vấn Pháp luật Giao thông Đường bộ Việt Nam. Tôi có thể hỗ trợ gì cho bạn?"
                        }
                    ]
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp
    config = PipelineConfig(generator_use_local=False)
    generator = AnswerGenerator(config=config, key_manager=km, session=mock_session)
    res = generator.generate(package)

    assert "Trợ lý AI Cố vấn Pháp luật Giao thông" in res.answer
    assert res.citations == []
    # Verify conversational instructions are present in prompt
    called_payload = mock_session.post.call_args[1]["json"]
    sent_prompt = called_payload["contents"][0]["parts"][0]["text"]
    assert "HƯỚNG DẪN XỬ LÝ" in sent_prompt
    assert "LỜI CHÀO HỎI" in sent_prompt


def test_generator_successful_completion() -> None:
    """Test successful generation with mock LLM response."""
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D5_K1_Da",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Phạt tiền từ 200.000 đồng đến 400.000 đồng...",
    )
    item = EvidenceItem(
        chunk_id="c1",
        original_chunk_text="Phạt 200.000 - 400.000 đồng",
        validated_provision=vp,
    )
    package = EvidencePackage(
        user_query="phạt tiền",
        rewritten_query="mức phạt",
        items=[item],
    )

    km = KeyManager(api_keys=["test-key"])
    mock_session = MagicMock(spec=requests.Session)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "Theo Điểm a Khoản 1 Điều 5 Nghị định 168/2024/NĐ-CP, "
                                "hành vi vi phạm sẽ bị phạt tiền từ 200.000 đồng đến 400.000 đồng."
                            )
                        }
                    ]
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    config = PipelineConfig(generator_use_local=False)
    generator = AnswerGenerator(
        config=config,
        key_manager=km,
        session=mock_session,
    )
    res = generator.generate(package)

    assert "200.000 đồng đến 400.000 đồng" in res.answer
    assert len(res.citations) > 0
    assert any("Điều 5" in c for c in res.citations)


def test_generator_rotation_on_429() -> None:
    """Test key rotation when generator receives 429 quota error."""
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D5_K1",
        level="CLAUSE",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Quy định điều 5",
    )
    item = EvidenceItem(
        chunk_id="c1",
        original_chunk_text="Nội dung",
        validated_provision=vp,
    )
    package = EvidencePackage(
        user_query="q",
        rewritten_query="q",
        items=[item],
    )

    km = KeyManager(api_keys=["key-1", "key-2"], default_cooldown=10.0)
    mock_session = MagicMock(spec=requests.Session)

    resp_429 = MagicMock()
    resp_429.status_code = 429

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "candidates": [
            {"content": {"parts": [{"text": "Căn cứ Khoản 1 Điều 5, mức phạt là..."}]}}
        ]
    }

    mock_session.post.side_effect = [resp_429, resp_200]

    config = PipelineConfig(max_retries=2)
    generator = AnswerGenerator(config=config, key_manager=km, session=mock_session)
    res = generator.generate(package)

    assert mock_session.post.call_count == 2
    assert "Khoản 1 Điều 5" in res.answer


def test_generator_rotation_on_503() -> None:
    """Test key rotation when generator receives 503 server overloaded error."""
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D5_K1",
        level="CLAUSE",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Quy định điều 5",
    )
    item = EvidenceItem(
        chunk_id="c1",
        original_chunk_text="Nội dung",
        validated_provision=vp,
    )
    package = EvidencePackage(
        user_query="q",
        rewritten_query="q",
        items=[item],
    )

    km = KeyManager(api_keys=["key-1", "key-2"], default_cooldown=10.0)
    mock_session = MagicMock(spec=requests.Session)

    resp_503 = MagicMock()
    resp_503.status_code = 503

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "candidates": [
            {"content": {"parts": [{"text": "Căn cứ Khoản 1 Điều 5, mức phạt là..."}]}}
        ]
    }

    mock_session.post.side_effect = [resp_503, resp_200]

    config = PipelineConfig(max_retries=2)
    generator = AnswerGenerator(config=config, key_manager=km, session=mock_session)
    res = generator.generate(package)

    assert mock_session.post.call_count == 2
    assert "Khoản 1 Điều 5" in res.answer
    first_call_url = mock_session.post.call_args_list[0][0][0]
    second_call_url = mock_session.post.call_args_list[1][0][0]
    assert "key=key-1" in first_call_url
    assert "key=key-2" in second_call_url


def test_generator_network_failure_fallback() -> None:
    """Test fallback message when all requests fail."""
    vp = ValidatedProvision(
        provision_id="p1",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Quy định",
    )
    item = EvidenceItem(
        chunk_id="c1", original_chunk_text="text", validated_provision=vp
    )
    package = EvidencePackage(user_query="q", rewritten_query="q", items=[item])

    km = KeyManager(api_keys=["key-1"])
    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = requests.RequestException("Network unreachable")

    config = PipelineConfig(max_retries=1)
    generator = AnswerGenerator(config=config, key_manager=km, session=mock_session)
    res = generator.generate(package)

    assert "tạm thời không thể tạo câu trả lời" in res.answer
    assert res.citations == []


def test_has_sanctions_in_package() -> None:
    """Test detection of sanction presence in evidence package."""
    # 1. Package with fines
    vp_fine = ValidatedProvision(
        provision_id="p1",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Hành vi vi phạm",
        parent_clause_content="Phạt tiền từ 2.000.000 đồng đến 3.000.000 đồng đối với...",
    )
    item_fine = EvidenceItem(
        chunk_id="c1", original_chunk_text="text", validated_provision=vp_fine
    )
    pkg_fine = EvidencePackage(user_query="q", rewritten_query="q", items=[item_fine])
    assert has_sanctions_in_package(pkg_fine) is True

    # 2. Package with point deduction reference
    ref = ReferencedProvision(
        target_id="p_sanction",
        relation_type="TRU_DIEM_GPLX",
        content="bị trừ 4 điểm giấy phép lái xe",
    )
    vp_deduct = ValidatedProvision(
        provision_id="p2",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Hành vi vi phạm",
        cross_references=[ref],
    )
    item_deduct = EvidenceItem(
        chunk_id="c2", original_chunk_text="text", validated_provision=vp_deduct
    )
    pkg_deduct = EvidencePackage(
        user_query="q", rewritten_query="q", items=[item_deduct]
    )
    assert has_sanctions_in_package(pkg_deduct) is True

    # 3. Package with general scope provision (Điều 1) without concrete fines or deductions
    vp_scope = ValidatedProvision(
        provision_id="168_2024_ND-CP_D1",
        level="ARTICLE",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Điều 1. Phạm vi điều chỉnh. Nghị định này quy định về xử phạt vi phạm hành chính...",
    )
    item_scope = EvidenceItem(
        chunk_id="c3",
        original_chunk_text="Điều 1. Phạm vi điều chỉnh",
        validated_provision=vp_scope,
    )
    pkg_scope = EvidencePackage(
        user_query="Trích toàn bộ điều 1", rewritten_query="Điều 1", items=[item_scope]
    )
    assert has_sanctions_in_package(pkg_scope) is False


def test_clean_generated_answer_prunes_no_sanction_note() -> None:
    """Test that when has_sanctions is False, redundant no-sanction note is pruned."""
    raw_text = (
        "Chào bạn, dưới đây là toàn văn Điều 1:\n\n"
        "### **TRÍCH TOÀN VĂN ĐIỀU 1 NGHỊ ĐỊNH 168/2024/NĐ-CP**\n\n"
        "> Điều 1. Phạm vi điều chỉnh...\n\n"
        "---\n\n"
        "### **GHI CHÚ VỀ HÌNH THỨC XỬ PHẠT VÀ ĐIỂM GPLX**\n"
        "* Điều 1 là quy định chung về phạm vi điều chỉnh, không trực tiếp chế tài hành vi vi phạm cụ thể, "
        "do đó không quy định mức phạt tiền, hình thức xử phạt bổ sung hay mức trừ điểm GPLX."
    )
    cleaned = clean_generated_answer(raw_text, has_sanctions=False)
    assert "TRÍCH TOÀN VĂN ĐIỀU 1" in cleaned
    assert "GHI CHÚ VỀ HÌNH THỨC XỬ PHẠT" not in cleaned
    assert "không trực tiếp chế tài" not in cleaned


def test_clean_generated_answer_deduplicates_header_loops() -> None:
    """Test deduplication when model enters a degenerate repetitive completion loop."""
    repetitive_text = (
        "### **NỘI DUNG QUY ĐỊNH**\n"
        "Toàn văn nội dung quy định Điều 1.\n\n"
        "### **GHI CHÚ VỀ HÌNH THỨC XỬ PHẠT**\n"
        "Ghi chú lần 1.\n\n"
        "### **GHI CHÚ VỀ HÌNH THỨC XỬ PHẠT**\n"
        "Ghi chú lần 2 lặp lại.\n\n"
        "### **GHI CHÚ VỀ HÌNH THỨC XỬ PHẠT**\n"
        "Ghi chú lần 3 lặp lại."
    )
    cleaned = clean_generated_answer(repetitive_text, has_sanctions=True)
    # Header should appear exactly once
    assert cleaned.count("GHI CHÚ VỀ HÌNH THỨC XỬ PHẠT") == 1
    assert "Ghi chú lần 1" in cleaned
    assert "Ghi chú lần 2" not in cleaned


def test_clean_generated_answer_preserves_genuine_sanctions() -> None:
    """Test that valid penalty sections are fully preserved when has_sanctions is True."""
    valid_text = (
        "### **CĂN CỨ PHÁP LÝ**\n"
        "Theo Khoản 1 Điều 5.\n\n"
        "### **HÌNH THỨC XỬ PHẠT VÀ ĐIỂM GPLX**\n"
        "* Phạt tiền: từ 4.000.000 đồng đến 6.000.000 đồng đối với người điều khiển xe ô tô.\n"
        "* Trừ điểm GPLX: Trừ 2 điểm."
    )
    cleaned = clean_generated_answer(valid_text, has_sanctions=True)
    assert "HÌNH THỨC XỬ PHẠT VÀ ĐIỂM GPLX" in cleaned
    assert "4.000.000 đồng đến 6.000.000 đồng" in cleaned
    assert "Trừ 2 điểm" in cleaned


def test_generator_local_mode_successful() -> None:
    """Test answer generation using Localhost LLM OpenAI-compatible REST endpoint."""
    config = PipelineConfig(
        generator_use_local=True,
        generator_local_endpoint="http://localhost:11434/v1",
        generator_local_model="Qwen2.5:1.5b",
    )
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D7_K1_Da",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Phạt tiền từ 200.000 đến 400.000 đồng đối với xe mô tô...",
        parent_article_title="Điều 7. Xử phạt người điều khiển xe mô tô, xe gắn máy",
    )
    item = EvidenceItem(
        chunk_id="c1",
        original_chunk_text="Phạt tiền từ 200.000 đến 400.000 đồng đối với xe mô tô...",
        validated_provision=vp,
    )
    pkg = EvidencePackage(
        user_query="xe máy vượt đèn đỏ phạt bao nhiêu",
        rewritten_query="mức phạt xe mô tô vượt đèn đỏ",
        items=[item],
    )

    mock_session = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        "Theo Điểm a Khoản 1 Điều 7 Nghị định 168/2024/NĐ-CP, "
                        "người điều khiển xe mô tô, xe gắn máy không chấp hành hiệu lệnh của đèn tín hiệu giao thông "
                        "bị phạt tiền từ 200.000 đồng đến 400.000 đồng."
                    )
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    generator = AnswerGenerator(config=config, session=mock_session)
    res = generator.generate(pkg)

    assert "Điểm a Khoản 1 Điều 7 Nghị định 168/2024/NĐ-CP" in res.answer
    assert "200.000 đồng đến 400.000 đồng" in res.answer
    assert any("Điều 7" in c for c in res.citations)

    called_url = mock_session.post.call_args[0][0]
    assert "http://localhost:11434/v1/chat/completions" in called_url


def test_generator_local_mode_failure() -> None:
    """Test graceful fallback when Localhost LLM endpoint is unreachable."""
    config = PipelineConfig(
        generator_use_local=True,
        generator_local_endpoint="http://localhost:11434/v1",
    )
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D7_K1",
        level="CLAUSE",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        content_text="Quy định",
    )
    item = EvidenceItem(
        chunk_id="c1",
        original_chunk_text="Quy định",
        validated_provision=vp,
    )
    pkg = EvidencePackage(user_query="q", rewritten_query="q", items=[item])

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = requests.ConnectionError("Connection refused")

    generator = AnswerGenerator(config=config, session=mock_session)
    res = generator.generate(pkg)

    assert "mô hình ngôn ngữ cục bộ" in res.answer
    assert res.citations == []


def test_clean_generated_answer_strips_role_echo() -> None:
    """Test that role repetition phrases like 'Bạn là chuyên viên tư vấn pháp luật...' are stripped."""
    raw_answer = (
        "Bạn là chuyên viên tư vấn pháp luật giao thông đường bộ Việt Nam.\n\n"
        "Vượt đèn đỏ ở xe máy bị xử phạt như sau:\n"
        "- Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng.\n"
        "- Trừ 2 điểm giấy phép lái xe."
    )
    cleaned = clean_generated_answer(raw_answer, has_sanctions=True)
    assert not cleaned.startswith("Bạn là chuyên viên")
    assert "Vượt đèn đỏ ở xe máy bị xử phạt như sau:" in cleaned
