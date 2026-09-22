"""Graph Validator traversing Neo4j for statutory validity, hierarchy, amendments, and bidirectional references."""

from __future__ import annotations

import ast
import json
import logging
from typing import Any

from src.graph.neo4j.connection import Neo4jClient
from src.pipeline.config import PipelineConfig
from src.pipeline.models import (
    AmendmentRecord,
    DocumentAmendmentItem,
    LegalValidityStatus,
    ReferencedProvision,
    ValidatedProvision,
)

logger = logging.getLogger(__name__)

VALIDATION_CYPHER_QUERY = """
UNWIND $unit_ids AS raw_id
OPTIONAL MATCH (direct_node {id: raw_id})
WHERE direct_node:Point OR direct_node:Clause OR direct_node:Article
OPTIONAL MATCH (su:SemanticUnit {id: raw_id})-[:LOCATED_AT|EXTRACTED_FROM]->(su_node:Point|Clause|Article)
WITH coalesce(direct_node, su_node) AS target
WHERE target IS NOT NULL
WITH DISTINCT target

// 1. Versioning & Temporal status
OPTIONAL MATCH (target)-[:HAS_VERSION]->(v:ProvisionVersion)
WITH target, v ORDER BY v.valid_from DESC
WITH target, collect(v) AS versions
WITH target, head(versions) AS current_v, [ver in versions WHERE ver.is_current = false] AS historical_versions

// 2. Structural Parent Hierarchy
OPTIONAL MATCH (target)<-[:CONTAINS_POINT]-(parent_clause:Clause)
WITH target, current_v, historical_versions, coalesce(parent_clause, CASE WHEN target:Clause THEN target ELSE null END) AS clause_node
OPTIONAL MATCH (clause_node)<-[:CONTAINS_CLAUSE]-(parent_article:Article)
WITH target, current_v, historical_versions, clause_node, coalesce(parent_article, CASE WHEN target:Article THEN target ELSE null END) AS article_node
OPTIONAL MATCH (article_node)<-[:CONTAINS_ARTICLE|CONTAINS_CHAPTER*1..2]-(parent_doc:Document)
OPTIONAL MATCH (target)<-[:CONTAINS_ARTICLE|CONTAINS_CHAPTER*1..2]-(direct_doc:Document)
OPTIONAL MATCH (fallback_doc:Document) WHERE target.id STARTS WITH fallback_doc.id
WITH target, current_v, historical_versions, clause_node, article_node, coalesce(parent_doc, direct_doc, fallback_doc) AS doc_node

// 3. Direct Amendment Actions impacting this provision (INCOMING)
OPTIONAL MATCH (action_in:AmendmentAction)-[r_mod_in:AMENDS|REPEALS|ADDS]->(target)
OPTIONAL MATCH (su_in:SemanticUnit)-[:HAS_ACTION]->(action_in)
OPTIONAL MATCH (su_in)-[:LOCATED_AT]->(src_prov_in)
OPTIONAL MATCH (action_in)-[:HAS_REPLACEMENT]->(rep_in:AmendmentReplacement)
OPTIONAL MATCH (action_in)-[:HAS_TEXT_AMENDMENT]->(txt_in:AmendmentText)
OPTIONAL MATCH (doc_mod_in:Document) WHERE su_in.id STARTS WITH doc_mod_in.id

// 4. Direct Amendment Actions originating from this provision (OUTGOING)
OPTIONAL MATCH (su_out:SemanticUnit)-[:LOCATED_AT|EXTRACTED_FROM*0..1]->(target)
OPTIONAL MATCH (su_out)-[:HAS_ACTION]->(action_out:AmendmentAction)
OPTIONAL MATCH (action_out)-[r_mod_out:AMENDS|REPEALS|ADDS]->(orig_target:Point|Clause|Article)
OPTIONAL MATCH (action_out)-[:HAS_REPLACEMENT]->(rep_out:AmendmentReplacement)
OPTIONAL MATCH (action_out)-[:HAS_TEXT_AMENDMENT]->(txt_out:AmendmentText)
OPTIONAL MATCH (doc_mod_out:Document) WHERE orig_target.id STARTS WITH doc_mod_out.id

// 5. 1-hop Cross-references (OUTGOING & INCOMING to capture sanctions and penalty point deductions)
OPTIONAL MATCH (target)-[r_out:REFERENCES|EXCEPTION_TO|THAM_CHIEU]->(ref_out:Point|Clause|Article)
OPTIONAL MATCH (ref_out)-[:HAS_VERSION]->(ref_out_v:ProvisionVersion {is_current: true})

OPTIONAL MATCH (ref_in:Point|Clause|Article)-[r_in:REFERENCES|EXCEPTION_TO|THAM_CHIEU]->(target)
OPTIONAL MATCH (ref_in)-[:HAS_VERSION]->(ref_in_v:ProvisionVersion {is_current: true})

RETURN target.id AS provision_id,
       labels(target)[0] AS level,
       doc_node.id AS document_id,
       coalesce(doc_node.ten, doc_node.so_hieu) AS document_title,
       article_node.id AS parent_article_id,
       coalesce(article_node.title, article_node.tieu_de) AS parent_article_title,
       clause_node.id AS parent_clause_id,
       coalesce(clause_node.number, clause_node.so_khoan) AS parent_clause_number,
       coalesce(clause_node.content, clause_node.noi_dung, clause_node.text, '') AS parent_clause_content,
       {
           version_id: current_v.version_id,
           valid_from: current_v.valid_from,
           valid_to: current_v.valid_to,
           is_current: current_v.is_current,
           content_text: coalesce(current_v.content_text, target.content, target.noi_dung, target.text, ''),
           effective_status: current_v.effective_status
       } AS version_info,
       collect(DISTINCT CASE WHEN action_in IS NOT NULL THEN {
           operation: coalesce(action_in.operation, type(r_mod_in)),
           instruction: coalesce(action_in.raw_instruction, action_in.normalized_instruction, ''),
           by_document: coalesce(doc_mod_in.so_hieu, doc_mod_in.ten),
           effective_from: coalesce(current_v.valid_from, doc_mod_in.hieu_luc_tu),
           replacement_payload: rep_in.payload_json,
           text_new: txt_in.new_text,
           text_old: txt_in.old_text,
           text_general: txt_in.text,
           source_provision_id: src_prov_in.id,
           target_provision_id: target.id,
           direction: 'INCOMING'
       } ELSE null END) +
       collect(DISTINCT CASE WHEN action_out IS NOT NULL THEN {
           operation: coalesce(action_out.operation, type(r_mod_out)),
           instruction: coalesce(action_out.raw_instruction, action_out.normalized_instruction, ''),
           by_document: coalesce(doc_mod_out.so_hieu, doc_mod_out.ten),
           effective_from: coalesce(current_v.valid_from, doc_mod_out.hieu_luc_tu),
           replacement_payload: rep_out.payload_json,
           text_new: txt_out.new_text,
           text_old: txt_out.old_text,
           text_general: txt_out.text,
           source_provision_id: target.id,
           target_provision_id: orig_target.id,
           direction: 'OUTGOING'
       } ELSE null END) AS amendments,
       collect(DISTINCT CASE WHEN ref_out IS NOT NULL THEN {
           target_id: ref_out.id,
           relation_type: type(r_out),
           document_id: ref_out.document_id,
           title: coalesce(ref_out.title, ref_out.tieu_de),
           content: coalesce(ref_out_v.content_text, ref_out.content, ref_out.noi_dung, ref_out.text, ''),
           direction: 'OUTGOING'
       } ELSE null END) +
       collect(DISTINCT CASE WHEN ref_in IS NOT NULL THEN {
           target_id: ref_in.id,
           relation_type: type(r_in),
           document_id: ref_in.document_id,
           title: coalesce(ref_in.title, ref_in.tieu_de),
           content: coalesce(ref_in_v.content_text, ref_in.content, ref_in.noi_dung, ref_in.text, ''),
           direction: 'INCOMING'
       } ELSE null END) AS references
"""

