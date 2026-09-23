from unittest.mock import MagicMock

from src.graph.neo4j.queries import (
    QUERY_POINT_IN_TIME_PROVISIONS,
    get_active_provisions_at_date,
    make_batch_link_provision_versions_query,
    make_batch_link_version_timeline_query,
    make_batch_merge_canonical_provisions_query,
    make_batch_merge_nodes_query,
    make_batch_merge_provision_versions_query,
    make_batch_merge_relationships_query,
)


def test_make_batch_merge_nodes_query():
    query = make_batch_merge_nodes_query("Article")
    assert "UNWIND $batch AS row" in query
    assert "MERGE (n:Article {id: row.id})" in query
    assert "SET n += row.properties" in query


def test_make_batch_merge_relationships_query():
    query = make_batch_merge_relationships_query("CONTAINS_ARTICLE")
    assert "UNWIND $batch AS row" in query
    assert "MATCH (start {id: row.start_id})" in query
    assert "MATCH (end {id: row.end_id})" in query
    assert "MERGE (start)-[r:CONTAINS_ARTICLE]->(end)" in query


def test_provision_version_queries():
    q_p = make_batch_merge_canonical_provisions_query()
    assert "MERGE (p:CanonicalProvision {id: row.id})" in q_p

    q_v = make_batch_merge_provision_versions_query()
    assert "MERGE (v:ProvisionVersion {id: row.id})" in q_v

    q_link_v = make_batch_link_provision_versions_query()
    assert "MERGE (p)-[:HAS_VERSION]->(v)" in q_link_v

    q_link_t = make_batch_link_version_timeline_query()
    assert "MERGE (v1)-[:NEXT_VERSION]->(v2)" in q_link_t


def test_get_active_provisions_at_date():
    mock_session = MagicMock()
    mock_record1 = MagicMock()
    mock_record1.data.return_value = {
        "provision_id": "doc_1_D1",
        "level": "ARTICLE",
        "version_id": "doc_1_D1_V1",
        "valid_from": "2020-01-01",
        "valid_to": None,
        "is_current": True,
        "content_text": "Noi dung dieu 1",
    }
    mock_session.run.return_value = [mock_record1]

    results = get_active_provisions_at_date(mock_session, "doc_1", "2021-06-01")
    assert len(results) == 1
    assert results[0]["provision_id"] == "doc_1_D1"
    mock_session.run.assert_called_once_with(
        QUERY_POINT_IN_TIME_PROVISIONS, doc_id="doc_1", target_date="2021-06-01"
    )
