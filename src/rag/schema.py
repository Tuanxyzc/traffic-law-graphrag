"""Neo4j Schema & Index Management for Traditional RAG (Vector and Full-Text Indexes)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import Session

from src.rag.config import RAGConfig

logger = logging.getLogger(__name__)


class RAGSchemaManager:
    """Manages creation, verification, and status validation of Neo4j RAG indexes."""

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()

    def get_constraint_statement(self) -> str:
        """Returns the Cypher statement to create the unique constraint on :SemanticUnit(id)."""
        return (
            f"CREATE CONSTRAINT {self.config.constraint_name} IF NOT EXISTS "
            "FOR (n:SemanticUnit) REQUIRE n.id IS UNIQUE"
        )

    def get_vector_index_statement(self) -> str:
        """Returns the Cypher statement to create the 1024-dim cosine Vector Index."""
        return (
            f"CREATE VECTOR INDEX {self.config.vector_index_name} IF NOT EXISTS "
            "FOR (n:SemanticUnit) ON (n.embedding) "
            "OPTIONS {indexConfig: {"
            f"`vector.dimensions`: {self.config.embedding_dim}, "
            "`vector.similarity_function`: 'cosine'"
            "}}"
        )

    def get_fulltext_index_statement(self) -> str:
        """Returns the Cypher statement to create the Full-Text Index on text and title."""
        return (
            f"CREATE FULLTEXT INDEX {self.config.fulltext_index_name} IF NOT EXISTS "
            "FOR (n:SemanticUnit) ON EACH [n.text, n.tieu_de_dieu]"
        )

    def get_article_fulltext_index_statement(self) -> str:
        """Returns the Cypher statement to create the Full-Text Index on Article nodes."""
        return (
            f"CREATE FULLTEXT INDEX {self.config.article_fulltext_index_name} IF NOT EXISTS "
            "FOR (a:Article) ON EACH [a.title, a.content, a.id]"
        )

    def get_document_fulltext_index_statement(self) -> str:
        """Returns the Cypher statement to create the Full-Text Index on Document nodes."""
        return (
            f"CREATE FULLTEXT INDEX {self.config.document_fulltext_index_name} IF NOT EXISTS "
            "FOR (d:Document) ON EACH [d.so_hieu, d.ten, d.id]"
        )

    def ensure_schema(self, session: Session) -> list[str]:
        """Executes Cypher statements ensuring constraint, vector index, and all fulltext indexes exist."""
        executed: list[str] = []

        # 1. Unique constraint
        constraint_stmt = self.get_constraint_statement()
        logger.info("Ensuring constraint: %s", self.config.constraint_name)
        session.run(constraint_stmt)
        executed.append(constraint_stmt)

        # 2. Vector Index
        vector_stmt = self.get_vector_index_statement()
        logger.info("Ensuring vector index: %s", self.config.vector_index_name)
        session.run(vector_stmt)
        executed.append(vector_stmt)

        # 3. SemanticUnit Fulltext Index
        fulltext_stmt = self.get_fulltext_index_statement()
        logger.info("Ensuring fulltext index: %s", self.config.fulltext_index_name)
        session.run(fulltext_stmt)
        executed.append(fulltext_stmt)

        # 4. Article Fulltext Index
        article_ft_stmt = self.get_article_fulltext_index_statement()
        logger.info(
            "Ensuring article fulltext index: %s",
            self.config.article_fulltext_index_name,
        )
        session.run(article_ft_stmt)
        executed.append(article_ft_stmt)

        # 5. Document Fulltext Index
        doc_ft_stmt = self.get_document_fulltext_index_statement()
        logger.info(
            "Ensuring document fulltext index: %s",
            self.config.document_fulltext_index_name,
        )
        session.run(doc_ft_stmt)
        executed.append(doc_ft_stmt)

        return executed

    def check_indexes_status(self, session: Session) -> dict[str, str]:
        """Queries Neo4j for the current population/operational state of RAG indexes."""
        query = (
            "SHOW INDEXES YIELD name, state, type "
            "WHERE name IN [$v_name, $f_name, $a_name, $d_name] "
            "RETURN name, state, type"
        )
        result = session.run(
            query,
            v_name=self.config.vector_index_name,
            f_name=self.config.fulltext_index_name,
            a_name=self.config.article_fulltext_index_name,
            d_name=self.config.document_fulltext_index_name,
        )
        status_map: dict[str, str] = {}
        for record in result:
            status_map[record["name"]] = record["state"]
        return status_map

    def wait_for_indexes(
        self,
        session: Session,
        timeout_sec: float = 30.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Waits until vector and fulltext indexes transition to 'ONLINE' state."""
        start_time = time.time()
        expected = {
            self.config.vector_index_name,
            self.config.fulltext_index_name,
            self.config.article_fulltext_index_name,
            self.config.document_fulltext_index_name,
        }

        while (time.time() - start_time) < timeout_sec:
            statuses = self.check_indexes_status(session)
            all_online = expected.issubset(statuses.keys()) and all(
                statuses[name] == "ONLINE" for name in expected
            )
            if all_online:
                logger.info("All RAG indexes are ONLINE.")
                return True
            time.sleep(poll_interval)

        logger.warning("Timed out waiting for RAG indexes to become ONLINE.")
        return False
