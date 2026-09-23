from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.graph.models import GraphNode, GraphRelationship
from src.graph.neo4j.connection import Neo4jClient
from src.graph.neo4j.importer import Neo4jBatchImporter, chunk_list
from src.graph.neo4j.queries import (
    validate_identifier,
)
from src.graph.neo4j.schema import SchemaManager
from src.versioning.version_models import CanonicalProvision, ProvisionVersion


def test_chunk_list():
    items = list(range(10))
    chunks = chunk_list(items, 3)
    assert chunks == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
    assert chunk_list([], 5) == []
    assert chunk_list([1, 2], 0) == [[1, 2]]


def test_validate_identifier():
    assert validate_identifier("Article") == "Article"
    assert validate_identifier("HAS_CLAUSE") == "HAS_CLAUSE"
    with pytest.raises(ValueError, match="Invalid Cypher identifier"):
        validate_identifier("Article; DROP DATABASE")


def test_neo4j_client_configuration():
    client = Neo4jClient(
        uri="bolt://example.com:7687",
        username="custom_user",
        password="secret_password",
        database="test_db",
    )
    assert client.uri == "bolt://example.com:7687"
    assert client.username == "custom_user"
    assert client.password == "secret_password"
    assert client.database == "test_db"


def test_neo4j_client_context_manager():
    client = Neo4jClient(uri="bolt://localhost:7687")
    mock_driver = MagicMock()
    client._driver = mock_driver

    with client as c:
        assert c is client

    mock_driver.close.assert_called_once()
    assert client._driver is None


def test_schema_manager():
    mock_session = MagicMock()
    constraints = SchemaManager.create_constraints(mock_session)
    assert len(constraints) == 9
    assert any("FOR (n:Article) REQUIRE n.id IS UNIQUE" in c for c in constraints)
    assert mock_session.run.call_count == 9

    mock_session.reset_mock()
    indexes = SchemaManager.create_indexes(mock_session)
    assert len(indexes) == 4
    assert any("FOR (n:ProvisionVersion) ON (n.valid_from)" in idx for idx in indexes)
    assert mock_session.run.call_count == 4


def test_importer_import_nodes():
    mock_session = MagicMock()
    importer = Neo4jBatchImporter(batch_size=2)
    nodes = [
        GraphNode(id="D1", label="Article", properties={"number": "1"}),
        GraphNode(id="D2", label="Article", properties={"number": "2"}),
        GraphNode(id="D3", label="Article", properties={"number": "3"}),
        GraphNode(id="C1", label="Chapter", properties={"number": "I"}),
    ]

    total = importer.import_nodes(mock_session, nodes)
    assert total == 4
    assert mock_session.run.call_count == 3  # 2 chunks for Article, 1 chunk for Chapter


def test_importer_import_relationships():
    mock_session = MagicMock()
    importer = Neo4jBatchImporter(batch_size=2)
    relationships = [
        GraphRelationship(
            start_id="D1", relationship_type="HAS_CLAUSE", end_id="D1_K1"
        ),
        GraphRelationship(
            start_id="D1", relationship_type="HAS_CLAUSE", end_id="D1_K2"
        ),
        GraphRelationship(
            start_id="D1", relationship_type="HAS_CLAUSE", end_id="D1_K3"
        ),
    ]

    total = importer.import_relationships(mock_session, relationships)
    assert total == 3
    assert mock_session.run.call_count == 2  # 2 chunks of HAS_CLAUSE


