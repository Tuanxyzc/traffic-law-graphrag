"""Unit tests for EvidenceBuilder."""

from __future__ import annotations

from src.pipeline.evidence_builder import (
    WARNING_AMENDED,
    WARNING_EXPIRED,
    WARNING_REPEALED,
    WARNING_SUPERSEDED,
    EvidenceBuilder,
)
from src.pipeline.models import (
    AmendmentRecord,
    LegalValidityStatus,
    ReferencedProvision,
    ValidatedProvision,
)
from src.rag.models import ChunkMetadata, RetrievedChunk


def _make_chunk(chunk_id: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        text=text,
        raw_text=text,
        metadata=ChunkMetadata(
            document_id="168_2024_ND-CP",
            dieu="5",
            tieu_de_dieu="Điều 5. Xử phạt xe ô tô",
            level=4,
        ),
        score=0.03,
        dense_score=0.85,
        sparse_score=12.5,
        dense_rank=1,
        sparse_rank=2,
    )


def test_evidence_builder_active_provisions() -> None:
    """Test building evidence package when all provisions are active."""
    chunk = _make_chunk(
        "168_2024_ND-CP_D5_K1_Da", "Phạt tiền từ 200.000 đến 400.000 đồng..."
    )
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk.raw_text or "",
        parent_article_title="Điều 5. Xử phạt người điều khiển xe ô tô",
    )

    builder = EvidenceBuilder()
    package = builder.build(
        user_query="phạt ô tô",
        rewritten_query="xử phạt xe ô tô",
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    assert package.total_chunks_retrieved == 1
    assert package.total_valid_provisions == 1
    assert package.has_superseded_provisions is False
    assert len(package.items) == 1
    assert package.items[0].warning_flag is None


def test_evidence_builder_superseded_provision() -> None:
    """Test building evidence with superseded provision attaching warning flag."""
    chunk = _make_chunk("100_2019_ND-CP_D5_K1_Da", "Quy định cũ theo Nghị định 100...")
    am = AmendmentRecord(
        operation="THAY_THE",
        instruction="Thay thế bởi Điểm a Khoản 1 Điều 5 Nghị định 168/2024/NĐ-CP",
        by_document="168/2024/ND-CP",
    )
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DA_BI_THAY_THE,
        is_current=False,
        content_text=chunk.raw_text or "",
        amendments=[am],
    )

    builder = EvidenceBuilder()
    package = builder.build(
        user_query="phạt cũ",
        rewritten_query="quy định cũ",
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    assert package.has_superseded_provisions is True
    assert package.items[0].warning_flag == WARNING_SUPERSEDED
    assert package.items[0].superseding_text is not None
    assert "168/2024/ND-CP" in package.items[0].superseding_text


def test_evidence_builder_expired_and_repealed() -> None:
    """Test warning flags for expired and repealed provisions."""
    chunk_exp = _make_chunk("exp_id", "Hết hiệu lực")
    prov_exp = ValidatedProvision(
        provision_id="exp_id",
        level="POINT",
        status=LegalValidityStatus.HET_HIEU_LUC,
        is_current=False,
        content_text="Quy định hết hiệu lực",
    )

    chunk_rep = _make_chunk("rep_id", "Bị bãi bỏ")
    prov_rep = ValidatedProvision(
        provision_id="rep_id",
        level="POINT",
        status=LegalValidityStatus.DA_BI_BAI_BO,
        is_current=False,
        content_text="Quy định bị bãi bỏ",
    )

    builder = EvidenceBuilder()
    package = builder.build(
        user_query="q",
        rewritten_query="q",
        retrieved_chunks=[chunk_exp, chunk_rep],
        validated_provisions=[prov_exp, prov_rep],
    )

    assert package.has_superseded_provisions is True
    assert package.items[0].warning_flag == WARNING_EXPIRED
    assert package.items[1].warning_flag == WARNING_REPEALED


def test_evidence_builder_fallback_provision() -> None:
    """Test fallback provision creation when graph has no matching node."""
    chunk = _make_chunk("unmatched_chunk", "Nội dung chỉ có trong vector index")
    builder = EvidenceBuilder()
    package = builder.build(
        user_query="q",
        rewritten_query="q",
        retrieved_chunks=[chunk],
        validated_provisions=[],
    )

    assert package.total_chunks_retrieved == 1
    assert package.total_valid_provisions == 0
    assert len(package.items) == 1
    assert package.items[0].validated_provision.provision_id == "unmatched_chunk"
    assert (
        package.items[0].validated_provision.status
        == LegalValidityStatus.KHONG_XAC_DINH
    )


def test_format_for_llm() -> None:
    """Test text formatting for LLM consumption."""
    chunk = _make_chunk(
        "168_2024_ND-CP_D5_K1_Da", "Phạt tiền từ 200.000 đến 400.000 đồng..."
    )
    ref = ReferencedProvision(
        target_id="168_2024_ND-CP_D6_K1",
        relation_type="THAM_CHIEU",
        title="Khoản 1 Điều 6",
        content="Nội dung điều 6",
    )
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text="Nội dung quy chuẩn",
        document_title="Nghị định 168/2024/NĐ-CP",
        parent_article_title="Điều 5. Xử phạt xe ô tô",
        parent_clause_number="1",
        cross_references=[ref],
    )

    builder = EvidenceBuilder()
    package = builder.build(
        user_query="Vượt đèn đỏ",
        rewritten_query="Không chấp hành tín hiệu",
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    text = builder.format_for_llm(package)
    assert "CÂU HỎI CỦA NGƯỜI DÂN: Vượt đèn đỏ" in text
    assert "Nghị định 168/2024/NĐ-CP" in text
    assert "Điều 5. Xử phạt xe ô tô" in text
    assert "DẪN CHIẾU THAM CHIẾU LIÊN QUAN" in text
    assert "Khoản 1 Điều 6" in text


def test_format_for_llm_sanction_references() -> None:
    """Test that incoming sanction / deduction references are highlighted."""
    chunk = _make_chunk(
        "168_2024_ND-CP_D6_K11_Dđ", "11. Phạt tiền từ 30.000.000 đến 40.000.000 đồng..."
    )
    sanction_ref = ReferencedProvision(
        target_id="168_2024_ND-CP_D6_K16_Dd",
        relation_type="TRU_DIEM_GPLX",
        title="Điểm d Khoản 16 Điều 6",
        content="bị trừ điểm giấy phép lái xe 10 điểm",
    )
    prov = ValidatedProvision(
        provision_id=chunk.id,
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        content_text=chunk.raw_text or "",
        cross_references=[sanction_ref],
    )
    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="đi ngược chiều",
        rewritten_query="đi ngược chiều cao tốc",
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )
    text = builder.format_for_llm(pkg)
    assert "HÌNH THỨC XỬ PHẠT BỔ SUNG & TRỪ ĐIỂM GIẤY PHÉP LÁI XE" in text
    assert "TRU_DIEM_GPLX" in text
    assert "10 điểm" in text


