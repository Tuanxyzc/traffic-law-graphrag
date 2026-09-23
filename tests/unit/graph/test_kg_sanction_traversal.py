"""Tests for kg-sanction-traversal module (Pure Topological Graph Traversal & LLM Normative Reasoning).

Verifies:
1. Cypher query in GraphValidator retrieves 1-hop bidirectional references without keyword regex.
2. GraphValidator maps incoming/outgoing references with pure relation types.
3. EvidenceBuilder formats 1-hop reference nodes faithfully without arbitrary regex splitting.
4. Context stays lean without parent_clause_content duplication.
5. GENERATE_SYSTEM_PROMPT contains normative reasoning guidance for sanctions vs police powers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.graph_validator import VALIDATION_CYPHER_QUERY, GraphValidator
from src.pipeline.models import (
    LegalValidityStatus,
    ReferencedProvision,
    ValidatedProvision,
)
from src.pipeline.prompts import GENERATE_SYSTEM_PROMPT
from src.rag.models import ChunkMetadata, RetrievedChunk


def _make_chunk(chunk_id: str, text: str, article: str, clause: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        text=text,
        raw_text=text,
        metadata=ChunkMetadata(
            document_id="168_2024_ND-CP",
            dieu=article,
            khoan=clause,
            tieu_de_dieu=f"Điều {article}",
            level=4,
        ),
        score=0.03,
        dense_score=0.85,
        sparse_score=12.5,
        dense_rank=1,
        sparse_rank=2,
    )


def test_cypher_query_has_no_regex_keyword_matching() -> None:
    """Acceptance criteria: Cypher query must NOT contain hardcoded regex pattern traps."""
    assert "=~" not in VALIDATION_CYPHER_QUERY
    assert "trừ điểm" not in VALIDATION_CYPHER_QUERY.lower()
    assert "tước quyền" not in VALIDATION_CYPHER_QUERY.lower()
    # Must support bidirectional 1-hop traversal via THAM_CHIEU / REFERENCES / EXCEPTION_TO
    assert "THAM_CHIEU" in VALIDATION_CYPHER_QUERY
    assert "r_out" in VALIDATION_CYPHER_QUERY
    assert "r_in" in VALIDATION_CYPHER_QUERY


def test_graph_validator_pure_traversal_mapping() -> None:
    """Verifies that GraphValidator maps incoming references naturally without regex filtering."""
    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    mock_record = {
        "provision_id": "168_2024_ND-CP_D6_K9_Dc",
        "level": "Point",
        "document_id": "168_2024_ND-CP",
        "document_title": "Nghị định 168/2024/NĐ-CP",
        "parent_article_id": "168_2024_ND-CP_D6",
        "parent_article_title": "Điều 6. Xử phạt người lái xe ô tô",
        "parent_clause_id": "168_2024_ND-CP_D6_K9",
        "parent_clause_number": "9",
        "parent_clause_content": None,
        "version_info": {
            "version_id": "v1",
            "valid_from": "2025-01-01",
            "valid_to": None,
            "is_current": True,
            "content_text": "c) Không chấp hành hiệu lệnh của người điều khiển giao thông...",
            "effective_status": "EFFECTIVE",
        },
        "amendments": [],
        "references": [
            {
                "target_id": "168_2024_ND-CP_D6_K16_Db",
                "relation_type": "THAM_CHIEU",
                "document_id": "168_2024_ND-CP",
                "title": "Điểm b Khoản 16 Điều 6",
                "content": "b) Thực hiện hành vi quy định tại điểm c khoản 9 Điều này bị trừ điểm giấy phép lái xe 04 điểm;",
                "direction": "INCOMING",
            }
        ],
    }

    mock_session.run.return_value = [mock_record]
    validator = GraphValidator(client=mock_client)

    provisions = validator.validate_provisions(["168_2024_ND-CP_D6_K9_Dc"])
    assert len(provisions) == 1
    prov = provisions[0]

    assert prov.provision_id == "168_2024_ND-CP_D6_K9_Dc"
    assert len(prov.cross_references) == 1
    ref = prov.cross_references[0]
    assert ref.target_id == "168_2024_ND-CP_D6_K16_Db"
    assert ref.direction == "INCOMING"
    assert ref.relation_type == "THAM_CHIEU"
    assert ref.title == "Điểm b Khoản 16 Điều 6"
    assert "trừ điểm giấy phép lái xe 04 điểm" in (ref.content or "")


def test_graph_validator_motorcycle_traversal_mapping() -> None:
    """Verifies that GraphValidator maps motorcycle references (D7_K7_Dd <- D7_K13_Db) naturally."""
    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    mock_record = {
        "provision_id": "168_2024_ND-CP_D7_K7_Dd",
        "level": "Point",
        "document_id": "168_2024_ND-CP",
        "document_title": "Nghị định 168/2024/NĐ-CP",
        "parent_article_id": "168_2024_ND-CP_D7",
        "parent_article_title": "Điều 7. Xử phạt người lái xe mô tô, xe gắn máy",
        "parent_clause_id": "168_2024_ND-CP_D7_K7",
        "parent_clause_number": "7",
        "parent_clause_content": None,
        "version_info": {
            "version_id": "v2",
            "valid_from": "2025-01-01",
            "valid_to": None,
            "is_current": True,
            "content_text": "d) Không chấp hành hiệu lệnh của người điều khiển giao thông...",
            "effective_status": "EFFECTIVE",
        },
        "amendments": [],
        "references": [
            {
                "target_id": "168_2024_ND-CP_D7_K13_Db",
                "relation_type": "THAM_CHIEU",
                "document_id": "168_2024_ND-CP",
                "title": "Điểm b Khoản 13 Điều 7",
                "content": "b) Thực hiện hành vi quy định tại điểm d khoản 7 Điều này bị trừ điểm giấy phép lái xe 04 điểm;",
                "direction": "INCOMING",
            }
        ],
    }

    mock_session.run.return_value = [mock_record]
    validator = GraphValidator(client=mock_client)

    provisions = validator.validate_provisions(["168_2024_ND-CP_D7_K7_Dd"])
    assert len(provisions) == 1
    prov = provisions[0]

    assert prov.provision_id == "168_2024_ND-CP_D7_K7_Dd"
    assert len(prov.cross_references) == 1
    ref = prov.cross_references[0]
    assert ref.target_id == "168_2024_ND-CP_D7_K13_Db"
    assert ref.direction == "INCOMING"
    assert ref.relation_type == "THAM_CHIEU"
    assert ref.title == "Điểm b Khoản 13 Điều 7"
    assert "trừ điểm giấy phép lái xe 04 điểm" in (ref.content or "")


def test_evidence_builder_faithful_1hop_formatting() -> None:
    """Acceptance criteria: EvidenceBuilder formats 1-hop reference nodes cleanly under unified section."""
    chunk_car = _make_chunk(
        "168_2024_ND-CP_D6_K9_Dc",
        "9. Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng đối với người điều khiển xe thực hiện một trong các hành vi vi phạm sau đây:\n"
        "c) Không chấp hành hiệu lệnh của người điều khiển giao thông hoặc người kiểm soát giao thông;",
        "6",
        "9",
    )

    car_ref = ReferencedProvision(
        target_id="168_2024_ND-CP_D6_K16_Db",
        relation_type="THAM_CHIEU",
        title="Điểm b Khoản 16 Điều 6",
        content="b) Thực hiện hành vi quy định tại điểm c khoản 9 Điều này bị trừ điểm giấy phép lái xe 04 điểm;",
        direction="INCOMING",
    )

    car_prov = ValidatedProvision(
        provision_id=chunk_car.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk_car.raw_text or "",
        parent_article_title="Điều 6. Xử phạt người điều khiển xe ô tô",
        parent_clause_number="9",
        document_title="Nghị định 168/2024/NĐ-CP",
        cross_references=[car_ref],
    )

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="Không chấp hành hiệu lệnh CSGT phạt bao nhiêu",
        rewritten_query="không chấp hành hiệu lệnh người điều khiển giao thông",
        retrieved_chunks=[chunk_car],
        validated_provisions=[car_prov],
    )

    llm_context = builder.format_for_llm(pkg)

    # 1. Section header must be clean and unified
    assert "CÁC QUY ĐỊNH THAM CHIẾU LIÊN QUAN TỪ ĐỒ THỊ (1-HOP):" in llm_context
    # 2. Must contain directional tag, relation type, title, and raw statutory text
    assert (
        "• [INCOMING] [THAM_CHIEU] Căn cứ Điểm b Khoản 16 Điều 6: b) Thực hiện hành vi quy định tại điểm c khoản 9 Điều này bị trừ điểm giấy phép lái xe 04 điểm;"
        in llm_context
    )
    # 3. Must NOT contain arbitrary legacy regex split headings
    assert (
        "HÌNH THỨC XỬ PHẠT BỔ SUNG & TRỪ ĐIỂM GIẤY PHÉP LÁI XE (GPLX) ÁP DỤNG:"
        not in llm_context
    )
    assert "DẪN CHIẾU THAM CHIẾU LIÊN QUAN KHÁC (1-HOP):" not in llm_context


def test_lean_context_no_parent_clause_duplication() -> None:
    """Verifies that parent_clause_content is None in ValidatedProvision to avoid diluting context."""
    chunk = _make_chunk(
        "168_2024_ND-CP_D7_K7_Dd",
        "7. Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng đối với người điều khiển xe thực hiện một trong các hành vi vi phạm sau đây:\n"
        "d) Không chấp hành hiệu lệnh của người điều khiển giao thông hoặc người kiểm soát giao thông;",
        "7",
        "7",
    )
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk.raw_text or "",
        parent_clause_content=None,
    )
    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="phạt vượt hiệu lệnh",
        rewritten_query="hiệu lệnh CSGT",
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )
    item = pkg.items[0]
    assert item.validated_provision.parent_clause_content is None


def test_generate_system_prompt_normative_reasoning() -> None:
    """Acceptance criteria: GENERATE_SYSTEM_PROMPT instructs LLM to perform 1-hop normative reasoning and distinguish sanctions from police powers."""
    # 1. 1-hop reference reasoning
    assert "ĐỐI CHIẾU THAM CHIẾU 1-HOP" in GENERATE_SYSTEM_PROMPT
    assert (
        "CÁC QUY ĐỊNH THAM CHIẾU LIÊN QUAN TỪ ĐỒ THỊ (1-HOP)" in GENERATE_SYSTEM_PROMPT
    )
    assert "trừ điểm" in GENERATE_SYSTEM_PROMPT.lower()

    # 2. Distinction between citizen sanctions and police powers
    assert "PHÂN BIỆT RẠCH RÒI CHẾ TÀI NGƯỜI DÂN" in GENERATE_SYSTEM_PROMPT
    assert "BIỆN PHÁP NGHIỆP VỤ" in GENERATE_SYSTEM_PROMPT
    assert "truy đuổi" in GENERATE_SYSTEM_PROMPT.lower()
