"""Tests for multi-hop (2-hop) statutory graph traversal, anchor matching, and LLM evidence formatting."""

from unittest.mock import MagicMock

import pytest

from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.graph_validator import GraphValidator
from src.pipeline.models import (
    EvidenceItem,
    EvidencePackage,
    LegalValidityStatus,
    ReferencedProvision,
    ValidatedProvision,
)


class TestGraphTraversalMultiHop:
    """Test suite for 2-hop statutory graph traversal logic."""

    def test_mocked_graph_validator_2hop_unpacking(self) -> None:
        """Verifies GraphValidator correctly unpacks Hop 1 and Hop 2 references with hop_level."""
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_client.session.return_value.__enter__.return_value = mock_session

        fake_record = {
            "provision_id": "168_2024_ND-CP_D7_K7_Dc",
            "level": "POINT",
            "document_id": "168_2024_ND-CP",
            "document_title": "Nghị định 168/2024/NĐ-CP",
            "parent_article_id": "168_2024_ND-CP_D7",
            "parent_article_title": "Xử phạt vi phạm giao thông xe mô tô",
            "parent_clause_id": "168_2024_ND-CP_D7_K7",
            "parent_clause_number": "7",
            "parent_clause_content": "Phạt tiền từ 800.000 đồng đến 1.000.000 đồng",
            "version_info": {
                "version_id": "168_2024_ND-CP_D7_K7_Dc_V1",
                "valid_from": "2025-01-01",
                "valid_to": None,
                "is_current": True,
                "content_text": "Không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
                "effective_status": "DANG_CO_HIEU_LUC",
            },
            "amendments": [],
            "references": [
                {
                    "target_id": "168_2024_ND-CP_D7_K13_Db",
                    "relation_type": "TRU_DIEM_GPLX",
                    "document_id": "168_2024_ND-CP",
                    "title": "Khoản 13 Điểm b",
                    "content": "Bị trừ điểm giấy phép lái xe 04 điểm",
                    "direction": "INCOMING",
                    "hop_level": 1,
                },
                {
                    "target_id": "36_2024_QH15_D58",
                    "relation_type": "REFERENCES",
                    "document_id": "36_2024_QH15",
                    "title": "Điều 58",
                    "content": "Phục hồi điểm giấy phép lái xe sau 12 tháng",
                    "direction": "OUTGOING",
                    "hop_level": 2,
                },
            ],
        }
        mock_session.run.return_value = [fake_record]

        validator = GraphValidator(client=mock_client)
        results = validator.validate_provisions(["168_2024_ND-CP_D7_K7_Dc"])

        assert len(results) == 1
        prov = results[0]
        assert prov.provision_id == "168_2024_ND-CP_D7_K7_Dc"
        assert prov.parent_article_title == "Xử phạt vi phạm giao thông xe mô tô"
        assert len(prov.cross_references) == 2

        ref_h1 = prov.cross_references[0]
        assert ref_h1.target_id == "168_2024_ND-CP_D7_K13_Db"
        assert ref_h1.relation_type == "TRU_DIEM_GPLX"
        assert ref_h1.hop_level == 1
        assert ref_h1.direction == "INCOMING"

        ref_h2 = prov.cross_references[1]
        assert ref_h2.target_id == "36_2024_QH15_D58"
        assert ref_h2.hop_level == 2
        assert ref_h2.direction == "OUTGOING"

    def test_evidence_builder_formatting_with_2hop(self) -> None:
        """Verifies EvidenceBuilder creates separate prompt sections for Hop 1 sanctions, Hop 1 direct refs, and Hop 2 extended refs."""
        prov = ValidatedProvision(
            provision_id="168_2024_ND-CP_D7_K7_Dc",
            level="POINT",
            status=LegalValidityStatus.DANG_CO_HIEU_LUC,
            is_current=True,
            content_text="Không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
            parent_article_id="168_2024_ND-CP_D7",
            parent_article_title="Xử phạt xe mô tô, xe gắn máy vi phạm quy tắc giao thông",
            parent_clause_number="7",
            parent_clause_content="Phạt tiền từ 800.000 đồng đến 1.000.000 đồng",
            cross_references=[
                ReferencedProvision(
                    target_id="168_2024_ND-CP_D7_K13_Db",
                    relation_type="TRU_DIEM_GPLX",
                    title="Khoản 13 Điểm b",
                    content="Bị trừ điểm giấy phép lái xe 04 điểm",
                    direction="INCOMING",
                    hop_level=1,
                ),
                ReferencedProvision(
                    target_id="168_2024_ND-CP_D7_K1_Da",
                    relation_type="THAM_CHIEU",
                    title="Khoản 1 Điểm a",
                    content="Chấp hành hiệu lệnh biển báo",
                    direction="OUTGOING",
                    hop_level=1,
                ),
                ReferencedProvision(
                    target_id="36_2024_QH15_D58",
                    relation_type="CAN_CU_VAO",
                    title="Điều 58 Luật Trật tự an toàn giao thông đường bộ 2024",
                    content="Giấy phép lái xe được phục hồi đủ 12 điểm khi không bị trừ điểm trong thời hạn 12 tháng",
                    direction="OUTGOING",
                    hop_level=2,
                ),
            ],
        )

        item = EvidenceItem(
            chunk_id="chunk_1",
            unit_id="168_2024_ND-CP_D7_K7_Dc",
            original_chunk_text="Điểm c Khoản 7: Không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
            validated_provision=prov,
        )

        pkg = EvidencePackage(
            user_query="Vượt đèn đỏ xe máy bị trừ mấy điểm và khi nào được hồi điểm?",
            rewritten_query="Xử phạt không chấp hành đèn tín hiệu giao thông xe mô tô và phục hồi điểm GPLX",
            items=[item],
        )

        builder = EvidenceBuilder()
        formatted = builder.format_for_llm(pkg)

        # 1. Check article title is presented as category constraint
        assert "ĐIỀU LUẬT / ĐỐI TƯỢNG ÁP DỤNG: Xử phạt xe mô tô, xe gắn máy" in formatted

        # 2. Check Hop 1 sanction is present under dedicated section
        assert "HÌNH THỨC XỬ PHẠT BỔ SUNG & TRỪ ĐIỂM GIẤY PHÉP LÁI XE (GPLX) ÁP DỤNG:" in formatted
        assert "TRU_DIEM_GPLX" in formatted
        assert "Bị trừ điểm giấy phép lái xe 04 điểm" in formatted

        # 3. Check Hop 1 direct reference section
        assert "DẪN CHIẾU THAM CHIẾU LIÊN QUAN TRỰC TIẾP (HOP 1):" in formatted
        assert "Chấp hành hiệu lệnh biển báo" in formatted

        # 4. Check Hop 2 multi-hop graph traversal section
        assert "QUY ĐỊNH LIÊN QUAN MỞ RỘNG (HOP 2 - MULTI-HOP GRAPH TRAVERSAL):" in formatted
        assert "Hop 2 - CAN_CU_VAO" in formatted
        assert "Điều 58 Luật Trật tự an toàn giao thông đường bộ 2024" in formatted
        assert "phục hồi đủ 12 điểm" in formatted

    def test_evidence_builder_graph_serialization_hop_level(self) -> None:
        """Verifies graph serialization retains hop_level property on relationship edges."""
        prov = ValidatedProvision(
            provision_id="TEST_PROV_1",
            level="POINT",
            status=LegalValidityStatus.DANG_CO_HIEU_LUC,
            is_current=True,
            content_text="Sample content",
            cross_references=[
                ReferencedProvision(
                    target_id="REF_HOP_1",
                    relation_type="TRU_DIEM_GPLX",
                    direction="INCOMING",
                    hop_level=1,
                ),
                ReferencedProvision(
                    target_id="REF_HOP_2",
                    relation_type="THAM_CHIEU",
                    direction="OUTGOING",
                    hop_level=2,
                ),
            ],
        )

        item = EvidenceItem(
            chunk_id="chunk_2",
            unit_id="TEST_PROV_1",
            original_chunk_text="Sample text",
            validated_provision=prov,
        )

        pkg = EvidencePackage(
            user_query="test query",
            rewritten_query="test query",
            items=[item],
        )

        builder = EvidenceBuilder()
        subgraph = builder.build_subgraph(pkg.items)

        edges = subgraph.relationships
        edge1 = next(e for e in edges if e.source == "REF_HOP_1" and e.target == "TEST_PROV_1")
        assert edge1.properties["hop_level"] == 1
        assert edge1.properties["direction"] == "INCOMING"

        edge2 = next(e for e in edges if e.source == "TEST_PROV_1" and e.target == "REF_HOP_2")
        assert edge2.properties["hop_level"] == 2
        assert edge2.properties["direction"] == "OUTGOING"


@pytest.mark.integration
class TestLiveGraphTraversalMultiHop:
    """Integration test checking multi-hop traversal against real local Neo4j database."""

    def test_live_neo4j_multihop_traversal(self) -> None:
        """Verifies live Neo4j retrieves Hop 1 and Hop 2 nodes with current version validation."""
        validator = GraphValidator()
        # 168_2024_ND-CP_D7_K7_Dc is motorbike red light violation in Decree 168
        results = validator.validate_provisions(["168_2024_ND-CP_D7_K7_Dc"])
        assert len(results) == 1
        prov = results[0]
        assert prov.parent_article_title is not None
        assert "xe mô tô" in prov.parent_article_title.lower()

        # Must catch incoming penalty point deduction from Khoản 13
        tru_diem = [r for r in prov.cross_references if r.relation_type == "TRU_DIEM_GPLX"]
        assert len(tru_diem) >= 1
        assert tru_diem[0].hop_level == 1
        assert "trừ điểm" in (tru_diem[0].content or "").lower()