DOCUMENT_AMENDMENTS_CYPHER_QUERY = """
MATCH (action:AmendmentAction)-[r_mod:AMENDS|REPEALS|ADDS]->(target)
WHERE (
    ($doc_b IS NOT NULL AND (
        (action.id CONTAINS $doc_a AND target.id CONTAINS $doc_b) OR
        (action.id CONTAINS $doc_b AND target.id CONTAINS $doc_a)
    ))
    OR
    ($doc_b IS NULL AND (
        action.id CONTAINS $doc_a OR target.id CONTAINS $doc_a
    ))
)
OPTIONAL MATCH (action)-[:HAS_REPLACEMENT]->(rep:AmendmentReplacement)
OPTIONAL MATCH (action)-[:HAS_TEXT_AMENDMENT]->(txt:AmendmentText)
OPTIONAL MATCH (target)<-[:CONTAINS_POINT]-(parent_c:Clause)
WITH target, parent_c, action, r_mod, rep, txt, coalesce(parent_c, CASE WHEN target:Clause THEN target ELSE null END) AS c
OPTIONAL MATCH (c)<-[:CONTAINS_CLAUSE]-(parent_a:Article)
WITH target, action, r_mod, rep, txt, coalesce(parent_a, CASE WHEN target:Article THEN target ELSE null END) AS a
RETURN
    target.id AS target_id,
    target.title AS target_title,
    a.id AS article_id,
    a.title AS article_title,
    coalesce(action.operation, type(r_mod)) AS operation,
    coalesce(action.raw_instruction, action.normalized_instruction, '') AS instruction,
    rep.payload_json AS replacement_payload,
    txt.new_text AS text_new,
    txt.old_text AS text_old,
    txt.text AS text_general
ORDER BY a.id, target.id
"""


