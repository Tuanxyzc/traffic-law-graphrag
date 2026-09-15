"""Unit tests for GraphRAGPipeline orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.pipeline.config import PipelineConfig
from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.generator import AnswerGenerator
from src.pipeline.graph_validator import GraphValidator
from src.pipeline.models import (
    EvidenceItem,
    EvidencePackage,
    GenerationResult,
    LegalValidityStatus,
    RewrittenQuery,
    ValidatedProvision,
)
from src.pipeline.pipeline import GraphRAGPipeline
from src.pipeline.rewriter import QueryRewriter
from src.rag.models import ChunkMetadata, RetrievalResult, RetrievedChunk
from src.rag.retriever import HybridRetriever


def test_orchestrator_end_to_end() -> None:
    """Test full pipeline execution flow with injected mock components."""
    # 1. Mock Rewriter
    mock_rewriter = MagicMock(spec=QueryRewriter)
    mock_rewriter.rewrite.return_value = RewrittenQuery(
        original_query="vượt đèn đỏ",
        search_query="không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        identified_keywords=["đèn tín hiệu"],
    )

    # 2. Mock Retriever
    chunk = RetrievedChunk(
        id="168_2024_ND-CP_D5_K1_Da",
        text="Phạt tiền từ 200.000 đến 400.000 đồng...",
        raw_text="Phạt tiền từ 200.000 đến 400.000 đồng...",
        metadata=ChunkMetadata(
            document_id="168_2024_ND-CP",
            dieu="5",
            tieu_de_dieu="Điều 5",
            level=4,
        ),
        score=0.03,
    )
    mock_retriever = MagicMock(spec=HybridRetriever)
    mock_retriever.retrieve.return_value = RetrievalResult(
        query="không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        top_k=5,
        chunks=[chunk],
        execution_time_ms=50.0,
    )

    # 3. Mock Validator
    vp = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk.raw_text or "",
    )
    mock_validator = MagicMock(spec=GraphValidator)
    mock_validator.validate_provisions.return_value = [vp]

    # 4. Mock EvidenceBuilder
    package = EvidencePackage(
        user_query="vượt đèn đỏ",
        rewritten_query="không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        items=[
            EvidenceItem(
                chunk_id=chunk.id,
                original_chunk_text=chunk.raw_text or "",
                validated_provision=vp,
            )
        ],
        total_chunks_retrieved=1,
        total_valid_provisions=1,
    )
    mock_builder = MagicMock(spec=EvidenceBuilder)
    mock_builder.build.return_value = package

    # 5. Mock Generator
    mock_generator = MagicMock(spec=AnswerGenerator)
    mock_generator.generate.return_value = GenerationResult(
        answer="Theo Điểm a Khoản 1 Điều 5 Nghị định 168/2024/NĐ-CP, mức phạt là...",
        citations=["Điểm a Khoản 1 Điều 5"],
    )

    # Instantiate Pipeline
    config = PipelineConfig(top_k=5)
    pipeline = GraphRAGPipeline(
        rewriter=mock_rewriter,
        retriever=mock_retriever,
        validator=mock_validator,
        evidence_builder=mock_builder,
        generator=mock_generator,
        config=config,
    )

    result = pipeline.query(
        user_query="vượt đèn đỏ", document_id="168_2024_ND-CP", top_k=3
    )

    assert result.user_query == "vượt đèn đỏ"
    assert (
        result.rewritten_query
        == "không chấp hành hiệu lệnh của đèn tín hiệu giao thông"
    )
    assert "Nghị định 168/2024/NĐ-CP" in result.answer
    assert result.citations == ["Điểm a Khoản 1 Điều 5"]
    assert result.execution_time_ms > 0
    assert result.evidence_package == package

    # Verify call arguments
    # Verify call arguments (Dual-Query RRF retrieves both rewritten query and original query)
    mock_rewriter.rewrite.assert_called_once_with("vượt đèn đỏ")
    assert mock_retriever.retrieve.call_count == 2
    mock_retriever.retrieve.assert_any_call(
        query="không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        top_k=3,
        document_id="168_2024_ND-CP",
    )
    mock_retriever.retrieve.assert_any_call(
        query="vượt đèn đỏ",
        top_k=3,
        document_id="168_2024_ND-CP",
    )
    mock_validator.validate_provisions.assert_called_once_with([chunk.id])
    mock_builder.build.assert_called_once()
    mock_generator.generate.assert_called_once_with(package)


def test_orchestrator_multi_query_retrieval() -> None:
    """Test pipeline execution when rule_query and sanction_query trigger dual retrieval."""
    mock_rewriter = MagicMock(spec=QueryRewriter)
    mock_rewriter.rewrite.return_value = RewrittenQuery(
        original_query="đi ngược chiều trên cao tốc",
        search_query="đi ngược chiều trên đường cao tốc",
        rule_query="quy tắc giao thông cấm đi ngược chiều đường cao tốc",
        sanction_query="mức phạt tiền trừ điểm giấy phép lái xe đi ngược chiều cao tốc",
        identified_keywords=["ngược chiều", "đường cao tốc"],
    )

    chunk_rule = RetrievedChunk(
        id="36_2024_QH15_D25_K1",
        text="Quy định cấm đi ngược chiều trên đường cao tốc...",
        metadata=ChunkMetadata(document_id="36_2024_QH15", dieu="25"),
        score=0.03,
    )
    chunk_sanction = RetrievedChunk(
        id="168_2024_ND-CP_D6_K11_Dđ",
        text="Phạt tiền từ 30.000.000 đến 40.000.000 đồng...",
        metadata=ChunkMetadata(document_id="168_2024_ND-CP", dieu="6"),
        score=0.035,
    )

    mock_retriever = MagicMock(spec=HybridRetriever)
    mock_retriever.retrieve.side_effect = [
        RetrievalResult(
            query="quy tắc giao thông",
            top_k=2,
            chunks=[chunk_rule],
            execution_time_ms=20.0,
        ),
        RetrievalResult(
            query="mức phạt tiền",
            top_k=4,
            chunks=[chunk_sanction],
            execution_time_ms=25.0,
        ),
    ]

    vp_rule = ValidatedProvision(
        provision_id=chunk_rule.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk_rule.text,
    )
    vp_sanction = ValidatedProvision(
        provision_id=chunk_sanction.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk_sanction.text,
    )

    mock_validator = MagicMock(spec=GraphValidator)
    mock_validator.validate_provisions.return_value = [vp_sanction, vp_rule]

    package = EvidencePackage(
        user_query="đi ngược chiều trên cao tốc",
        rewritten_query="đi ngược chiều trên đường cao tốc",
        items=[
            EvidenceItem(
                chunk_id=chunk_sanction.id,
                original_chunk_text=chunk_sanction.text,
                validated_provision=vp_sanction,
            ),
            EvidenceItem(
                chunk_id=chunk_rule.id,
                original_chunk_text=chunk_rule.text,
                validated_provision=vp_rule,
            ),
        ],
        total_chunks_retrieved=2,
        total_valid_provisions=2,
    )
    mock_builder = MagicMock(spec=EvidenceBuilder)
    mock_builder.build.return_value = package

    mock_generator = MagicMock(spec=AnswerGenerator)
    mock_generator.generate.return_value = GenerationResult(
        answer="Hành vi bị nghiêm cấm theo Luật 36/2024/QH15 và bị phạt 30-40 triệu theo Nghị định 168/2024/NĐ-CP.",
        citations=["Điều 25 Luật 36/2024/QH15", "Điều 6 Nghị định 168/2024/NĐ-CP"],
    )

    pipeline = GraphRAGPipeline(
        rewriter=mock_rewriter,
        retriever=mock_retriever,
        validator=mock_validator,
        evidence_builder=mock_builder,
        generator=mock_generator,
        config=PipelineConfig(top_k=5),
    )

    result = pipeline.query(user_query="đi ngược chiều trên cao tốc")
    assert result.user_query == "đi ngược chiều trên cao tốc"
    assert "Luật 36/2024/QH15" in result.answer
    assert "Nghị định 168/2024/NĐ-CP" in result.answer
    assert mock_retriever.retrieve.call_count == 2
    # Verify validator received both rule and sanction chunk IDs
    validated_ids = mock_validator.validate_provisions.call_args[0][0]
    assert chunk_rule.id in validated_ids
    assert chunk_sanction.id in validated_ids


def test_orchestrator_document_amendment_routing() -> None:
    """Test smart routing to direct graph traversal for document amendment queries."""
    from src.pipeline.models import DocumentAmendmentItem

    mock_rewriter = MagicMock(spec=QueryRewriter)
    mock_rewriter.rewrite.return_value = RewrittenQuery(
        original_query="những điều khoản nào trong nghị định 168 được sửa đổi bởi ND 238",
        search_query="Các điều khoản Nghị định 168 được sửa đổi bổ sung bởi Nghị định 238",
        intent="document_amendment",
        source_doc="238_2026_ND-CP",
        target_doc="168_2024_ND-CP",
        identified_keywords=["sửa đổi", "Nghị định 238", "Nghị định 168"],
    )

    mock_retriever = MagicMock(spec=HybridRetriever)
    mock_retriever.retrieve.return_value = RetrievalResult(
        query="Các điều khoản Nghị định 168 được sửa đổi bổ sung bởi Nghị định 238",
        top_k=5,
        chunks=[],
        execution_time_ms=10.0,
    )

    mock_validator = MagicMock(spec=GraphValidator)
    fake_amendments = [
        DocumentAmendmentItem(
            target_id="168_2024_ND-CP_D21_K8_Dd",
            target_title="Điểm d Khoản 8 Điều 21",
            article_id="168_2024_ND-CP_D21",
            article_title="Điều 21",
            operation="SUA_DOI",
            instruction="Sửa đổi tịch thu phương tiện",
            replacement_content="Tịch thu xe",
        )
    ]
    mock_validator.find_document_amendments.return_value = fake_amendments
    mock_validator.validate_provisions.return_value = []

    mock_builder = MagicMock(spec=EvidenceBuilder)
    pkg = EvidencePackage(
        user_query="những điều khoản nào trong nghị định 168 được sửa đổi bởi ND 238",
        rewritten_query="Các điều khoản Nghị định 168 được sửa đổi bổ sung bởi Nghị định 238",
        items=[],
        document_amendments=fake_amendments,
    )
    mock_builder.build.return_value = pkg

    mock_generator = MagicMock(spec=AnswerGenerator)
    mock_generator.generate.return_value = GenerationResult(
        answer="Nghị định 238 sửa đổi Điều 21 của Nghị định 168 về tịch thu phương tiện.",
        citations=["Điều 21 Nghị định 168/2024/NĐ-CP"],
    )

    pipeline = GraphRAGPipeline(
        rewriter=mock_rewriter,
        retriever=mock_retriever,
        validator=mock_validator,
        evidence_builder=mock_builder,
        generator=mock_generator,
        config=PipelineConfig(top_k=5),
    )

    result = pipeline.run(
        "những điều khoản nào trong nghị định 168 được sửa đổi bởi ND 238"
    )

    # Verifications
    mock_validator.find_document_amendments.assert_called_once_with(
        "238_2026_ND-CP", "168_2024_ND-CP"
    )
    mock_builder.build.assert_called_once()
    assert mock_retriever.retrieve.call_count == 1
    assert "Điều 21" in result.answer


def test_orchestrator_system_meta_query_routing() -> None:
    """Test smart routing of system meta query directly to document catalog without chunk retrieval."""
    mock_rewriter = MagicMock(spec=QueryRewriter)
    mock_rewriter.rewrite.return_value = RewrittenQuery(
        original_query="Liệt kê Các luật,nghị định mà bạn nắm rõ",
        search_query="Liệt kê Các luật,nghị định mà bạn nắm rõ",
        intent="system_meta_query",
    )

    mock_retriever = MagicMock(spec=HybridRetriever)
    mock_validator = MagicMock(spec=GraphValidator)
    mock_validator.get_all_documents.return_value = [
        {
            "id": "35_2024_QH15",
            "so_hieu": "35/2024/QH15",
            "ten": "Luật Đường bộ",
            "loai": "LUAT",
        },
        {
            "id": "168_2024_ND-CP",
            "so_hieu": "168/2024/NĐ-CP",
            "ten": "Nghị định 168",
            "loai": "NGHI_DINH",
        },
    ]

    mock_builder = MagicMock(spec=EvidenceBuilder)
    pkg = EvidencePackage(
        user_query="Liệt kê Các luật,nghị định mà bạn nắm rõ",
        rewritten_query="Liệt kê Các luật,nghị định mà bạn nắm rõ",
        system_documents=mock_validator.get_all_documents.return_value,
    )
    mock_builder.build.return_value = pkg

    mock_generator = MagicMock(spec=AnswerGenerator)
    mock_generator.generate.return_value = GenerationResult(
        answer="Các luật, nghị định gồm: Luật Đường bộ 35/2024/QH15 và Nghị định 168/2024/NĐ-CP.",
        citations=[],
    )

    pipeline = GraphRAGPipeline(
        rewriter=mock_rewriter,
        retriever=mock_retriever,
        validator=mock_validator,
        evidence_builder=mock_builder,
        generator=mock_generator,
    )

    result = pipeline.run("Liệt kê Các luật,nghị định mà bạn nắm rõ")

    # Meta query routes directly to document catalog without chunk retrieval
    mock_validator.get_all_documents.assert_called_once()
    assert mock_retriever.retrieve.call_count == 0
    assert "Luật Đường bộ" in result.answer
    assert len(result.evidence_package.system_documents) == 2
