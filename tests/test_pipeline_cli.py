"""Unit tests for Pipeline CLI entrypoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.__main__ import build_parser, main
from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.models import (
    AmendmentRecord,
    EvidenceItem,
    EvidencePackage,
    LegalValidityStatus,
    PipelineResult,
    ReferencedProvision,
    ValidatedProvision,
)


def _sample_pipeline_result() -> PipelineResult:
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D5_K1_Da",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text="Phạt tiền từ 200.000 đến 400.000 đồng...",
        parent_article_title="Điều 5. Xử phạt xe ô tô",
    )
    item = EvidenceItem(
        chunk_id="chunk-1",
        original_chunk_text="Phạt tiền từ 200.000 đến 400.000 đồng...",
        validated_provision=vp,
    )
    subgraph = EvidenceBuilder().build_subgraph([item])
    pkg = EvidencePackage(
        user_query="vượt đèn đỏ",
        rewritten_query="không chấp hành tín hiệu",
        items=[item],
        total_chunks_retrieved=1,
        total_valid_provisions=1,
        has_superseded_provisions=False,
        subgraph=subgraph,
    )
    return PipelineResult(
        user_query="vượt đèn đỏ",
        rewritten_query="không chấp hành tín hiệu",
        answer="Theo Điểm a Khoản 1 Điều 5, mức phạt là 200.000 - 400.000 đồng.",
        citations=["Điểm a Khoản 1 Điều 5"],
        evidence_package=pkg,
        subgraph=subgraph,
        execution_time_ms=123.4,
    )


def test_cli_parser_arguments() -> None:
    """Test parser argument parsing."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "vượt đèn đỏ",
            "--doc",
            "168_2024_ND-CP",
            "-k",
            "3",
            "-f",
            "json",
            "--no-rewrite",
            "-v",
        ]
    )
    assert args.query == "vượt đèn đỏ"
    assert args.doc == "168_2024_ND-CP"
    assert args.top_k == 3
    assert args.format == "json"
    assert args.no_rewrite is True
    assert args.verbose is True


def test_cli_main_text_format(capsys: pytest.CaptureFixture[str]) -> None:
    """Test CLI execution with default text format."""
    mock_res = _sample_pipeline_result()
    with patch("src.pipeline.__main__.GraphRAGPipeline") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.query.return_value = mock_res
        mock_cls.return_value = mock_instance

        exit_code = main(["vượt đèn đỏ"])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "HỆ THỐNG TRẢ LỜI PHÁP LUẬT GIAO THÔNG" in captured.out
        assert "200.000 - 400.000 đồng" in captured.out
        assert "Điểm a Khoản 1 Điều 5" in captured.out


def test_cli_main_table_format(capsys: pytest.CaptureFixture[str]) -> None:
    """Test CLI execution with table format."""
    mock_res = _sample_pipeline_result()
    with patch("src.pipeline.__main__.GraphRAGPipeline") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.query.return_value = mock_res
        mock_cls.return_value = mock_instance

        exit_code = main(["vượt đèn đỏ", "--format", "table"])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "CHI TIẾT BẰNG CHỨNG PHÁP LÝ" in captured.out
        assert "Provision ID" in captured.out
        assert "168_2024_ND-CP_D5_K1_Da" in captured.out


def test_cli_main_json_format(capsys: pytest.CaptureFixture[str]) -> None:
    """Test CLI execution with json format."""
    mock_res = _sample_pipeline_result()
    with patch("src.pipeline.__main__.GraphRAGPipeline") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.query.return_value = mock_res
        mock_cls.return_value = mock_instance

        exit_code = main(["vượt đèn đỏ", "--format", "json"])
        assert exit_code == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["user_query"] == "vượt đèn đỏ"
        assert "200.000 - 400.000 đồng" in data["answer"]
        assert "subgraph" in data
        assert "nodes" in data["subgraph"]
        assert "relationships" in data["subgraph"]
        assert len(data["subgraph"]["nodes"]) >= 1