def test_evidence_builder_subgraph_generation() -> None:
    """Test SubGraph generation in EvidenceBuilder including hierarchy, version, amendments, and references."""
    chunk = _make_chunk(
        "168_2024_ND-CP_D6_K11_Dđ", "11. Phạt tiền từ 30.000.000 đến 40.000.000 đồng..."
    )

    am = AmendmentRecord(
        operation="SUA_DOI",
        instruction="Sửa đổi mức phạt",
        by_document="168/2024/ND-CP",
        effective_from="2025-01-01",
    )
    ref_out = ReferencedProvision(
        target_id="168_2024_ND-CP_D6_K1",
        relation_type="THAM_CHIEU",
        title="Khoản 1",
        direction="OUTGOING",
    )
    ref_in = ReferencedProvision(
        target_id="168_2024_ND-CP_D6_K16_Dd",
        relation_type="TRU_DIEM_GPLX",
        title="Điểm d Khoản 16",
        content="trừ 10 điểm",
        direction="INCOMING",
    )
    prov = ValidatedProvision(
        provision_id="168_2024_ND-CP_D6_K11_Dđ",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        version_id="v_168_d6_k11_dd",
        valid_from="2025-01-01",
        content_text=chunk.raw_text or "",
        parent_article_id="168_2024_ND-CP_D6",
        parent_article_title="Điều 6. Xử phạt người lái xe mô tô",
        parent_clause_id="168_2024_ND-CP_D6_K11",
        parent_clause_number="11",
        document_id="168_2024_ND-CP",
        document_title="Nghị định 168/2024/NĐ-CP",
        amendments=[am],
        cross_references=[ref_out, ref_in],
    )

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="ngược chiều cao tốc",
        rewritten_query="đi ngược chiều trên đường cao tốc",
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    sg = pkg.subgraph
    node_ids = {n.id for n in sg.nodes}
    rel_tuples = {(r.source, r.target, r.type) for r in sg.relationships}

    # Verify nodes present
    assert "168_2024_ND-CP_D6_K11_Dđ" in node_ids
    assert "168_2024_ND-CP_D6_K11" in node_ids
    assert "168_2024_ND-CP_D6" in node_ids
    assert "168_2024_ND-CP" in node_ids
    assert "v_168_d6_k11_dd" in node_ids
    assert "168_2024_ND-CP_D6_K1" in node_ids
    assert "168_2024_ND-CP_D6_K16_Dd" in node_ids

    # Verify relationships present
    # Hierarchy
    assert ("168_2024_ND-CP", "168_2024_ND-CP_D6", "CONTAINS_ARTICLE") in rel_tuples
    assert (
        "168_2024_ND-CP_D6",
        "168_2024_ND-CP_D6_K11",
        "CONTAINS_CLAUSE",
    ) in rel_tuples
    assert (
        "168_2024_ND-CP_D6_K11",
        "168_2024_ND-CP_D6_K11_Dđ",
        "CONTAINS_POINT",
    ) in rel_tuples

    # Version
    assert ("168_2024_ND-CP_D6_K11_Dđ", "v_168_d6_k11_dd", "HAS_VERSION") in rel_tuples

    # Outgoing reference
    assert (
        "168_2024_ND-CP_D6_K11_Dđ",
        "168_2024_ND-CP_D6_K1",
        "THAM_CHIEU",
    ) in rel_tuples

    # Incoming deduction reference (ref_in -> prov)
    assert (
        "168_2024_ND-CP_D6_K16_Dd",
        "168_2024_ND-CP_D6_K11_Dđ",
        "TRU_DIEM_GPLX",
    ) in rel_tuples