def clean_provision_content(raw_content: str | None) -> str:
    """Unpacks stringified dictionary representations (e.g. {'number': 'đ', 'content': ...})."""
    if not raw_content:
        return ""
    s = raw_content.strip()
    if (
        s.startswith("{")
        and s.endswith("}")
        and ("'content':" in s or '"content":' in s)
    ):
        try:
            d = ast.literal_eval(s)
            if isinstance(d, dict) and "content" in d:
                return str(d["content"]).strip()
        except (ValueError, SyntaxError, TypeError):
            logger.debug("Could not parse content string as literal dict: %s", s[:50])
    return s


def extract_replacement_text(
    payload_json: str | None,
    new_text: str | None = None,
    old_text: str | None = None,
    general_text: str | None = None,
) -> str | None:
    """Extracts clean statutory replacement text from JSON payload or phrase text."""
    if payload_json:
        s = payload_json.strip()
        if (s.startswith("{") and s.endswith("}")) or (
            s.startswith("[") and s.endswith("]")
        ):
            try:
                data = json.loads(s)
                if isinstance(data, dict):
                    if data.get("content"):
                        return str(data["content"]).strip()
                    if data.get("text"):
                        return str(data["text"]).strip()
                    if data.get("noi_dung"):
                        return str(data["noi_dung"]).strip()
                    return str(data)
                if isinstance(data, list):
                    return "\n".join(str(x) for x in data if x)
            except (ValueError, json.JSONDecodeError) as exc:
                logger.debug("Failed to parse replacement json payload: %s", exc)
            try:
                d = ast.literal_eval(s)
                if isinstance(d, dict):
                    if d.get("content"):
                        return str(d["content"]).strip()
                    if d.get("text"):
                        return str(d["text"]).strip()
                    return str(d)
            except (ValueError, SyntaxError, TypeError) as exc:
                logger.debug(
                    "Failed to evaluate literal dict in replacement payload: %s", exc
                )
        return s

    if new_text:
        if old_text:
            return f"Thay thế cụm từ '{old_text}' bằng '{new_text}'"
        return new_text.strip()
    if general_text:
        return general_text.strip()
    return None


