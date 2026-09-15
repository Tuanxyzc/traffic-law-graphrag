"""Tests for Neo4j RAGSchemaManager."""

from unittest.mock import MagicMock

from src.rag.config import RAGConfig
from src.rag.schema import RAGSchemaManager


def test_schema_statements() -> None:
    config = RAGConfig(
        embedding_dim=1024,
        vector_index_name="test_vector_idx",
        fulltext_index_name="test_fulltext_idx",
        constraint_name="test_constraint",
    )
    manager = RAGSchemaManager(config=config)

    constraint_stmt = manager.get_constraint_statement()
    assert "CREATE CONSTRAINT test_constraint IF NOT EXISTS" in constraint_stmt
    assert "FOR (n:SemanticUnit) REQUIRE n.id IS UNIQUE" in constraint_stmt

    vector_stmt = manager.get_vector_index_statement()
    assert "CREATE VECTOR INDEX test_vector_idx IF NOT EXISTS" in vector_stmt
    assert "`vector.dimensions`: 1024" in vector_stmt
    assert "`vector.similarity_function`: 'cosine'" in vector_stmt

    fulltext_stmt = manager.get_fulltext_index_statement()
    assert "CREATE FULLTEXT INDEX test_fulltext_idx IF NOT EXISTS" in fulltext_stmt
    assert "ON EACH [n.text, n.tieu_de_dieu]" in fulltext_stmt


def test_ensure_schema_execution() -> None:
    mock_session = MagicMock()
    manager = RAGSchemaManager()

    executed = manager.ensure_schema(mock_session)
    assert len(executed) == 3
    assert mock_session.run.call_count == 3


def test_check_indexes_status() -> None:
    mock_session = MagicMock()
    mock_records = [
        {"name": "semantic_unit_vector", "state": "ONLINE", "type": "VECTOR"},
        {"name": "semantic_unit_fulltext", "state": "ONLINE", "type": "FULLTEXT"},
    ]
    mock_session.run.return_value = mock_records

    manager = RAGSchemaManager()
    statuses = manager.check_indexes_status(mock_session)

    assert statuses["semantic_unit_vector"] == "ONLINE"
    assert statuses["semantic_unit_fulltext"] == "ONLINE"


def test_wait_for_indexes_online() -> None:
    mock_session = MagicMock()
    mock_records = [
        {"name": "semantic_unit_vector", "state": "ONLINE", "type": "VECTOR"},
        {"name": "semantic_unit_fulltext", "state": "ONLINE", "type": "FULLTEXT"},
    ]
    mock_session.run.return_value = mock_records

    manager = RAGSchemaManager()
    success = manager.wait_for_indexes(mock_session, timeout_sec=1.0)
    assert success is True


def test_wait_for_indexes_timeout() -> None:
    mock_session = MagicMock()
    mock_records = [
        {"name": "semantic_unit_vector", "state": "POPULATING", "type": "VECTOR"},
        {"name": "semantic_unit_fulltext", "state": "POPULATING", "type": "FULLTEXT"},
    ]
    mock_session.run.return_value = mock_records

    manager = RAGSchemaManager()
    success = manager.wait_for_indexes(
        mock_session, timeout_sec=0.2, poll_interval=0.05
    )
    assert success is False