def test_evidence_builder_amended_provision_warning_and_formatting() -> None:
    """Test EvidenceBuilder handling amended provision with replacement text and SubGraph replacement node."""
    chunk = _make_chunk(
        "168_2024_ND-CP_D21_K2_Db",
        "b) Chở hàng trên nóc thùng xe... trên 1,1 lần chiều dài toàn bộ của xe...",
    )
    am_in = AmendmentRecord(
        operation="SUA_DOI",
        instruction="1. Sửa đổi, bổ sung điểm b khoản 2 như sau:",
        by_document="238/2026/ND-CP",
        effective_from="2026-08-15",
        replacement_text="b) Chở hàng trên nóc thùng xe... trên 10% chiều dài toàn bộ của xe...",
        source_provision_id="238_2026_ND-CP_D8_K1",
        target_provision_id="168_2024_ND-CP_D21_K2_Db",
        direction="INCOMING",
    )
    prov = ValidatedProvision(
        provision_id="168_2024_ND-CP_D21_K2_Db",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        version_id="168_2024_ND-CP_D21_K2_Db_V2",
        valid_from="2026-08-15",
        content_text="b) Chở hàng trên nóc thùng xe... trên 10% chiều dài toàn bộ của xe...",
        parent_article_id="168_2024_ND-CP_D21",
        parent_article_title="Điều 21. Xử phạt các hành vi vi phạm quy định về điều kiện của phương tiện",
        parent_clause_id="168_2024_ND-CP_D21_K2",
        parent_clause_number="2",
        document_id="168_2024_ND-CP",
        document_title="Nghị định 168/2024/NĐ-CP",
        amendments=[am_in],
    )

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="chở hàng vượt chiều dài xe",
        rewritten_query="hành vi chở hàng vượt quá kích thước chiều dài xe",
        retrieved_chunks=[chunk],
        validated_provisions=[prov],
    )

    assert pkg.has_superseded_provisions is True
    assert len(pkg.items) == 1
    item = pkg.items[0]
    assert item.warning_flag == WARNING_AMENDED
    assert item.superseding_text is not None
    assert "238/2026/ND-CP" in item.superseding_text
    assert "trên 10% chiều dài toàn bộ của xe" in item.superseding_text

    # Verify LLM formatted prompt includes both new replacement text and original
    llm_prompt = builder.format_for_llm(pkg)
    assert "QUY ĐỊNH MỚI SAU SỬA ĐỔI, BỔ SUNG" in llm_prompt
    assert "trên 10% chiều dài toàn bộ của xe" in llm_prompt
    assert "QUY ĐỊNH GỐC / TRƯỚC SỬA ĐỔI" in llm_prompt

    # Verify SubGraph includes AmendmentReplacement node and HAS_REPLACEMENT relationship
    node_labels = {n.label for n in pkg.subgraph.nodes}
    assert "AmendmentReplacement" in node_labels
    rel_types = {r.type for r in pkg.subgraph.relationships}
    assert "HAS_REPLACEMENT" in rel_types


