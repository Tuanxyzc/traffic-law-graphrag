import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.graph.amendment.amendment_mapper import map_amendment_item
from src.graph.loader import load_json
from src.graph.mapper import map_document_structure
from src.graph.models import GraphNode, GraphRelationship
from src.graph.neo4j.connection import Neo4jClient
from src.graph.neo4j.queries import (
    make_batch_link_provision_versions_query,
    make_batch_link_version_timeline_query,
    make_batch_merge_nodes_query,
    make_batch_merge_provision_versions_query,
    make_batch_merge_relationships_query,
)
from src.graph.neo4j.schema import SchemaManager
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver
from src.versioning.version_builder import VersionBuilder
from src.versioning.version_models import CanonicalProvision, ProvisionVersion

logger = logging.getLogger(__name__)


def sanitize_properties(props: dict[str, Any] | None) -> dict[str, Any]:
    """Sanitizes property values so they are compatible with Neo4j property types.

    Neo4j supports primitives (int, float, bool, str) or homogenous lists of primitives.
    Nested dicts and non-primitive/mixed lists are serialized into JSON strings.
    None values are excluded to prevent storing nulls.
    """
    if not props:
        return {}
    clean_props: dict[str, Any] = {}
    for key, value in props.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean_props[key] = value
        elif isinstance(value, (list, tuple)):
            if not value:
                continue
            if (
                all(isinstance(v, (str, int, float, bool)) for v in value)
                and len({type(v) for v in value}) == 1
            ):
                clean_props[key] = list(value)
            else:
                clean_props[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, dict):
            clean_props[key] = json.dumps(value, ensure_ascii=False)
        else:
            clean_props[key] = str(value)
    return clean_props


REFERENCE_RELATION_MAP: dict[str, str] = {
    "THAM_CHIEU": "REFERENCES",
    "NGOAI_LE": "EXCEPTION_TO",
    "CAN_CU_VAO": "PURSUANT_TO",
    "HUONG_DAN": "GUIDES",
    "QUY_DINH_CHI_TIET": "DETAILS",
}


def parse_external_node_structure(node_id: str, document_id: str) -> tuple[str, str]:
    """Infers structural label (Article, Clause, Point, Document) and number from a node ID."""
    if not node_id:
        return "Document", ""
    suffix = (
        node_id[len(document_id) :].lstrip("_")
        if document_id and node_id.startswith(document_id)
        else node_id
    )
    parts = suffix.split("_")

    point_part = next(
        (
            p
            for p in reversed(parts)
            if p.startswith("D") and len(p) > 1 and not p[1:].isdigit()
        ),
        None,
    )
    if point_part:
        return "Point", point_part[1:]

    clause_part = next(
        (
            p
            for p in reversed(parts)
            if p.startswith("K") and len(p) > 1 and p[1:].isdigit()
        ),
        None,
    )
    if clause_part:
        return "Clause", clause_part[1:]

    article_part = next(
        (
            p
            for p in reversed(parts)
            if p.startswith("D") and len(p) > 1 and p[1:].isdigit()
        ),
        None,
    )
    if article_part:
        return "Article", article_part[1:]

    return "Document", ""


def chunk_list(items: list[Any], chunk_size: int) -> list[list[Any]]:
    """Splits a list into chunks of at most chunk_size items."""
    if chunk_size <= 0:
        return [items]
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


