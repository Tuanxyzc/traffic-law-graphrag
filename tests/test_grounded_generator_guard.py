"""Unit tests for grounded-generator-guard (Dynamic Context Excellence & Generalized Grounding Guard).

Verifies:
1. Dynamic context header formatting in EvidenceBuilder with intent and target_entities metadata.
2. Dynamic user prompt instructions in AnswerGenerator adapting to multi-vehicle and violation sanction intent.
3. Generalized action grounding verification detecting negative term drift (must_not_have_terms).
4. Generalized action grounding verification checking target entity coverage (target_entities).
5. Grounding verification metadata in GenerationResult and PipelineResult.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.pipeline.config import PipelineConfig
from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.generator import (
    AnswerGenerator,
    verify_action_grounding,
)
from src.pipeline.models import (
    EvidencePackage,
    LegalValidityStatus,
    ReferencedProvision,
    RewrittenQuery,
    ValidatedProvision,
)
from src.rag.models import ChunkMetadata, RetrievedChunk


def _make_chunk(chunk_id: str, text: str, article: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        text=text,
        raw_text=text,
        metadata=ChunkMetadata(
            document_id="168_2024_ND-CP",
            dieu=article,
            tieu_de_dieu=f"Điều {article}",
            level=4,
        ),
        score=0.03,
        dense_score=0.85,
        sparse_score=12.5,
        dense_rank=1,
        sparse_rank=2,
    )


def test_dynamic_context_header_metadata() -> None:
    """Verifies that format_for_llm dynamically includes intent and target_entities in context header."""
    rw = RewrittenQuery(
        original_query="Không chấp hành hiệu lệnh CSGT phạt thế nào",
        search_query="không chấp hành hiệu lệnh của người điều khiển giao thông",
        rule_query="quy định chấp hành hiệu lệnh người chỉ huy giao thông",
        sanction_query="xử phạt không tuân thủ hiệu lệnh cảnh sát giao thông",
        intent="violation_sanction",
        target_entities=["xe_o_to", "xe_mo_to"],
        must_have_terms=["hiệu lệnh", "người điều khiển giao thông"],
        must_not_have_terms=["đèn tín hiệu", "vượt đèn đỏ"],
    )

    chunk = _make_chunk("chunk_1", "Nội dung điều khoản...", "6")
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk.raw_text or "",
    )

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="Không chấp hành hiệu lệnh CSGT phạt thế nào",
        rewritten_query=rw,
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    context = builder.format_for_llm(pkg)

    # Dynamic metadata must be present in the header
    assert "MỤC ĐÍCH TRA CỨU: violation_sanction" in context
    assert "ĐỐI TƯỢNG PHƯƠNG TIỆN MỤC TIÊU: xe_o_to, xe_mo_to" in context
    assert (
        "TRUY VẤN PHÁP LÝ CHUẨN HÓA: không chấp hành hiệu lệnh của người điều khiển giao thông"
        in context
    )


def test_dynamic_user_prompt_multi_vehicle() -> None:
    """Verifies that _build_user_prompt generates multi-vehicle guidance when multiple target entities exist."""
    rw = RewrittenQuery(
        original_query="phạt không nghe theo CSGT",
        search_query="không chấp hành hiệu lệnh của người điều khiển giao thông",
        intent="violation_sanction",
        target_entities=["xe_o_to", "xe_mo_to"],
    )

    chunk = _make_chunk("chunk_1", "Nội dung quy định", "6")
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk.raw_text or "",
    )

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="phạt không nghe theo CSGT",
        rewritten_query=rw,
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    gen = AnswerGenerator()
    prompt = gen._build_user_prompt(pkg, has_sanctions=True)

    # Multi-vehicle instruction must be generated dynamically
    assert "nhiều nhóm phương tiện (xe_o_to, xe_mo_to)" in prompt
    assert "phân tách rõ ràng từng nhóm phương tiện" in prompt


def test_dynamic_user_prompt_sanction_distinction() -> None:
    """Verifies that _build_user_prompt instructs LLM to distinguish citizen sanctions from police powers."""
    rw = RewrittenQuery(
        original_query="bị phạt bao nhiêu khi không nghe CSGT",
        search_query="hiệu lệnh người kiểm soát giao thông",
        intent="violation_sanction",
        target_entities=["xe_o_to"],
    )

    chunk = _make_chunk("chunk_1", "Nội dung quy định", "6")
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk.raw_text or "",
    )

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="bị phạt bao nhiêu khi không nghe CSGT",
        rewritten_query=rw,
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    gen = AnswerGenerator()
    prompt = gen._build_user_prompt(pkg, has_sanctions=True)

    # Guidance to avoid turning police enforcement powers into citizen penalties
    assert "chế tài xử phạt hành chính đối với người vi phạm" in prompt
    assert "biện pháp nghiệp vụ của lực lượng thực thi công vụ" in prompt
    assert "truy đuổi" in prompt


def test_verify_action_grounding_negative_term_drift() -> None:
    """Verifies that verify_action_grounding detects prohibited negative terms without hardcoding."""
    rw = RewrittenQuery(
        original_query="Không chấp hành hiệu lệnh CSGT phạt thế nào",
        search_query="không chấp hành hiệu lệnh của người điều khiển giao thông",
        must_not_have_terms=["đèn tín hiệu", "vượt đèn đỏ"],
    )
    pkg = EvidencePackage(user_query="q", rewritten_query=rw, items=[])

    # Case 1: Answer drifts to traffic light violation
    drifted_answer = (
        "Theo quy định, hành vi vượt đèn đỏ khi tham gia giao thông bị phạt 5 triệu đồng."
    )
    is_valid, warnings = verify_action_grounding(drifted_answer, rw, pkg)
    assert is_valid is False
    assert any("vượt đèn đỏ" in w for w in warnings)

    # Case 2: Clean answer on police signals
    clean_answer = (
        "Hành vi không chấp hành hiệu lệnh của người điều khiển giao thông bị xử phạt..."
    )
    is_valid_clean, warnings_clean = verify_action_grounding(clean_answer, rw, pkg)
    assert is_valid_clean is True
    assert len(warnings_clean) == 0


def test_verify_action_grounding_target_entities_coverage() -> None:
    """Verifies that verify_action_grounding warns when a target vehicle entity is omitted."""
    rw = RewrittenQuery(
        original_query="Không chấp hành hiệu lệnh CSGT phạt thế nào",
        search_query="không chấp hành hiệu lệnh người điều khiển giao thông",
        target_entities=["xe_o_to", "xe_mo_to"],
    )
    pkg = EvidencePackage(user_query="q", rewritten_query=rw, items=[])

    # Answer only mentions cars, omitting motorcycles
    car_only_answer = (
        "Đối với người điều khiển xe ô tô, hành vi không chấp hành hiệu lệnh bị phạt tiền..."
    )
    is_valid, warnings = verify_action_grounding(car_only_answer, rw, pkg)
    assert is_valid is False
    assert any("xe_mo_to" in w for w in warnings)

    # Answer mentions both cars and motorcycles
    both_answer = (
        "Đối với xe ô tô: phạt tiền từ 18 triệu đến 20 triệu. "
        "Đối với xe máy: phạt tiền từ 4 triệu đến 6 triệu."
    )
    is_valid_both, warnings_both = verify_action_grounding(both_answer, rw, pkg)
    assert is_valid_both is True
    assert len(warnings_both) == 0


def test_generator_local_grounding_verified_integration() -> None:
    """Verifies that _generate_local runs verification and attaches grounding_verified to GenerationResult."""
    rw = RewrittenQuery(
        original_query="phạt hiệu lệnh",
        search_query="hiệu lệnh CSGT",
        must_not_have_terms=["vượt đèn đỏ"],
        target_entities=["xe_o_to"],
    )
    ref = ReferencedProvision(
        target_id="168_2024_ND-CP_D6_K16_Db",
        relation_type="THAM_CHIEU",
        title="Điểm b Khoản 16 Điều 6",
        content="trừ 04 điểm",
    )
    prov = ValidatedProvision(
        provision_id="168_2024_ND-CP_D6_K9_Dc",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text="Không chấp hành hiệu lệnh",
        cross_references=[ref],
    )
    chunk = _make_chunk("168_2024_ND-CP_D6_K9_Dc", "Không chấp hành hiệu lệnh", "6")

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="phạt hiệu lệnh",
        rewritten_query=rw,
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Người điều khiển xe ô tô không chấp hành hiệu lệnh bị phạt theo Điều 6 Nghị định 168/2024/NĐ-CP."
                }
            }
        ]
    }
    mock_session.post.return_value = mock_resp

    config = PipelineConfig(generator_use_local=True)
    gen = AnswerGenerator(config=config, session=mock_session)

    result = gen.generate(pkg)
    assert result.grounding_verified is True
    assert len(result.verification_warnings) == 0
    assert "Điều 6" in result.answer
