"""Evidence Builder formatting graph-validated provisions and attaching warning flags."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from src.pipeline.config import PipelineConfig
from src.pipeline.models import (
    DocumentAmendmentItem,
    EvidenceItem,
    EvidencePackage,
    LegalValidityStatus,
    SubGraph,
    SubGraphNode,
    SubGraphRelationship,
    ValidatedProvision,
)
from src.rag.models import RetrievedChunk

logger = logging.getLogger(__name__)

WARNING_SUPERSEDED = "[CẢNH BÁO: ĐIỀU KHOẢN ĐÃ BỊ THAY THẾ BỞI QUY ĐỊNH MỚI]"
WARNING_EXPIRED = "[CẢNH BÁO: ĐIỀU KHOẢN ĐÃ HẾT HIỆU LỰC THI HÀNH]"
WARNING_REPEALED = "[CẢNH BÁO: ĐIỀU KHOẢN ĐÃ BỊ BÃI BỎ]"
WARNING_NOT_YET_EFFECTIVE = "[CẢNH BÁO: ĐIỀU KHOẢN CHƯA CÓ HIỆU LỰC THI HÀNH]"
WARNING_AMENDED = (
    "[LƯU Ý: ĐIỀU KHOẢN ĐÃ ĐƯỢC SỬA ĐỔI, BỔ SUNG - ÁP DỤNG QUY ĐỊNH MỚI NHẤT]"
)


def infer_provision_label(node_id: str, level: str | None = None) -> str:
    """Infers an intuitive graph node label from level or ID pattern."""
    if level and level.upper() in ("POINT", "CLAUSE", "ARTICLE", "DOCUMENT"):
        return level.capitalize()
    nid = node_id.upper()
    if (
        "_D" in nid
        and "_K" in nid
        and ("_D" in nid[nid.rfind("_K") :] or "_DIEM" in nid)
    ):
        return "Point"
    if "_D" in nid and "_K" in nid:
        return "Clause"
    if "_D" in nid:
        return "Article"
    if "_ND-CP" in nid or "_QH" in nid or "_TT-" in nid:
        return "Document"
    return "Provision"


def _detect_vehicle_category(
    article_title: str | None, content: str = ""
) -> str | None:
    """Detects and standardizes vehicle category from article title or content."""
    art = (article_title or "").lower()
    if "máy kéo" in art or "xe máy chuyên dùng" in art:
        return "Xe máy chuyên dùng, xe máy kéo"
    if "xe mô tô" in art or "xe gắn máy" in art:
        return "Xe mô tô, xe gắn máy (xe máy)"
    if "xe ô tô" in art or "ô tô" in art:
        return "Xe ô tô (và các loại xe tương tự xe ô tô)"
    if "xe đạp" in art or "xe thô sơ" in art:
        return "Xe đạp, xe thô sơ"
    if "người đi bộ" in art:
        return "Người đi bộ"

    source = f"{art} {content}".lower()
    if "máy kéo" in source or "xe máy chuyên dùng" in source:
        if "xe mô tô" not in source and "xe gắn máy" not in source:
            return "Xe máy chuyên dùng, xe máy kéo"
    if "xe mô tô" in source or "xe gắn máy" in source:
        return "Xe mô tô, xe gắn máy (xe máy)"
    if "xe ô tô" in source or "ô tô" in source:
        return "Xe ô tô (và các loại xe tương tự xe ô tô)"
    if "xe đạp" in source or "xe thô sơ" in source:
        return "Xe đạp, xe thô sơ"
    if "người đi bộ" in source:
        return "Người đi bộ"
    return None


class EvidenceBuilder:
    """Combines retrieved semantic chunks and validated graph nodes into a structured EvidencePackage."""

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig.from_env()

    def build(
        self,
        user_query: str,
        rewritten_query: Any,
        retrieved_chunks: Sequence[RetrievedChunk],
        validated_provisions: Sequence[ValidatedProvision],
        document_amendments: Sequence[DocumentAmendmentItem] | None = None,
        system_documents: Sequence[dict[str, Any]] | None = None,
    ) -> EvidencePackage:
        """Constructs an EvidencePackage with temporal warning flags and replacement context.

        Args:
            user_query: Original question asked by citizen.
            rewritten_query: Standardized statutory query.
            retrieved_chunks: Candidate semantic unit chunks from hybrid retrieval.
            validated_provisions: Provisions validated via Neo4j.
            document_amendments: Optional direct document amendments traversed from Neo4j.
            system_documents: Optional list of all legal documents in system for meta queries.

        Returns:
            Structured EvidencePackage.
        """
        # Map validated provisions by provision_id
        prov_map: dict[str, ValidatedProvision] = {
            p.provision_id: p for p in validated_provisions
        }

        items: list[EvidenceItem] = []
        has_superseded = False
        valid_provisions_count = 0

        for chunk in retrieved_chunks:
            # 1. Match validated provision
            prov = prov_map.get(chunk.id)
            if not prov:
                for pid, p in prov_map.items():
                    if (
                        chunk.id == pid
                        or chunk.id.startswith(f"{pid}_")
                        or pid.startswith(f"{chunk.id}_")
                    ):
                        prov = p
                        break
            if not prov:
                # Build fallback provision from chunk metadata
                prov = ValidatedProvision(
                    provision_id=chunk.id,
                    level="UNKNOWN",
                    status=LegalValidityStatus.KHONG_XAC_DINH,
                    is_current=True,
                    content_text=chunk.raw_text or chunk.text,
                    document_id=chunk.metadata.document_id,
                    parent_article_title=chunk.metadata.tieu_de_dieu,
                )
            else:
                valid_provisions_count += 1

            # 2. Determine warning flag
            warning_flag: str | None = None
            superseding_text: str | None = None

            if self.config.include_superseded_warning:
                if prov.status == LegalValidityStatus.DA_BI_THAY_THE:
                    warning_flag = WARNING_SUPERSEDED
                    has_superseded = True
                elif prov.status == LegalValidityStatus.HET_HIEU_LUC:
                    warning_flag = WARNING_EXPIRED
                    has_superseded = True
                elif prov.status == LegalValidityStatus.DA_BI_BAI_BO:
                    warning_flag = WARNING_REPEALED
                    has_superseded = True
                elif prov.status == LegalValidityStatus.CHUA_CO_HIEU_LUC:
                    warning_flag = WARNING_NOT_YET_EFFECTIVE
                    has_superseded = True
                elif any(
                    am.direction == "INCOMING"
                    and am.operation
                    in ("SUA_DOI", "AMENDS", "THAY_THE", "BO_SUNG", "ADDS")
                    for am in prov.amendments
                ):
                    warning_flag = WARNING_AMENDED
                    has_superseded = True

            # 3. Detect superseding/amendment provision text
            incoming_amendments = [
                am
                for am in prov.amendments
                if am.direction == "INCOMING"
                and am.operation in ("THAY_THE", "SUA_DOI", "AMENDS", "BO_SUNG", "ADDS")
            ]
            outgoing_amendments = [
                am for am in prov.amendments if am.direction == "OUTGOING"
            ]

            superseding_parts: list[str] = []
            for am in incoming_amendments:
                source_info = (
                    f" ({am.source_provision_id})" if am.source_provision_id else ""
                )
                eff_info = (
                    f" [Hiệu lực từ: {am.effective_from}]" if am.effective_from else ""
                )
                part = f"Theo {am.by_document or 'văn bản sửa đổi'}{source_info}{eff_info}: {am.instruction}"
                if am.replacement_text:
                    part += (
                        f"\n-> NỘI DUNG MỚI ÁP DỤNG HIỆN HÀNH: {am.replacement_text}"
                    )
                superseding_parts.append(part)

            for am in outgoing_amendments:
                eff_info = (
                    f" [Hiệu lực từ: {am.effective_from}]" if am.effective_from else ""
                )
                part = (
                    f"Quy định này sửa đổi, bổ sung cho điều khoản [{am.target_provision_id or ''}] "
                    f"của {am.by_document or 'văn bản được sửa đổi'}{eff_info}: {am.instruction}"
                )
                if am.replacement_text:
                    part += f"\n-> NỘI DUNG SỬA ĐỔI ĐƯỢC ÁP DỤNG: {am.replacement_text}"
                superseding_parts.append(part)

            if superseding_parts:
                superseding_text = "\n\n".join(superseding_parts)

            clean_prov = prov.model_copy(
                update={
                    "parent_clause_content": None,
                    "parent_article_title": None,
                }
            )
            item = EvidenceItem(
                chunk_id=chunk.id,
                original_chunk_text=chunk.raw_text or chunk.text,
                validated_provision=clean_prov,
                warning_flag=warning_flag,
                superseding_text=superseding_text,
                score=getattr(chunk, "score", None),
                dense_score=getattr(chunk, "dense_score", None),
                sparse_score=getattr(chunk, "sparse_score", None),
                dense_rank=getattr(chunk, "dense_rank", None),
                sparse_rank=getattr(chunk, "sparse_rank", None),
            )
            items.append(item)

        doc_amendments_list = list(document_amendments) if document_amendments else []
        sys_docs_list = list(system_documents) if system_documents else []
        subgraph = self.build_subgraph(items, doc_amendments_list, sys_docs_list)

        package = EvidencePackage(
            user_query=user_query,
            rewritten_query=rewritten_query,
            items=items,
            total_chunks_retrieved=len(retrieved_chunks),
            total_valid_provisions=valid_provisions_count,
            has_superseded_provisions=has_superseded,
            subgraph=subgraph,
            document_amendments=doc_amendments_list,
            system_documents=sys_docs_list,
        )
        return package

    def build_subgraph(
        self,
        items: Sequence[EvidenceItem],
        document_amendments: Sequence[DocumentAmendmentItem] | None = None,
        system_documents: Sequence[dict[str, Any]] | None = None,
    ) -> SubGraph:
        """Builds a de-duplicated SubGraph containing all validated and expanded nodes & relationships.

        Includes:
        - SemanticUnit nodes from retrieved chunks
        - Validated statutory nodes (Point, Clause, Article)
        - Document and structural hierarchy relationships (CONTAINS_ARTICLE, CONTAINS_CLAUSE, CONTAINS_POINT)
        - Versioning nodes & HAS_VERSION relationships
        - AmendmentAction nodes & amendment relationships (AMENDS, REPEALS, ADDS, etc.)
        - 1-hop expanded referenced nodes & cross-reference relationships (REFERENCES, TRU_DIEM_GPLX, etc.)
        """
        nodes: dict[str, SubGraphNode] = {}
        relationships: dict[tuple[str, str, str], SubGraphRelationship] = {}

        def add_node(
            node_id: str, label: str, properties: dict[str, Any] | None = None
        ) -> None:
            clean_props = {k: v for k, v in (properties or {}).items() if v is not None}
            if node_id in nodes:
                existing = nodes[node_id]
                merged = {**existing.properties, **clean_props}
                nodes[node_id] = SubGraphNode(
                    id=node_id, label=existing.label or label, properties=merged
                )
            else:
                nodes[node_id] = SubGraphNode(
                    id=node_id, label=label, properties=clean_props
                )

        def add_rel(
            source: str,
            target: str,
            rel_type: str,
            properties: dict[str, Any] | None = None,
        ) -> None:
            if not source or not target or source == target:
                return
            key = (source, target, rel_type)
            clean_props = {k: v for k, v in (properties or {}).items() if v is not None}
            if key in relationships:
                existing = relationships[key]
                merged = {**existing.properties, **clean_props}
                relationships[key] = SubGraphRelationship(
                    source=source,
                    target=target,
                    type=rel_type,
                    properties=merged,
                )
            else:
                relationships[key] = SubGraphRelationship(
                    source=source,
                    target=target,
                    type=rel_type,
                    properties=clean_props,
                )

        for item in items:
            prov = item.validated_provision

            # 1. SemanticUnit node
            if item.chunk_id:
                chunk_preview = item.original_chunk_text.strip()
                if len(chunk_preview) > 300:
                    chunk_preview = chunk_preview[:300] + "..."
                add_node(
                    node_id=item.chunk_id,
                    label="SemanticUnit",
                    properties={"chunk_id": item.chunk_id, "text": chunk_preview},
                )
                if item.chunk_id != prov.provision_id:
                    add_rel(
                        source=item.chunk_id,
                        target=prov.provision_id,
                        rel_type="EXTRACTED_FROM",
                    )

            # 2. Target validated provision node
            prov_label = infer_provision_label(prov.provision_id, prov.level)
            prov_preview = prov.content_text.strip()
            if len(prov_preview) > 300:
                prov_preview = prov_preview[:300] + "..."

            prov_props: dict[str, Any] = {
                "level": prov.level,
                "status": prov.status.value,
                "is_current": prov.is_current,
                "content": prov_preview,
            }
            if item.warning_flag:
                prov_props["warning_flag"] = item.warning_flag
            if item.superseding_text:
                prov_props["superseding_text"] = item.superseding_text
            if prov.valid_from:
                prov_props["valid_from"] = prov.valid_from
            if prov.valid_to:
                prov_props["valid_to"] = prov.valid_to
            if prov.parent_clause_number:
                prov_props["clause_number"] = prov.parent_clause_number

            add_node(node_id=prov.provision_id, label=prov_label, properties=prov_props)

            # 3. ProvisionVersion node
            if prov.version_id:
                v_props: dict[str, Any] = {
                    "is_current": prov.is_current,
                    "effective_status": prov.status.value,
                }
                if prov.valid_from:
                    v_props["valid_from"] = prov.valid_from
                if prov.valid_to:
                    v_props["valid_to"] = prov.valid_to
                add_node(
                    node_id=prov.version_id,
                    label="ProvisionVersion",
                    properties=v_props,
                )
                add_rel(
                    source=prov.provision_id,
                    target=prov.version_id,
                    rel_type="HAS_VERSION",
                )

            # 4. Structural Hierarchy: Document -> Article -> Clause -> Point
            # Parent Clause
            if prov.parent_clause_id and prov.parent_clause_id != prov.provision_id:
                c_props: dict[str, Any] = {}
                if prov.parent_clause_number:
                    c_props["number"] = prov.parent_clause_number
                if prov.parent_clause_content:
                    clause_prev = prov.parent_clause_content.strip()
                    c_props["content"] = (
                        (clause_prev[:300] + "...")
                        if len(clause_prev) > 300
                        else clause_prev
                    )
                add_node(
                    node_id=prov.parent_clause_id, label="Clause", properties=c_props
                )
                add_rel(
                    source=prov.parent_clause_id,
                    target=prov.provision_id,
                    rel_type="CONTAINS_POINT",
                )

            # Parent Article
            if prov.parent_article_id:
                a_props = (
                    {"title": prov.parent_article_title}
                    if prov.parent_article_title
                    else {}
                )
                add_node(
                    node_id=prov.parent_article_id, label="Article", properties=a_props
                )
                if prov.parent_clause_id and prov.parent_clause_id != prov.provision_id:
                    add_rel(
                        source=prov.parent_article_id,
                        target=prov.parent_clause_id,
                        rel_type="CONTAINS_CLAUSE",
                    )
                elif prov.parent_article_id != prov.provision_id:
                    add_rel(
                        source=prov.parent_article_id,
                        target=prov.provision_id,
                        rel_type="CONTAINS_CLAUSE",
                    )

            # Document
            if prov.document_id:
                d_props = {"title": prov.document_title} if prov.document_title else {}
                add_node(node_id=prov.document_id, label="Document", properties=d_props)
                target_doc_child = prov.parent_article_id or (
                    prov.parent_clause_id
                    if prov.parent_clause_id != prov.provision_id
                    else prov.provision_id
                )
                if target_doc_child and target_doc_child != prov.document_id:
                    add_rel(
                        source=prov.document_id,
                        target=target_doc_child,
                        rel_type="CONTAINS_ARTICLE",
                    )

            # 5. Amendments (Bidirectional traversal nodes & replacement payload)
            for idx_am, am in enumerate(prov.amendments):
                am_id = f"Amendment_{am.operation}_{am.by_document or 'unknown'}_{prov.provision_id}_{idx_am}"
                am_props: dict[str, Any] = {
                    "operation": am.operation,
                    "instruction": am.instruction,
                    "direction": am.direction,
                }
                if am.by_document:
                    am_props["by_document"] = am.by_document
                if am.effective_from:
                    am_props["effective_from"] = am.effective_from
                add_node(node_id=am_id, label="AmendmentAction", properties=am_props)

                # If there is a replacement payload / text:
                if am.replacement_text:
                    rep_id = f"{am_id}_Replacement"
                    rep_preview = am.replacement_text.strip()
                    if len(rep_preview) > 300:
                        rep_preview = rep_preview[:300] + "..."
                    add_node(
                        node_id=rep_id,
                        label="AmendmentReplacement",
                        properties={
                            "payload": rep_preview,
                            "operation": am.operation,
                        },
                    )
                    add_rel(source=am_id, target=rep_id, rel_type="HAS_REPLACEMENT")

                if am.direction == "INCOMING":
                    add_rel(
                        source=am_id,
                        target=prov.provision_id,
                        rel_type=am.operation or "AMENDS",
                        properties={"direction": "INCOMING"},
                    )
                    if (
                        am.source_provision_id
                        and am.source_provision_id != prov.provision_id
                    ):
                        src_label = infer_provision_label(am.source_provision_id)
                        add_node(node_id=am.source_provision_id, label=src_label)
                        add_rel(
                            source=am.source_provision_id,
                            target=am_id,
                            rel_type="HAS_ACTION",
                        )
                else:
                    # OUTGOING: target provision amends orig_target
                    add_rel(
                        source=prov.provision_id, target=am_id, rel_type="HAS_ACTION"
                    )
                    if (
                        am.target_provision_id
                        and am.target_provision_id != prov.provision_id
                    ):
                        orig_label = infer_provision_label(am.target_provision_id)
                        add_node(node_id=am.target_provision_id, label=orig_label)
                        add_rel(
                            source=am_id,
                            target=am.target_provision_id,
                            rel_type=am.operation or "AMENDS",
                            properties={"direction": "OUTGOING"},
                        )
                        add_rel(
                            source=prov.provision_id,
                            target=am.target_provision_id,
                            rel_type=am.operation or "AMENDS",
                            properties={"direction": "OUTGOING"},
                        )

            # 6. 1-hop Cross-references (expanded nodes & edges)
            for ref in prov.cross_references:
                ref_label = infer_provision_label(ref.target_id)
                ref_props: dict[str, Any] = {}
                if ref.title:
                    ref_props["title"] = ref.title
                if ref.document_id:
                    ref_props["document_id"] = ref.document_id
                if ref.content:
                    c_prev = ref.content.strip()
                    ref_props["content"] = (
                        (c_prev[:300] + "...") if len(c_prev) > 300 else c_prev
                    )

                add_node(node_id=ref.target_id, label=ref_label, properties=ref_props)

                rel_type = ref.relation_type or "REFERENCES"
                if ref.direction == "INCOMING":
                    add_rel(
                        source=ref.target_id,
                        target=prov.provision_id,
                        rel_type=rel_type,
                        properties={"direction": "INCOMING"},
                    )
                else:
                    add_rel(
                        source=prov.provision_id,
                        target=ref.target_id,
                        rel_type=rel_type,
                        properties={"direction": "OUTGOING"},
                    )

        if document_amendments:
            for idx_da, da in enumerate(document_amendments):
                # 1. Target provision node
                add_node(
                    node_id=da.target_id,
                    label=infer_provision_label(da.target_id),
                    properties={"title": da.target_title} if da.target_title else {},
                )
                # 2. Parent article node
                if da.article_id:
                    add_node(
                        node_id=da.article_id,
                        label="Article",
                        properties={"title": da.article_title}
                        if da.article_title
                        else {},
                    )
                    add_rel(
                        source=da.article_id, target=da.target_id, rel_type="CONTAINS"
                    )
                # 3. AmendmentAction node
                da_id = f"DocAmendment_{da.operation}_{da.target_id}_{idx_da}"
                da_props: dict[str, Any] = {
                    "operation": da.operation,
                    "instruction": da.instruction,
                }
                if da.replacement_content:
                    da_props["replacement_content"] = da.replacement_content[:200]
                add_node(node_id=da_id, label="AmendmentAction", properties=da_props)
                add_rel(source=da_id, target=da.target_id, rel_type=da.operation)

        if system_documents:
            for doc in system_documents:
                d_id = doc.get("id") or doc.get("so_hieu") or "doc"
                add_node(
                    node_id=d_id,
                    label="Document",
                    properties={
                        "so_hieu": doc.get("so_hieu", d_id),
                        "ten": doc.get("ten", ""),
                        "loai": doc.get("loai", "DOCUMENT"),
                        "role": doc.get("role", "NORMAL"),
                    },
                )

        return SubGraph(
            nodes=list(nodes.values()),
            relationships=list(relationships.values()),
        )

    def format_for_llm(self, package: EvidencePackage) -> str:
        """Formats the EvidencePackage into structured text for LLM answer generation."""
        if package.system_documents:

            def _is_law(doc: dict[str, Any]) -> bool:
                loai = str(doc.get("loai", "")).upper()
                so_hieu = str(doc.get("so_hieu", "")).upper()
                ten = str(doc.get("ten", "")).strip()
                if (
                    "ND-CP" in so_hieu
                    or "NĐ-CP" in so_hieu
                    or "NGHIDINH" in loai
                    or "NGHI_DINH" in loai
                ):
                    return False
                if (
                    loai in ("LUAT", "BO_LUAT")
                    or "QH" in so_hieu
                    or ten.startswith("Luật")
                ):
                    return True
                return False

            laws = [d for d in package.system_documents if _is_law(d)]
            decrees = [d for d in package.system_documents if not _is_law(d)]

            meta_parts: list[str] = [
                f"CÂU HỎI CỦA NGƯỜI DÂN: {package.user_query}",
                "Ý ĐỊNH TRUY VẤN: Tra cứu danh mục các văn bản quy phạm pháp luật trong cơ sở tri thức của hệ thống",
                "",
                "=== DANH MỤC CÁC VĂN BẢN PHÁP LUẬT ĐƯỢC TÍCH HỢP TRONG CƠ SỞ DỮ LIỆU HỆ THỐNG ===",
                f"TỔNG SỐ VĂN BẢN: {len(package.system_documents)} (gồm {len(laws)} Luật và {len(decrees)} Nghị định)",
                "",
                "I. CÁC ĐẠO LUẬT (QUỐC HỘI BAN HÀNH):",
            ]
            for idx, law in enumerate(laws, start=1):
                so_hieu = law.get("so_hieu") or law.get("id")
                ten = law.get("ten") or "Luật"
                role_desc = f" - Vai trò: {law.get('role')}" if law.get("role") else ""
                meta_parts.append(f"  {idx}. {so_hieu}: {ten}{role_desc}")

            meta_parts.extend(
                [
                    "",
                    "II. CÁC NGHỊ ĐỊNH (CHÍNH PHỦ BAN HÀNH):",
                ]
            )
            for idx, dec in enumerate(decrees, start=1):
                so_hieu = dec.get("so_hieu") or dec.get("id")
                ten = dec.get("ten") or "Nghị định"
                role_desc = f" - Vai trò: {dec.get('role')}" if dec.get("role") else ""
                meta_parts.append(f"  {idx}. {so_hieu}: {ten}{role_desc}")

            meta_parts.append("\n=== HẾT BẰNG CHỨNG ===")
            return "\n".join(meta_parts)

        if not package.items and not package.document_amendments:
            return "Không tìm thấy điều khoản pháp luật phù hợp trong cơ sở dữ liệu."

        rw = package.rewritten_query
        rw_query_str = (
            rw.search_query
            if hasattr(rw, "search_query")
            else str(rw)
        )
        parts: list[str] = [
            f"CÂU HỎI CỦA NGƯỜI DÂN: {package.user_query}",
            f"TRUY VẤN PHÁP LÝ CHUẨN HÓA: {rw_query_str}",
        ]
        if hasattr(rw, "intent") and rw.intent:
            parts.append(f"MỤC ĐÍCH TRA CỨU: {rw.intent}")
        if hasattr(rw, "target_entities") and rw.target_entities:
            target_str = ", ".join(rw.target_entities)
            parts.append(f"ĐỐI TƯỢNG PHƯƠNG TIỆN MỤC TIÊU: {target_str}")

        if package.document_amendments:
            # Group amendments by parent article
            articles_map: dict[str, list[DocumentAmendmentItem]] = {}
            for am in package.document_amendments:
                art_key = am.article_title or (
                    f"Điều ({am.article_id})"
                    if am.article_id
                    else "Các điều khoản khác"
                )
                if art_key not in articles_map:
                    articles_map[art_key] = []
                articles_map[art_key].append(am)

            parts.extend(
                [
                    f"TỔNG SỐ ĐIỀU KHOẢN ĐƯỢC SỬA ĐỔI, BỔ SUNG, BÃI BỎ: {len(package.document_amendments)} (thuộc {len(articles_map)} Điều luật)",
                    "",
                    "=== TỔNG HỢP TOÀN BỘ CÁC ĐIỀU KHOẢN ĐƯỢC SỬA ĐỔI, BỔ SUNG, BÃI BỎ (THEO GRAPH DỮ LIỆU CHÍNH XÁC) ===",
                ]
            )

            for art_title, am_list in articles_map.items():
                parts.append(f"\n■ {art_title}:")
                for am_item in am_list:
                    target_name = am_item.target_title or am_item.target_id
                    parts.append(
                        f"  * Quy định: {target_name} [Hình thức: {am_item.operation}]"
                    )
                    if am_item.instruction:
                        parts.append(
                            f"    - Lệnh sửa đổi/bổ sung: {am_item.instruction}"
                        )
                    if am_item.replacement_content:
                        parts.append(
                            f'    - Nội dung mới sau sửa đổi, bổ sung:\n      "{am_item.replacement_content}"'
                        )
                    elif am_item.old_phrase and am_item.new_phrase:
                        parts.append(
                            f"    - Thay thế cụm từ: '{am_item.old_phrase}' bằng '{am_item.new_phrase}'"
                        )

        if package.items:
            parts.extend(
                [
                    "",
                    f"TỔNG SỐ ĐIỀU KHOẢN CĂN CỨ: {len(package.items)}",
                    "",
                    "=== DANH SÁCH ĐIỀU KHOẢN CĂN CỨ PHÁP LÝ ===",
                ]
            )

        for idx, item in enumerate(package.items, start=1):
            prov = item.validated_provision
            doc_label = prov.document_title or prov.document_id or "Văn bản quy phạm"
            art_label = prov.parent_article_title or (
                f"Điều ({prov.parent_article_id})" if prov.parent_article_id else ""
            )
            clause_label = (
                f"Khoản {prov.parent_clause_number}"
                if prov.parent_clause_number
                else ""
            )
            header_parts = [
                p for p in [doc_label, art_label, clause_label, prov.provision_id] if p
            ]

            parts.append(f"\n--- CĂN CỨ [{idx}]: {' | '.join(header_parts)} ---")

            if item.warning_flag:
                parts.append(f"TRẠNG THÁI HIỆU LỰC: {item.warning_flag}")
                if item.superseding_text:
                    parts.append(f"THÔNG TIN THAY THẾ/SỬA ĐỔI: {item.superseding_text}")
            else:
                parts.append(
                    f"TRẠNG THÁI HIỆU LỰC: Đang có hiệu lực thi hành ({prov.status.value})"
                )

            # Prioritize self-contained chunk text containing full hierarchy, preamble & point
            chunk_txt = item.original_chunk_text.strip()
            prov_txt = prov.content_text.strip()

            veh_cat = _detect_vehicle_category(
                prov.parent_article_title, f"{chunk_txt} {prov_txt}"
            )
            if veh_cat:
                parts.append(f"LOẠI PHƯƠNG TIỆN ÁP DỤNG: {veh_cat}")

            content = chunk_txt or prov_txt

            active_replacements = [
                am
                for am in prov.amendments
                if am.direction == "INCOMING" and am.replacement_text
            ]
            if active_replacements:
                am_rep = active_replacements[0]
                doc_str = f" theo {am_rep.by_document}" if am_rep.by_document else ""
                parts.append(
                    f"NỘI DUNG QUY ĐỊNH:\n"
                    f"★ [QUY ĐỊNH MỚI SAU SỬA ĐỔI, BỔ SUNG (BẮT BUỘC ÁP DỤNG HIỆN HÀNH{doc_str})]:\n"
                    f"{am_rep.replacement_text}\n\n"
                    f"[QUY ĐỊNH GỐC / TRƯỚC SỬA ĐỔI (THAM KHẢO ĐỐI CHIẾU)]:\n"
                    f"{content}"
                )
            else:
                parts.append(f"NỘI DUNG QUY ĐỊNH:\n{content}")

            if prov.amendments:
                parts.append("LỊCH SỬ SỬA ĐỔI / BỔ SUNG & TRAVERSAL 2 CHIỀU:")
                for prov_am in prov.amendments:
                    dir_tag = f"[{prov_am.direction}]"
                    by_doc = (
                        f" bởi {prov_am.by_document}"
                        if prov_am.direction == "INCOMING" and prov_am.by_document
                        else (
                            f" cho {prov_am.target_provision_id} ({prov_am.by_document})"
                            if prov_am.by_document
                            else ""
                        )
                    )
                    eff = (
                        f" (hiệu lực: {prov_am.effective_from})"
                        if prov_am.effective_from
                        else ""
                    )
                    parts.append(
                        f"  - {dir_tag} [{prov_am.operation}]{by_doc}{eff}: {prov_am.instruction}"
                    )
                    if prov_am.replacement_text:
                        parts.append(
                            f"    + Nội dung sửa đổi: {prov_am.replacement_text}"
                        )

            if prov.cross_references:
                parts.append("CÁC QUY ĐỊNH THAM CHIẾU LIÊN QUAN TỪ ĐỒ THỊ (1-HOP):")
                for ref in prov.cross_references:
                    ref_title = ref.title or ref.target_id
                    ref_text = f": {ref.content}" if ref.content else ""
                    dir_tag = f"[{ref.direction}] " if ref.direction else ""
                    rel_type = ref.relation_type or "THAM_CHIEU"
                    parts.append(
                        f"  • {dir_tag}[{rel_type}] Căn cứ {ref_title}{ref_text}"
                    )

        parts.append("\n=== HẾT BẰNG CHỨNG ===")
        return "\n".join(parts)