class Neo4jBatchImporter:
    """Orchestrates high-performance batch ingestion of legal knowledge graphs into Neo4j."""

    def __init__(
        self,
        client: Neo4jClient | None = None,
        parsed_dir: Path = Path("data/parsed"),
        batch_size: int = 500,
    ) -> None:
        self.client = client
        self.parsed_dir = parsed_dir
        self.batch_size = batch_size
        self.resolver = CanonicalIDResolver()

    def load_corpus_data(
        self, doc_filter: str | None = None
    ) -> tuple[
        list[GraphNode],
        list[GraphRelationship],
        dict[str, CanonicalProvision],
        dict[str, list[ProvisionVersion]],
    ]:
        """Loads and transforms all parsed JSON documents into in-memory graph models."""
        all_nodes: list[GraphNode] = []
        all_relationships: list[GraphRelationship] = []
        structure_nodes_by_doc: dict[str, list[GraphNode]] = {}
        amendment_actions_by_doc: list[dict[str, Any]] = []
        effective_rules_by_doc: dict[str, list[dict[str, Any]]] = {}

        # 0. Load Effective Rules globally across corpus so date lookups succeed
        for eff_file in sorted(self.parsed_dir.glob("*_effective_rules.json")):
            doc_id_eff = eff_file.name.replace("_effective_rules.json", "")
            eff_data = load_json(str(eff_file))
            if isinstance(eff_data, dict):
                effective_rules_by_doc[doc_id_eff] = eff_data.get("rules", [])
            elif isinstance(eff_data, list):
                effective_rules_by_doc[doc_id_eff] = eff_data

        # 1. Load Document Structure
        structure_files = sorted(self.parsed_dir.glob("*_structure.json"))
        for s_file in structure_files:
            doc_data = load_json(str(s_file))
            so_hieu = doc_data.get("so_hieu", "")
            doc_id = self.resolver.resolve_document(so_hieu)
            if doc_filter and doc_filter not in doc_id:
                continue

            nodes, rels = map_document_structure(doc_data, self.resolver)
            all_nodes.extend(nodes)
            all_relationships.extend(rels)
            structure_nodes_by_doc[doc_id] = nodes

        # 2. Load Amendment Actions
        amendment_files = sorted(self.parsed_dir.rglob("amendment_index.json"))
        semantic_index = 1
        for a_file in amendment_files:
            amendment_data = load_json(str(a_file))
            for event in amendment_data:
                src_doc = self.resolver.resolve_document(
                    event.get("source_document", "")
                )
                tgt_doc = self.resolver.resolve_document(
                    event.get("target_document", "")
                )
                if (
                    doc_filter
                    and doc_filter not in src_doc
                    and doc_filter not in tgt_doc
                ):
                    continue

                for item in event.get("items", []):
                    try:
                        nodes, rels = map_amendment_item(
                            item, semantic_index, self.resolver
                        )
                        all_nodes.extend(nodes)
                        all_relationships.extend(rels)
                    except Exception as exc:
                        logger.warning("Error mapping amendment item: %s", exc)
                    semantic_index += 1

                for item in event.get("items", []):
                    for action in item.get("actions", []):
                        amendment_actions_by_doc.append(
                            {
                                "source_document": event.get("source_document"),
                                "source_unit": item.get("source_unit"),
                                "action_id": action.get("action_id"),
                                "action": action,
                                "item": item,
                            }
                        )

        # 3. Load External Nodes
        external_file = self.parsed_dir / "external_nodes.json"
        if external_file.exists():
            ext_data = load_json(str(external_file))
            if isinstance(ext_data, list):
                for item in ext_data:
                    node_id = item.get("id")
                    if not node_id:
                        continue
                    doc_id = item.get("document_id") or ""
                    if doc_filter and doc_filter not in doc_id:
                        continue
                    label, number = parse_external_node_structure(node_id, doc_id)
                    all_nodes.append(
                        GraphNode(
                            label=label,
                            id=node_id,
                            properties={
                                "id": node_id,
                                "document_id": doc_id,
                                "number": number,
                                "external": True,
                            },
                        )
                    )

        # 4. Load Reference Indexes
        ref_files = sorted(self.parsed_dir.glob("*_reference_index.json"))
        seen_rels: set[tuple[str, str, str]] = set()
        for r_file in ref_files:
            ref_data = load_json(str(r_file))
            if isinstance(ref_data, list):
                for ref_item in ref_data:
                    source_id = ref_item.get("source")
                    target_id = ref_item.get("target")
                    if not source_id or not target_id:
                        continue
                    if source_id == target_id:
                        continue
                    if (
                        doc_filter
                        and doc_filter not in source_id
                        and doc_filter not in target_id
                    ):
                        continue
                    raw_rel = (ref_item.get("relation") or "THAM_CHIEU").strip().upper()
                    raw_rel = raw_rel.replace(" ", "_")
                    rel_type = REFERENCE_RELATION_MAP.get(raw_rel, raw_rel)
                    key = (source_id, rel_type, target_id)
                    if key in seen_rels:
                        continue
                    seen_rels.add(key)
                    all_relationships.append(
                        GraphRelationship(
                            start_id=source_id,
                            relationship_type=rel_type,
                            end_id=target_id,
                            properties={
                                "external": bool(ref_item.get("external", False))
                            },
                        )
                    )

        # 5. Build Provision Versions
        builder = VersionBuilder(
            structure_nodes_by_document=structure_nodes_by_doc,
            amendment_actions=amendment_actions_by_doc,
            effective_rules_by_document=effective_rules_by_doc,
            resolver=self.resolver,
        )
        provisions, versions = builder.build()

        return all_nodes, all_relationships, provisions, versions

    def import_nodes(self, session: Any, nodes: list[GraphNode]) -> int:
        """Batch-merges GraphNodes into Neo4j grouped by label."""
        nodes_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            nodes_by_label[node.label].append(
                {
                    "id": node.id,
                    "label": node.label,
                    "properties": sanitize_properties(node.properties),
                }
            )

        total_imported = 0
        for label, items in nodes_by_label.items():
            query = make_batch_merge_nodes_query(label)
            chunks = chunk_list(items, self.batch_size)
            for chunk in chunks:
                session.run(query, batch=chunk)
                total_imported += len(chunk)
            logger.info("Imported %d nodes with label ':%s'", len(items), label)

        return total_imported

    def import_relationships(
        self, session: Any, relationships: list[GraphRelationship]
    ) -> int:
        """Batch-merges GraphRelationships into Neo4j grouped by relationship type."""
        rels_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rel in relationships:
            if not rel.start_id or not rel.end_id:
                continue
            rels_by_type[rel.relationship_type].append(
                {
                    "start_id": rel.start_id,
                    "relationship_type": rel.relationship_type,
                    "end_id": rel.end_id,
                    "properties": sanitize_properties(rel.properties),
                }
            )

        total_imported = 0
        for rel_type, items in rels_by_type.items():
            query = make_batch_merge_relationships_query(rel_type)
            chunks = chunk_list(items, self.batch_size)
            for chunk in chunks:
                session.run(query, batch=chunk)
                total_imported += len(chunk)
            logger.info(
                "Imported %d relationships with type '[:%s]'", len(items), rel_type
            )

        return total_imported

    def import_provisions_and_versions(
        self,
        session: Any,
        provisions: dict[str, CanonicalProvision],
        versions: dict[str, list[ProvisionVersion]],
    ) -> tuple[int, int]:
        """Batch-merges ProvisionVersion nodes directly linked to Article/Clause/Point and timeline edges."""
        # 1. Ingest ProvisionVersion nodes & edges
        version_payloads: list[dict[str, Any]] = []
        has_version_links: list[dict[str, Any]] = []
        timeline_links: list[dict[str, Any]] = []

        for p_id, v_list in versions.items():
            for idx, v in enumerate(v_list):
                content_str = (
                    v.content if isinstance(v.content, str) else str(v.content)
                )
                version_payloads.append(
                    {
                        "id": v.version_id,
                        "canonical_provision_id": v.canonical_provision_id,
                        "valid_from": v.valid_from,
                        "valid_to": v.valid_to,
                        "is_current": v.is_current,
                        "produced_by": v.produced_by,
                        "effective_status": v.effective_status,
                        "content_text": content_str,
                    }
                )
                has_version_links.append(
                    {
                        "canonical_provision_id": p_id,
                        "version_id": v.version_id,
                    }
                )
                if idx > 0:
                    timeline_links.append(
                        {
                            "prev_version_id": v_list[idx - 1].version_id,
                            "next_version_id": v.version_id,
                        }
                    )

        v_query = make_batch_merge_provision_versions_query()
        for chunk in chunk_list(version_payloads, self.batch_size):
            session.run(v_query, batch=chunk)

        link_v_query = make_batch_link_provision_versions_query()
        for chunk in chunk_list(has_version_links, self.batch_size):
            session.run(link_v_query, batch=chunk)

        link_t_query = make_batch_link_version_timeline_query()
        for chunk in chunk_list(timeline_links, self.batch_size):
            session.run(link_t_query, batch=chunk)

        logger.info(
            "Imported %d ProvisionVersions with timelines linked to provisions",
            len(version_payloads),
        )
        return 0, len(version_payloads)

    def link_semantic_unit_containment(self, session: Any) -> dict[str, int]:
        """Synchronizes structural containment relationships (CONTAINS_*) to SemanticUnit nodes,

        ensuring uniform hierarchy across all documents matching Circular 72.
        """
        logger.info("Synchronizing CONTAINS_* containment edges for SemanticUnits...")
        # 1. Article -> SemanticUnit (cấp Khoản)
        q1 = """
        MATCH (ar:Article)-[:CONTAINS_CLAUSE]->(c:Clause)
        MATCH (su:SemanticUnit {id: c.id})
        MERGE (ar)-[r:CONTAINS_CLAUSE]->(su)
        RETURN count(r) AS cnt
        """
        res1 = session.run(q1).single()["cnt"]

        # 2. Chapter / Document -> SemanticUnit (cấp Điều)
        q2 = """
        MATCH (parent)-[:CONTAINS_ARTICLE]->(ar:Article)
        MATCH (su:SemanticUnit {id: ar.id})
        MERGE (parent)-[r:CONTAINS_ARTICLE]->(su)
        RETURN count(r) AS cnt
        """
        res2 = session.run(q2).single()["cnt"]

        # 3. SemanticUnit (cấp Khoản) -> Point
        q3 = """
        MATCH (c:Clause)-[:CONTAINS_POINT]->(p:Point)
        MATCH (su:SemanticUnit {id: c.id})
        MERGE (su)-[r:CONTAINS_POINT]->(p)
        RETURN count(r) AS cnt
        """
        res3 = session.run(q3).single()["cnt"]

        # 4. Clause -> SemanticUnit (cấp Điểm)
        q4 = """
        MATCH (c:Clause)-[:CONTAINS_POINT]->(p:Point)
        MATCH (su:SemanticUnit {id: p.id})
        MERGE (c)-[r:CONTAINS_POINT]->(su)
        RETURN count(r) AS cnt
        """
        res4 = session.run(q4).single()["cnt"]

        summary = {
            "article_to_clause_su": res1,
            "parent_to_article_su": res2,
            "clause_su_to_point": res3,
            "clause_to_point_su": res4,
        }
        logger.info("SemanticUnit containment linking completed: %s", summary)
        return summary

    def clear_database(self, session: Any) -> None:
        """Clears all nodes and relationships in the active database."""
        logger.warning("Clearing all data from Neo4j database...")
        session.run("MATCH (n) DETACH DELETE n")
        logger.info("Database clear completed.")

    def run(
        self,
        dry_run: bool = False,
        clear: bool = False,
        doc_filter: str | None = None,
    ) -> dict[str, Any]:
        """Orchestrates the entire batch ingestion pipeline."""
        logger.info(
            "Starting ingestion pipeline (dry_run=%s, clear=%s, doc_filter=%s)...",
            dry_run,
            clear,
            doc_filter,
        )
        nodes, rels, provisions, versions = self.load_corpus_data(doc_filter=doc_filter)
        summary = {
            "nodes_count": len(nodes),
            "relationships_count": len(rels),
            "provisions_count": len(provisions),
            "versions_count": sum(len(v) for v in versions.values()),
            "dry_run": dry_run,
        }

        if dry_run:
            logger.info("DRY-RUN completed successfully. Summary: %s", summary)
            return summary

        client = self.client or Neo4jClient()
        with client.session() as session:
            if clear:
                self.clear_database(session)

            SchemaManager.init_schema(session)
            self.import_nodes(session, nodes)
            self.import_provisions_and_versions(session, provisions, versions)
            self.import_relationships(session, rels)
            self.link_semantic_unit_containment(session)

        logger.info("Full ingestion pipeline completed successfully: %s", summary)
        return summary


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Ingest legal corpus graph into Neo4j")
    parser.add_argument(
        "--all", action="store_true", default=True, help="Import all corpus documents"
    )
    parser.add_argument(
        "--doc", type=str, default=None, help="Filter by specific document ID"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate parsing and batch preparation without database connection",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing data in database before import",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Batch chunk size (default: 500)"
    )

    args = parser.parse_args()

    importer = Neo4jBatchImporter(batch_size=args.batch_size)
    try:
        summary = importer.run(
            dry_run=args.dry_run, clear=args.clear, doc_filter=args.doc
        )
        print("\n=== NEO4J INGESTION SUMMARY ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print("===============================\n")
    except Exception:
        logger.exception("Ingestion failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