def test_importer_import_provisions_and_versions():
    mock_session = MagicMock()
    importer = Neo4jBatchImporter(batch_size=10)

    provisions = {
        "D1": CanonicalProvision("D1", "doc_1", "ARTICLE", "1"),
    }
    versions = {
        "D1": [
            ProvisionVersion(
                version_id="D1_V1",
                canonical_provision_id="D1",
                valid_from="2020-01-01",
                valid_to="2022-01-01",
                content="Old content",
                is_current=False,
                produced_by=None,
            ),
            ProvisionVersion(
                version_id="D1_V2",
                canonical_provision_id="D1",
                valid_from="2022-01-01",
                valid_to=None,
                content="New content",
                is_current=True,
                produced_by="action_1",
            ),
        ]
    }

    num_p, num_v = importer.import_provisions_and_versions(
        mock_session, provisions, versions
    )
    assert num_p == 0
    assert num_v == 2
    # Ran: 1 batch versions, 1 batch HAS_VERSION, 1 batch NEXT_VERSION
    assert mock_session.run.call_count == 3


def test_importer_clear_database():
    mock_session = MagicMock()
    importer = Neo4jBatchImporter()
    importer.clear_database(mock_session)
    mock_session.run.assert_called_once_with("MATCH (n) DETACH DELETE n")


def _has_parsed_corpus() -> bool:
    parsed_dir = Path("data/parsed")
    return parsed_dir.exists() and any(parsed_dir.glob("*_structure.json"))


def test_importer_dry_run_execution():
    if not _has_parsed_corpus():
        pytest.skip(
            "Parsed corpus not found under data/parsed (skipped in non-corpus environments)"
        )
    importer = Neo4jBatchImporter()
    summary = importer.run(dry_run=True)
    assert summary["dry_run"] is True
    assert summary["nodes_count"] > 0
    assert summary["relationships_count"] > 0
    assert summary["provisions_count"] > 0
    assert summary["versions_count"] > 0


def test_sanitize_properties():
    from src.graph.neo4j.importer import sanitize_properties

    props = {
        "str_val": "test",
        "int_val": 42,
        "bool_val": True,
        "none_val": None,
        "nested_dict": {"foo": "bar"},
        "nested_list_dicts": [{"id": 1}],
        "primitive_list": ["a", "b", "c"],
    }
    sanitized = sanitize_properties(props)
    assert sanitized["str_val"] == "test"
    assert sanitized["int_val"] == 42
    assert sanitized["bool_val"] is True
    assert "none_val" not in sanitized
    assert sanitized["primitive_list"] == ["a", "b", "c"]
    assert sanitized["nested_dict"] == '{"foo": "bar"}'
    assert sanitized["nested_list_dicts"] == '[{"id": 1}]'


def test_parse_external_node_structure():
    from src.graph.neo4j.importer import parse_external_node_structure

    assert parse_external_node_structure("10_2020_ND-CP_D32", "10_2020_ND-CP") == (
        "Article",
        "32",
    )
    assert parse_external_node_structure("10_2020_ND-CP_D32_K1", "10_2020_ND-CP") == (
        "Clause",
        "1",
    )
    assert parse_external_node_structure(
        "10_2020_ND-CP_D32_K1_Da", "10_2020_ND-CP"
    ) == ("Point", "a")
    assert parse_external_node_structure("10_2020_ND-CP", "10_2020_ND-CP") == (
        "Document",
        "",
    )


def test_importer_loads_references_and_external_nodes():
    if not _has_parsed_corpus():
        pytest.skip(
            "Parsed corpus not found under data/parsed (skipped in non-corpus environments)"
        )
    importer = Neo4jBatchImporter()
    nodes, rels, _, _ = importer.load_corpus_data()

    # Check external nodes are loaded
    external_nodes = [n for n in nodes if n.properties.get("external") is True]
    assert len(external_nodes) > 0
    assert any(
        n.id == "10_2020_ND-CP_D32" and n.label == "Article" for n in external_nodes
    )

    # Check reference relationships are loaded in English
    ref_rels = [
        r
        for r in rels
        if r.relationship_type in ("REFERENCES", "EXCEPTION_TO", "PURSUANT_TO")
    ]
    assert len(ref_rels) > 0
    assert any(r.relationship_type == "REFERENCES" for r in ref_rels)
