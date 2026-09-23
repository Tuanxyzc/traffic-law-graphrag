"""Unit tests for GraphValidator and status determination."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.graph.neo4j.connection import Neo4jClient
from src.pipeline.config import PipelineConfig
from src.pipeline.graph_validator import (
    GraphValidator,
    determine_legal_status,
)
from src.pipeline.models import (
    AmendmentRecord,
    LegalValidityStatus,
)


def test_determine_legal_status_active() -> None:
    """Test active provision with effective status."""
    v_info = {
        "version_id": "v1",
        "is_current": True,
        "effective_status": "EFFECTIVE",
    }
    status, is_current = determine_legal_status(v_info, [])
    assert status == LegalValidityStatus.DANG_CO_HIEU_LUC
    assert is_current is True


def test_determine_legal_status_superseded() -> None:
    """Test provision superseded by amendment."""
    v_info = {
        "version_id": "v1",
        "is_current": False,
        "effective_status": "SUPERSEDED",
    }
    status, is_current = determine_legal_status(v_info, [])
    assert status == LegalValidityStatus.DA_BI_THAY_THE
    assert is_current is False

    # Also test via amendment operation
    am = AmendmentRecord(
        operation="THAY_THE",
        instruction="Thay thế bằng Điều mới",
    )
    status2, is_current2 = determine_legal_status(None, [am])
    assert status2 == LegalValidityStatus.DA_BI_THAY_THE
    assert is_current2 is False


def test_determine_legal_status_repealed() -> None:
    """Test provision repealed by amendment or status."""
    v_info = {
        "version_id": "v1",
        "is_current": False,
        "effective_status": "REPEALED",
    }
    status, is_current = determine_legal_status(v_info, [])
    assert status == LegalValidityStatus.DA_BI_BAI_BO
    assert is_current is False

    am = AmendmentRecord(
        operation="BAI_BO",
        instruction="Bãi bỏ điểm này",
    )
    status2, is_current2 = determine_legal_status(None, [am])
    assert status2 == LegalValidityStatus.DA_BI_BAI_BO
    assert is_current2 is False


def test_determine_legal_status_expired() -> None:
    """Test expired provision."""
    v_info = {
        "version_id": "v1",
        "is_current": False,
        "effective_status": "EXPIRED",
    }
    status, is_current = determine_legal_status(v_info, [])
    assert status == LegalValidityStatus.HET_HIEU_LUC
    assert is_current is False


def test_graph_validator_empty_input() -> None:
    """Test that empty IDs list returns [] without querying database."""
    mock_client = MagicMock(spec=Neo4jClient)
    validator = GraphValidator(client=mock_client)
    res = validator.validate_provisions([])
    assert res == []
    mock_client.session.assert_not_called()


def test_graph_validator_query_mapping() -> None:
    """Test validation mapping from Neo4j records."""
    mock_client = MagicMock(spec=Neo4jClient)
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    fake_record = {
        "provision_id": "168_2024_ND-CP_D5_K1_Da",
        "level": "Point",
        "document_id": "168_2024_ND-CP",
        "document_title": "Nghị định 168/2024/NĐ-CP",
        "parent_article_id": "168_2024_ND-CP_D5",
        "parent_article_title": "Điều 5. Xử phạt người điều khiển xe ô tô",
        "parent_clause_id": "168_2024_ND-CP_D5_K1",
        "parent_clause_number": "1",
        "version_info": {
            "version_id": "v_168_2024_ND-CP_D5_K1_Da",
            "valid_from": "2025-01-01",
            "valid_to": None,
            "is_current": True,
            "content_text": "Phạt tiền từ 200.000 đến 400.000 đồng...",
            "effective_status": "EFFECTIVE",
        },
        "amendments": [
            {
                "operation": "SUA_DOI",
                "instruction": "Sửa đổi câu chữ",
                "by_document": "168/2024/ND-CP",
                "effective_from": "2025-01-01",
            }
        ],
        "references": [
            {
                "target_id": "168_2024_ND-CP_D6_K1",
                "relation_type": "THAM_CHIEU",
                "document_id": "168_2024_ND-CP",
                "title": "Khoản 1 Điều 6",
                "content": "Nội dung tham chiếu...",
            }
        ],
    }
    mock_session.run.return_value = [fake_record]

    config = PipelineConfig()
    validator = GraphValidator(config=config, client=mock_client)
    res = validator.validate_provisions(["168_2024_ND-CP_D5_K1_Da"])

    assert len(res) == 1
    item = res[0]
    assert item.provision_id == "168_2024_ND-CP_D5_K1_Da"
    assert item.level == "POINT"
    assert item.status == LegalValidityStatus.DANG_CO_HIEU_LUC
    assert item.is_current is True
    assert item.parent_article_title == "Điều 5. Xử phạt người điều khiển xe ô tô"
    assert item.parent_clause_number == "1"
    assert len(item.amendments) == 1
    assert item.amendments[0].operation == "SUA_DOI"
    assert len(item.cross_references) == 1
    assert item.cross_references[0].target_id == "168_2024_ND-CP_D6_K1"


def test_graph_validator_exception_handling() -> None:
    """Test that database exceptions return [] gracefully."""
    mock_client = MagicMock(spec=Neo4jClient)
    mock_client.session.side_effect = RuntimeError("Database connection lost")

    validator = GraphValidator(client=mock_client)
    res = validator.validate_provisions(["some_id"])
    assert res == []


def test_extract_replacement_text() -> None:
    """Test extracting replacement text from JSON payload or phrase replacements."""
    from src.pipeline.graph_validator import extract_replacement_text

    # 1. JSON payload dict with 'content'
    json_payload = (
        '{"number": "b", "content": "b) Chở hàng trên nóc xe trên 10% chiều dài xe..."}'
    )
    assert (
        extract_replacement_text(json_payload)
        == "b) Chở hàng trên nóc xe trên 10% chiều dài xe..."
    )

    # 2. Text phrase replacement (old -> new)
    assert (
        extract_replacement_text(
            None, new_text="Bộ Xây dựng", old_text="Bộ Giao thông vận tải"
        )
        == "Thay thế cụm từ 'Bộ Giao thông vận tải' bằng 'Bộ Xây dựng'"
    )

    # 3. Text general
    assert (
        extract_replacement_text(None, general_text="nội dung chung")
        == "nội dung chung"
    )

    # 4. None / empty
    assert extract_replacement_text(None) is None


def test_graph_validator_bidirectional_amendments() -> None:
    """Test validation mapping for both INCOMING and OUTGOING amendments with replacements."""
    mock_client = MagicMock(spec=Neo4jClient)
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    fake_record = {
        "provision_id": "168_2024_ND-CP_D21_K2_Db",
        "level": "Point",
        "document_id": "168_2024_ND-CP",
        "document_title": "Nghị định 168/2024/NĐ-CP",
        "parent_article_id": "168_2024_ND-CP_D21",
        "parent_article_title": "Điều 21. Xử phạt các vi phạm khác",
        "parent_clause_id": "168_2024_ND-CP_D21_K2",
        "parent_clause_number": "2",
        "version_info": {
            "version_id": "168_2024_ND-CP_D21_K2_Db_V2",
            "valid_from": "2026-08-15",
            "valid_to": None,
            "is_current": True,
            "content_text": "b) Chở hàng trên nóc thùng xe... trên 10% chiều dài xe",
            "effective_status": "NORMAL",
        },
        "amendments": [
            {
                "operation": "SUA_DOI",
                "instruction": "1. Sửa đổi, bổ sung điểm b khoản 2 như sau:",
                "by_document": "238/2026/ND-CP",
                "effective_from": "2026-08-15",
                "replacement_payload": '{"number": "b", "content": "b) Chở hàng trên nóc thùng xe... trên 10% chiều dài xe"}',
                "source_provision_id": "238_2026_ND-CP_D8_K1",
                "target_provision_id": "168_2024_ND-CP_D21_K2_Db",
                "direction": "INCOMING",
            },
            {
                "operation": "SUA_DOI",
                "instruction": "Sửa đổi liên kết",
                "by_document": "168/2024/ND-CP",
                "effective_from": "2026-08-15",
                "text_new": "Bộ Xây dựng",
                "text_old": "Bộ Giao thông",
                "source_provision_id": "168_2024_ND-CP_D21_K2_Db",
                "target_provision_id": "other_prov",
                "direction": "OUTGOING",
            },
        ],
        "references": [],
    }
    mock_session.run.return_value = [fake_record]

    validator = GraphValidator(client=mock_client)
    res = validator.validate_provisions(["168_2024_ND-CP_D21_K2_Db"])

    assert len(res) == 1
    prov = res[0]
    assert prov.status == LegalValidityStatus.DANG_CO_HIEU_LUC
    assert prov.is_current is True
    assert len(prov.amendments) == 2

    # Incoming
    am_in = prov.amendments[0]
    assert am_in.direction == "INCOMING"
    assert am_in.by_document == "238/2026/ND-CP"
    assert (
        am_in.replacement_text
        == "b) Chở hàng trên nóc thùng xe... trên 10% chiều dài xe"
    )
    assert am_in.source_provision_id == "238_2026_ND-CP_D8_K1"

    # Outgoing
    am_out = prov.amendments[1]
    assert am_out.direction == "OUTGOING"
    assert (
        am_out.replacement_text == "Thay thế cụm từ 'Bộ Giao thông' bằng 'Bộ Xây dựng'"
    )
    assert am_out.target_provision_id == "other_prov"


def test_find_document_amendments_mock() -> None:
    """Test find_document_amendments with mocked Neo4j records."""
    mock_client = MagicMock(spec=Neo4jClient)
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    fake_records = [
        {
            "target_id": "168_2024_ND-CP_D21_K8_Dd",
            "target_title": "Điểm d Khoản 8 Điều 21",
            "article_id": "168_2024_ND-CP_D21",
            "article_title": "Điều 21. Xử phạt các hành vi vi phạm khác",
            "operation": "SUA_DOI",
            "instruction": "Sửa đổi điểm d khoản 8 Điều 21",
            "replacement_payload": '{"content": "Tịch thu phương tiện"}',
            "text_new": None,
            "text_old": None,
            "text_general": None,
        }
    ]
    mock_session.run.return_value = fake_records

    validator = GraphValidator(client=mock_client)
    items = validator.find_document_amendments("238", "168")

    assert len(items) == 1
    item = items[0]
    assert item.target_id == "168_2024_ND-CP_D21_K8_Dd"
    assert item.article_id == "168_2024_ND-CP_D21"
    assert item.operation == "SUA_DOI"
    assert item.replacement_content == "Tịch thu phương tiện"


def test_find_document_amendments_empty_or_error() -> None:
    """Test find_document_amendments handles empty inputs and exceptions gracefully."""
    validator = GraphValidator()
    assert validator.find_document_amendments("") == []
    assert validator.find_document_amendments("   ") == []

    mock_client = MagicMock(spec=Neo4jClient)
    mock_session = MagicMock()
    mock_session.run.side_effect = Exception("Neo4j database down")
    mock_client.session.return_value.__enter__.return_value = mock_session

    v_err = GraphValidator(client=mock_client)
    assert v_err.find_document_amendments("238", "168") == []
