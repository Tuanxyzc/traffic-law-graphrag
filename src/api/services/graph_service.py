"""Graph Service managing queries to Neo4j knowledge graph."""

from __future__ import annotations

import asyncio
import logging

from src.api.schemas.graph import (
    AmendmentRecordSchema,
    CrossReferenceSchema,
    DocumentMetaResponse,
    ProvisionDetailResponse,
    ProvisionVersionSchema,
)
from src.api.schemas.query import SubGraphEdgeSchema, SubGraphNodeSchema, SubGraphSchema
from src.graph.neo4j.connection import Neo4jClient
from src.pipeline.graph_validator import GraphValidator

logger = logging.getLogger(__name__)


class GraphService:
    """Service handling legal document catalog, provision inspection, and subgraph queries."""

    def __init__(self, neo4j_client: Neo4jClient, validator: GraphValidator | None = None) -> None:
        self.neo4j_client = neo4j_client
        self.validator = validator or GraphValidator()

    def _sync_get_documents(self, skip: int = 0, limit: int = 20) -> list[DocumentMetaResponse]:
        """Synchronously retrieves document catalog with article counts."""
        query = (
            "MATCH (d:Document) "
            "OPTIONAL MATCH (d)-[:CONTAINS_ARTICLE|CONTAINS_CHAPTER*1..2]->(a:Article) "
            "WITH d, count(DISTINCT a) AS article_count "
            "RETURN d.id AS id, d.so_hieu AS so_hieu, coalesce(d.ten, d.tieu_de) AS ten, "
            "       d.loai AS loai, d.ngay_ban_hanh AS ngay_ban_hanh, d.ngay_hieu_luc AS ngay_hieu_luc, "
            "       d.ngay_het_hieu_luc AS ngay_het_hieu_luc, d.status AS status, "
            "       article_count "
            "ORDER BY d.ngay_hieu_luc DESC, d.id ASC "
            "SKIP $skip LIMIT $limit"
        )
        with self.neo4j_client.session() as session:
            result = session.run(query, skip=skip, limit=limit)
            docs: list[DocumentMetaResponse] = []
            for record in result:
                docs.append(
                    DocumentMetaResponse(
                        id=record["id"] or "",
                        so_hieu=record["so_hieu"],
                        ten=record["ten"],
                        loai=record["loai"],
                        ngay_ban_hanh=record["ngay_ban_hanh"],
                        ngay_hieu_luc=record["ngay_hieu_luc"],
                        ngay_het_hieu_luc=record["ngay_het_hieu_luc"],
                        status=record["status"],
                        total_articles=record["article_count"] or 0,
                    )
                )
            return docs

    async def get_documents(self, skip: int = 0, limit: int = 20) -> list[DocumentMetaResponse]:
        """Asynchronously retrieves legal document catalog from Neo4j."""
        return await asyncio.to_thread(self._sync_get_documents, skip=skip, limit=limit)

    def _sync_get_provision(self, provision_id: str) -> ProvisionDetailResponse | None:
        """Synchronously validates and extracts detailed information for a single provision."""
        validated_provisions = self.validator.validate_provisions([provision_id])
        if not validated_provisions:
            return None

        p = validated_provisions[0]
        cur_v = ProvisionVersionSchema(
            version_id=p.version_id,
            is_current=p.is_current,
            valid_from=p.valid_from,
            valid_to=p.valid_to,
            statutory_status=p.status.value if hasattr(p.status, "value") else str(p.status),
        )

        cross_refs = [
            CrossReferenceSchema(
                target_id=ref.target_id,
                target_title=ref.title,
                relation_type=ref.relation_type,
                content=ref.content,
                direction=ref.direction,
            )
            for ref in p.cross_references
        ]

        amendments = [
            AmendmentRecordSchema(
                operation=a.operation,
                by_document=a.by_document,
                instruction=a.instruction,
                replacement_text=a.replacement_text,
                effective_from=a.effective_from,
                direction=a.direction,
            )
            for a in p.amendments
        ]

        return ProvisionDetailResponse(
            provision_id=p.provision_id,
            level=p.level,
            document_id=p.document_id,
            document_title=p.document_title,
            parent_article_id=p.parent_article_id,
            parent_article_title=p.parent_article_title,
            parent_clause_id=p.parent_clause_id,
            parent_clause_number=p.parent_clause_number,
            content=p.content_text,
            current_version=cur_v,
            cross_references=cross_refs,
            amendments=amendments,
        )

    async def get_provision(self, provision_id: str) -> ProvisionDetailResponse | None:
        """Asynchronously retrieves detailed provision information."""
        return await asyncio.to_thread(self._sync_get_provision, provision_id=provision_id)

    def _sync_get_subgraph(self, unit_ids: list[str]) -> SubGraphSchema:
        """Synchronously traverses and builds visual subgraph for requested unit IDs."""
        if not unit_ids:
            return SubGraphSchema()

        query = (
            "UNWIND $unit_ids AS uid "
            "MATCH (n {id: uid}) "
            "OPTIONAL MATCH (n)-[r]-(m) "
            "WHERE (m:Article OR m:Clause OR m:Point OR m:Document OR m:ProvisionVersion) "
            "RETURN DISTINCT n, r, m LIMIT 100"
        )
        nodes_map: dict[str, SubGraphNodeSchema] = {}
        relationships_set: set[tuple[str, str, str]] = set()
        relationships: list[SubGraphEdgeSchema] = []

        with self.neo4j_client.session() as session:
            result = session.run(query, unit_ids=unit_ids)
            for record in result:
                n = record.get("n")
                r = record.get("r")
                m = record.get("m")
                if n and n.get("id"):
                    nid = n["id"]
                    lbl = next(iter(n.labels)) if hasattr(n, "labels") and n.labels else "Node"
                    props = dict(n)
                    props.pop("embedding", None)
                    nodes_map[nid] = SubGraphNodeSchema(id=nid, label=lbl, properties=props)
                if m and m.get("id"):
                    mid = m["id"]
                    lbl_m = next(iter(m.labels)) if hasattr(m, "labels") and m.labels else "Node"
                    props_m = dict(m)
                    props_m.pop("embedding", None)
                    nodes_map[mid] = SubGraphNodeSchema(id=mid, label=lbl_m, properties=props_m)
                if r:
                    src = n.get("id") if n else None
                    tgt = m.get("id") if m else None
                    rtype = r.type
                    if src and tgt:
                        rel_key = (src, tgt, rtype)
                        if rel_key not in relationships_set:
                            relationships_set.add(rel_key)
                            relationships.append(
                                SubGraphEdgeSchema(
                                    source=src, target=tgt, type=rtype, properties=dict(r)
                                )
                            )

        return SubGraphSchema(nodes=list(nodes_map.values()), relationships=relationships)

    async def get_subgraph(self, unit_ids: list[str]) -> SubGraphSchema:
        """Asynchronously traverses and returns visual subgraph."""
        return await asyncio.to_thread(self._sync_get_subgraph, unit_ids=unit_ids)