def determine_legal_status(
    version_info: dict[str, Any] | None,
    amendments: list[AmendmentRecord],
) -> tuple[LegalValidityStatus, bool]:
    """Determines the statutory validity status and is_current flag based on version and amendments."""
    if not version_info or not version_info.get("version_id"):
        for am in amendments:
            op = (am.operation or "").upper()
            if op in ("BAI_BO", "REPEALS"):
                return LegalValidityStatus.DA_BI_BAI_BO, False
            if op in ("THAY_THE", "AMENDS") and am.direction == "INCOMING":
                return LegalValidityStatus.DA_BI_THAY_THE, False
        return LegalValidityStatus.KHONG_XAC_DINH, True

    eff_status = str(version_info.get("effective_status") or "").upper()
    is_curr_val = version_info.get("is_current")
    is_current = bool(is_curr_val) if is_curr_val is not None else True

    # 1. Check repeal
    if eff_status in ("BAI_BO", "REPEALED"):
        return LegalValidityStatus.DA_BI_BAI_BO, False
    for am in amendments:
        if am.direction == "INCOMING" and (am.operation or "").upper() in (
            "BAI_BO",
            "REPEALS",
        ):
            return LegalValidityStatus.DA_BI_BAI_BO, False

    # 2. Check replacement / supersession
    if eff_status in ("THAY_THE", "SUPERSEDED"):
        return LegalValidityStatus.DA_BI_THAY_THE, False
    # If not current and has incoming replacement/amendment
    if not is_current:
        for am in amendments:
            if am.direction == "INCOMING" and (am.operation or "").upper() in (
                "THAY_THE",
                "AMENDS",
            ):
                return LegalValidityStatus.DA_BI_THAY_THE, False

    # 3. Check expiration
    if eff_status in ("HET_HIEU_LUC", "EXPIRED") or not is_current:
        return LegalValidityStatus.HET_HIEU_LUC, False

    # 4. Check future ineffectiveness
    if eff_status in ("CHUA_CO_HIEU_LUC", "PENDING"):
        return LegalValidityStatus.CHUA_CO_HIEU_LUC, False

    return LegalValidityStatus.DANG_CO_HIEU_LUC, True