def test_evidence_builder_document_amendments() -> None:
    """Test EvidenceBuilder formatting of macro document amendment packages."""
    from src.pipeline.models import DocumentAmendmentItem

    am1 = DocumentAmendmentItem(
        target_id="168_2024_ND-CP_D21_K8_Dd",
        target_title="Điểm d Khoản 8 Điều 21",
        article_id="168_2024_ND-CP_D21",
        article_title="Điều 21. Xử phạt các hành vi vi phạm khác",
        operation="SUA_DOI",
        instruction="Sửa đổi điểm d khoản 8 Điều 21",
        replacement_content="Tịch thu phương tiện vi phạm",
    )
    am2 = DocumentAmendmentItem(
        target_id="168_2024_ND-CP_D13_K8_Db",
        target_title="Điểm b Khoản 8 Điều 13",
        article_id="168_2024_ND-CP_D13",
        article_title="Điều 13. Xử phạt vi phạm quy định về đường sắt",
        operation="BO_SUNG",
        instruction="Bổ sung điểm b khoản 8 Điều 13",
        replacement_content="Phạt tiền từ 10.000.000 đến 15.000.000 đồng",
    )

    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="những điều khoản nào trong NĐ 168 được sửa đổi bởi NĐ 238",
        rewritten_query="Các điều khoản Nghị định 168 được sửa đổi bởi Nghị định 238",
        retrieved_chunks=[],
        validated_provisions=[],
        document_amendments=[am1, am2],
    )

    assert len(pkg.document_amendments) == 2
    llm_context = builder.format_for_llm(pkg)
    assert "TỔNG HỢP TOÀN BỘ CÁC ĐIỀU KHOẢN ĐƯỢC SỬA ĐỔI, BỔ SUNG" in llm_context
    assert "Điều 21. Xử phạt các hành vi vi phạm khác" in llm_context
    assert "Điểm d Khoản 8 Điều 21" in llm_context
    assert "Tịch thu phương tiện vi phạm" in llm_context
    assert "Điều 13. Xử phạt vi phạm quy định về đường sắt" in llm_context

    # SubGraph check
    node_ids = {n.id for n in pkg.subgraph.nodes}
    assert "168_2024_ND-CP_D21" in node_ids
    assert "168_2024_ND-CP_D21_K8_Dd" in node_ids
    rel_types = {r.type for r in pkg.subgraph.relationships}
    assert "CONTAINS" in rel_types
    assert "SUA_DOI" in rel_types


def test_evidence_builder_system_documents_format() -> None:
    """Test format_for_llm correctly groups laws and decrees."""
    docs = [
        {
            "id": "35_2024_QH15",
            "so_hieu": "35/2024/QH15",
            "ten": "Luật Đường bộ",
            "loai": "LUAT",
        },
        {
            "id": "36_2024_QH15",
            "so_hieu": "36/2024/QH15",
            "ten": "Luật Trật tự ATGT",
            "loai": "LUAT",
        },
        {
            "id": "151_2024_ND_CP",
            "so_hieu": "151/2024/NĐ-CP",
            "ten": "Nghị định quy định chi tiết Luật Trật tự, an toàn giao thông đường bộ",
            "loai": "NGHI_DINH",
        },
        {
            "id": "165_2024_ND_CP",
            "so_hieu": "165/2024/NĐ-CP",
            "ten": "Nghị định quy định chi tiết, hướng dẫn thi hành một số điều của Luật Đường bộ và Điều 77 Luật Trật tự",
            "loai": "NGHI_DINH",
        },
    ]
    builder = EvidenceBuilder()
    pkg = builder.build(
        user_query="danh mục",
        rewritten_query="danh mục",
        retrieved_chunks=[],
        validated_provisions=[],
        system_documents=docs,
    )
    formatted = builder.format_for_llm(pkg)
    # Ensure 151 and 165 are under II. CÁC NGHỊ ĐỊNH
    parts = formatted.split("II. CÁC NGHỊ ĐỊNH (CHÍNH PHỦ BAN HÀNH):")
    assert len(parts) == 2
    laws_section = parts[0]
    decrees_section = parts[1]

    assert "35/2024/QH15" in laws_section
    assert "36/2024/QH15" in laws_section
    assert "151/2024/NĐ-CP" not in laws_section
    assert "151/2024/NĐ-CP" in decrees_section
    assert "165/2024/NĐ-CP" in decrees_section
