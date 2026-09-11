import re
from typing import Any

VALID_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def validate_identifier(name: str) -> str:
    """Validates that label or relationship type names are alphanumeric/underscores

    to protect Cypher statements from injection.
    """
    if not VALID_IDENTIFIER.match(name):
        raise ValueError(f"Invalid Cypher identifier: {name}")
    return name


def make_batch_merge_nodes_query(label: str) -> str:
    """Generates parameterized Cypher statement for batch merging nodes with a specific label."""
    clean_label = validate_identifier(label)
    return (
        f"UNWIND $batch AS row "
        f"MERGE (n:{clean_label} {{id: row.id}}) "
        f"SET n += row.properties"
    )


def make_batch_merge_relationships_query(relationship_type: str) -> str:
    """Generates parameterized Cypher statement for batch merging relationships."""
    clean_rel = validate_identifier(relationship_type)
    return (
        f"UNWIND $batch AS row "
        f"MATCH (start {{id: row.start_id}}) "
        f"MATCH (end {{id: row.end_id}}) "
        f"MERGE (start)-[r:{clean_rel}]->(end) "
        f"SET r += row.properties"
    )


def make_batch_merge_canonical_provisions_query() -> str:
    """Generates Cypher statement for batch merging CanonicalProvision nodes."""
    return (
        "UNWIND $batch AS row "
        "MERGE (p:CanonicalProvision {id: row.id}) "
        "SET p.canonical_provision_id = row.id, "
        "    p.document_id = row.document_id, "
        "    p.level = row.level, "
        "    p.number = row.number"
    )


def make_batch_merge_provision_versions_query() -> str:
    """Generates Cypher statement for batch merging ProvisionVersion nodes."""
    return (
        "UNWIND $batch AS row "
        "MERGE (v:ProvisionVersion {id: row.id}) "
        "SET v.version_id = row.id, "
        "    v.canonical_provision_id = row.canonical_provision_id, "
        "    v.valid_from = row.valid_from, "
        "    v.valid_to = row.valid_to, "
        "    v.is_current = row.is_current, "
        "    v.produced_by = row.produced_by, "
        "    v.effective_status = row.effective_status, "
        "    v.content_text = row.content_text"
    )


def make_batch_link_provision_versions_query() -> str:
    """Generates Cypher statement to connect CanonicalProvision to its ProvisionVersions."""
    return (
        "UNWIND $batch AS row "
        "MATCH (p:CanonicalProvision {id: row.canonical_provision_id}) "
        "MATCH (v:ProvisionVersion {id: row.version_id}) "
        "MERGE (p)-[:HAS_VERSION]->(v)"
    )


def make_batch_link_version_timeline_query() -> str:
    """Generates Cypher statement to connect consecutive versions via NEXT_VERSION."""
    return (
        "UNWIND $batch AS row "
        "MATCH (v1:ProvisionVersion {id: row.prev_version_id}) "
        "MATCH (v2:ProvisionVersion {id: row.next_version_id}) "
        "MERGE (v1)-[:NEXT_VERSION]->(v2)"
    )


QUERY_POINT_IN_TIME_PROVISIONS = (
    "MATCH (p:CanonicalProvision {document_id: $doc_id})-[:HAS_VERSION]->(v:ProvisionVersion) "
    "WHERE (v.valid_from IS NULL OR v.valid_from <= $target_date) "
    "  AND (v.valid_to IS NULL OR v.valid_to > $target_date) "
    "RETURN p.canonical_provision_id AS provision_id, "
    "       p.level AS level, "
    "       v.version_id AS version_id, "
    "       v.valid_from AS valid_from, "
    "       v.valid_to AS valid_to, "
    "       v.is_current AS is_current, "
    "       v.content_text AS content_text "
    "ORDER BY p.canonical_provision_id"
)


def get_active_provisions_at_date(
    session: Any, doc_id: str, target_date: str
) -> list[dict[str, Any]]:
    """Executes point-in-time traversal query to retrieve active provision versions

    for a document at target_date.
    """
    result = session.run(
        QUERY_POINT_IN_TIME_PROVISIONS, doc_id=doc_id, target_date=target_date
    )
    return [record.data() for record in result]