def test_cli_main_exception_handling(capsys: pytest.CaptureFixture[str]) -> None:
    """Test CLI handles pipeline exceptions gracefully with error code 1."""
    with patch("src.pipeline.__main__.GraphRAGPipeline") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.query.side_effect = RuntimeError("Database unreachable")
        mock_cls.return_value = mock_instance

        exit_code = main(["câu hỏi"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Database unreachable" in captured.err


def test_cli_main_graph_traversal_tree_display(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test CLI renders graph traversal tree with Hop 1, Hop 2, and amendments."""
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D6_K5_Dh",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text="Dùng tay sử dụng điện thoại khi lái xe ô tô...",
        parent_article_id="168_2024_ND-CP_D6",
        parent_article_title="Điều 6. Xử phạt xe ô tô",
        parent_clause_number="5",
        amendments=[
            AmendmentRecord(
                operation="SUA_DOI",
                instruction="Sửa đổi mức phạt tiền",
                by_document="238_2026_ND-CP",
                replacement_text="Phạt tiền từ 5.000.000 đến 7.000.000 đồng",
                direction="INCOMING",
            )
        ],
        cross_references=[
            ReferencedProvision(
                target_id="168_2024_ND-CP_D6_K16_Db",
                relation_type="TRU_DIEM_GPLX",
                direction="INCOMING",
                hop_level=1,
                content="Bị trừ 04 điểm giấy phép lái xe theo quy định",
            ),
            ReferencedProvision(
                target_id="168_2024_ND-CP_D51_K1",
                relation_type="REFERENCES",
                direction="OUTGOING",
                hop_level=2,
                content="Giấy phép lái xe được phục hồi điểm sau 12 tháng",
            ),
        ],
    )
    item = EvidenceItem(
        chunk_id="chunk-phone-car",
        original_chunk_text="Dùng tay sử dụng điện thoại khi lái xe ô tô...",
        validated_provision=vp,
        score=0.032,
    )
    subgraph = EvidenceBuilder().build_subgraph([item])
    pkg = EvidencePackage(
        user_query="dùng điện thoại lái ô tô phạt sao",
        rewritten_query="mức phạt dùng điện thoại lái xe",
        items=[item],
        total_chunks_retrieved=1,
        total_valid_provisions=1,
        subgraph=subgraph,
    )
    res = PipelineResult(
        user_query="dùng điện thoại lái ô tô phạt sao",
        rewritten_query="mức phạt dùng điện thoại lái xe",
        answer="Phạt từ 5 - 7 triệu và trừ 4 điểm GPLX.",
        citations=["Điểm h Khoản 5 Điều 6"],
        evidence_package=pkg,
        subgraph=subgraph,
        execution_time_ms=88.5,
    )

    with patch("src.pipeline.__main__.GraphRAGPipeline") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.query.return_value = res
        mock_cls.return_value = mock_instance

        exit_code = main(["dùng điện thoại lái ô tô phạt sao"])
        assert exit_code == 0

        captured = capsys.readouterr()
        # Verify Graph Traversal header & structure
        assert "KNOWLEDGE GRAPH TRAVERSAL (CÁC NODES & QUAN HỆ ĐÃ DUYỆT)" in captured.out
        assert "ANCHOR (Gốc trích xuất RAG): 168_2024_ND-CP_D6_K5_Dh" in captured.out
        assert "Điều 6. Xử phạt xe ô tô" in captured.out
        # Hop 1 sanction
        assert "[Hop 1 : TRU_DIEM_GPLX] 168_2024_ND-CP_D6_K16_Db" in captured.out
        assert "Bị trừ 04 điểm giấy phép lái xe" in captured.out
        # Hop 2 reference
        assert "[Hop 2 : REFERENCES] 168_2024_ND-CP_D51_K1" in captured.out
        assert "Giấy phép lái xe được phục hồi điểm sau 12 tháng" in captured.out
        # Amendment
        assert "[AMENDS : SUA_DOI]" in captured.out
        assert "238_2026_ND-CP" in captured.out
        # Subgraph summary
        assert "TỔNG KẾT KNOWLEDGE SUBGRAPH" in captured.out


def test_cli_main_table_format_with_traversal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test CLI table format includes both evidence table and traversal table."""
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D7_K4_Da",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text="Sử dụng điện thoại khi điều khiển xe mô tô...",
        cross_references=[
            ReferencedProvision(
                target_id="168_2024_ND-CP_D7_K13_Db",
                relation_type="TRU_DIEM_GPLX",
                direction="INCOMING",
                hop_level=1,
                content="Bị trừ 02 điểm giấy phép lái xe",
            )
        ],
    )
    item = EvidenceItem(
        chunk_id="chunk-moto",
        original_chunk_text="Sử dụng điện thoại khi điều khiển xe mô tô...",
        validated_provision=vp,
    )
    subgraph = EvidenceBuilder().build_subgraph([item])
    pkg = EvidencePackage(
        user_query="dùng điện thoại xe máy",
        rewritten_query="mức phạt điện thoại xe máy",
        items=[item],
        subgraph=subgraph,
    )
    res = PipelineResult(
        user_query="dùng điện thoại xe máy",
        rewritten_query="mức phạt điện thoại xe máy",
        answer="Phạt 800k - 1tr và trừ 2 điểm.",
        citations=["Điểm a Khoản 4 Điều 7"],
        evidence_package=pkg,
        subgraph=subgraph,
        execution_time_ms=50.0,
    )

    with patch("src.pipeline.__main__.GraphRAGPipeline") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.query.return_value = res
        mock_cls.return_value = mock_instance

        exit_code = main(["dùng điện thoại xe máy", "--format", "table"])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "CHI TIẾT BẰNG CHỨNG PHÁP LÝ" in captured.out
        assert "CÁC QUAN HỆ GRAPH TRAVERSAL MỞ RỘNG (1-HOP & 2-HOP)" in captured.out
        assert "168_2024_ND-CP_D7_K13_Db" in captured.out
        assert "TRU_DIEM_GPLX" in captured.out