class GraphValidator:
    """Validates retrieved legal semantic units against the Neo4j statutory graph."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        client: Neo4jClient | None = None,
    ) -> None:
        self.config = config or PipelineConfig.from_env()
        self.client = client or Neo4jClient(
            uri=self.config.neo4j_uri,
            username=self.config.neo4j_user,
            password=self.config.neo4j_password,
        )

    def validate_provisions(self, unit_ids: list[str]) -> list[ValidatedProvision]:
        """Queries Neo4j for temporal validity, parent hierarchy, amendments, and references.

        Args:
            unit_ids: List of SemanticUnit IDs or structural Point/Clause/Article IDs.

        Returns:
            List of ValidatedProvision objects.
        """
        clean_ids = [uid.strip() for uid in unit_ids if uid and uid.strip()]
        if not clean_ids:
            return []

        try:
            with self.client.session() as session:
                records = session.run(VALIDATION_CYPHER_QUERY, unit_ids=clean_ids)
                results: list[ValidatedProvision] = []

                for record in records:
                    prov_id = record["provision_id"]
                    level = (record["level"] or "UNKNOWN").upper()
                    version_info = record.get("version_info") or {}

                    raw_amendments = record.get("amendments") or []
                    amendments: list[AmendmentRecord] = []
                    seen_amendments: set[tuple[str, str, str, str]] = set()
                    for am in raw_amendments:
                        if isinstance(am, dict) and am.get("operation"):
                            op = str(am.get("operation"))
                            direction = str(am.get("direction") or "INCOMING")
                            target_pid = am.get("target_provision_id")
                            source_pid = am.get("source_provision_id")
                            instr = str(am.get("instruction") or "")

                            rep_text = extract_replacement_text(
                                payload_json=am.get("replacement_payload"),
                                new_text=am.get("text_new"),
                                old_text=am.get("text_old"),
                                general_text=am.get("text_general"),
                            )

                            key = (
                                op,
                                direction,
                                instr,
                                str(target_pid or source_pid or ""),
                            )
                            if key not in seen_amendments:
                                seen_amendments.add(key)
                                amendments.append(
                                    AmendmentRecord(
                                        operation=op,
                                        instruction=instr,
                                        by_document=am.get("by_document"),
                                        effective_from=am.get("effective_from"),
                                        replacement_text=rep_text,
                                        source_provision_id=source_pid,
                                        target_provision_id=target_pid,
                                        direction=direction,
                                    )
                                )

                    raw_refs = record.get("references") or []
                    references: list[ReferencedProvision] = []
                    seen_refs: set[str] = set()
                    for ref in raw_refs:
                        if isinstance(ref, dict) and ref.get("target_id"):
                            tid = str(ref.get("target_id"))
                            if tid not in seen_refs and tid != prov_id:
                                seen_refs.add(tid)
                                clean_ref_content = clean_provision_content(
                                    ref.get("content")
                                )
                                references.append(
                                    ReferencedProvision(
                                        target_id=tid,
                                        relation_type=str(
                                            ref.get("relation_type") or "THAM_CHIEU"
                                        ),
                                        document_id=ref.get("document_id"),
                                        title=ref.get("title"),
                                        content=clean_ref_content,
                                        direction=str(
                                            ref.get("direction") or "OUTGOING"
                                        ),
                                    )
                                )

                    status, is_current = determine_legal_status(
                        version_info, amendments
                    )
                    raw_content = version_info.get("content_text") or ""
                    content_text = clean_provision_content(raw_content)

                    validated = ValidatedProvision(
                        provision_id=prov_id,
                        level=level,
                        status=status,
                        is_current=is_current,
                        version_id=version_info.get("version_id"),
                        valid_from=version_info.get("valid_from"),
                        valid_to=version_info.get("valid_to"),
                        content_text=content_text,
                        parent_article_id=record.get("parent_article_id"),
                        parent_article_title=record.get("parent_article_title"),
                        parent_clause_id=record.get("parent_clause_id"),
                        parent_clause_number=str(record.get("parent_clause_number"))
                        if record.get("parent_clause_number") is not None
                        else None,
                        parent_clause_content=clean_provision_content(
                            record.get("parent_clause_content")
                        ),
                        document_id=record.get("document_id"),
                        document_title=record.get("document_title"),
                        amendments=amendments,
                        cross_references=references,
                    )
                    results.append(validated)

                logger.info(
                    "Validated %d provisions from %d input IDs.",
                    len(results),
                    len(clean_ids),
                )
                return results

        except Exception as exc:
            logger.error("Failed to validate provisions via Neo4j: %s", exc)
            return []

    def find_document_amendments(
        self,
        doc_a: str,
        doc_b: str | None = None,
    ) -> list[DocumentAmendmentItem]:
        """Finds all direct amendment actions connecting two documents or impacting a document.

        Args:
            doc_a: Primary document ID or number (e.g. '238' or '238_2026_ND-CP').
            doc_b: Optional secondary document ID or number (e.g. '168' or '168_2024_ND-CP').

        Returns:
            List of unique DocumentAmendmentItem objects.
        """
        clean_a = doc_a.strip() if doc_a else ""
        clean_b = doc_b.strip() if doc_b else None
        if not clean_a:
            return []

        try:
            with self.client.session() as session:
                records = session.run(
                    DOCUMENT_AMENDMENTS_CYPHER_QUERY,
                    doc_a=clean_a,
                    doc_b=clean_b,
                )
                items_dict: dict[tuple[str, str, str], DocumentAmendmentItem] = {}

                for r in records:
                    target_id = str(r["target_id"])
                    operation = str(r["operation"])
                    instruction = str(r["instruction"] or "").strip()
                    article_id = str(r["article_id"]) if r.get("article_id") else None
                    article_title = (
                        str(r["article_title"]) if r.get("article_title") else None
                    )
                    target_title = (
                        str(r["target_title"]) if r.get("target_title") else None
                    )

                    rep_content = extract_replacement_text(
                        payload_json=r.get("replacement_payload"),
                        new_text=r.get("text_new"),
                        old_text=r.get("text_old"),
                        general_text=r.get("text_general"),
                    )

                    key = (target_id, operation, instruction)
                    if key not in items_dict:
                        items_dict[key] = DocumentAmendmentItem(
                            target_id=target_id,
                            target_title=target_title,
                            article_id=article_id,
                            article_title=article_title,
                            operation=operation,
                            instruction=instruction,
                            replacement_content=rep_content,
                            old_phrase=r.get("text_old"),
                            new_phrase=r.get("text_new"),
                        )
                    elif rep_content and not items_dict[key].replacement_content:
                        curr = items_dict[key]
                        items_dict[key] = DocumentAmendmentItem(
                            target_id=curr.target_id,
                            target_title=curr.target_title,
                            article_id=curr.article_id,
                            article_title=curr.article_title,
                            operation=curr.operation,
                            instruction=curr.instruction,
                            replacement_content=rep_content,
                            old_phrase=curr.old_phrase or r.get("text_old"),
                            new_phrase=curr.new_phrase or r.get("text_new"),
                        )

                logger.info(
                    "Found %d unique document amendments between '%s' and '%s'",
                    len(items_dict),
                    clean_a,
                    clean_b,
                )
                return list(items_dict.values())
        except Exception as exc:
            logger.warning(
                "Failed to traverse document amendments for '%s' - '%s': %s",
                clean_a,
                clean_b,
                exc,
            )
            return []

    def get_all_documents(self) -> list[dict[str, Any]]:
        """Retrieves all legal documents in the system database from Neo4j, with fallback to DOCUMENT_REGISTRY."""
        documents: list[dict[str, Any]] = []
        try:
            with self.client.session() as session:
                query = """
                MATCH (d:Document)
                RETURN d.id AS id, d.so_hieu AS so_hieu, d.ten AS ten, d.loai AS loai,
                       d.ngay_ban_hanh AS ngay_ban_hanh, d.hieu_luc_tu AS hieu_luc_tu
                ORDER BY d.loai, d.so_hieu
                """
                records = session.run(query)
                for r in records:
                    documents.append(
                        {
                            "id": r["id"],
                            "so_hieu": r["so_hieu"] or r["id"],
                            "ten": r["ten"] or "",
                            "loai": r["loai"]
                            or ("LUAT" if "QH" in str(r["id"]) else "NGHI_DINH"),
                            "ngay_ban_hanh": r.get("ngay_ban_hanh"),
                            "hieu_luc_tu": r.get("hieu_luc_tu"),
                        }
                    )
        except Exception as exc:
            logger.warning(
                "Failed to query Document nodes from Neo4j: %s. Using DOCUMENT_REGISTRY fallback.",
                exc,
            )

        if not documents:
            from src.config import DOCUMENT_REGISTRY

            for num, meta in DOCUMENT_REGISTRY.items():
                documents.append(
                    {
                        "id": meta.get("id", num),
                        "so_hieu": meta.get("number", num),
                        "ten": meta.get("name", ""),
                        "loai": meta.get("type", "NGHI_DINH"),
                        "role": meta.get("role", "NORMAL"),
                    }
                )

        return documents
