"""Unit tests for Pipeline CLI entrypoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.__main__ import build_parser, main
from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.models import (
    EvidenceItem,
    EvidencePackage,
    LegalValidityStatus,
    PipelineResult,
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
