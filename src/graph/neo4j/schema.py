import logging

from neo4j import Session

from src.graph.neo4j.queries import validate_identifier

logger = logging.getLogger(__name__)

PRIMARY_NODE_LABELS = [
    "Document",
    "Chapter",
    "Article",
    "Clause",
    "Point",
    "SemanticUnit",
    "AmendmentAction",
    "AmendmentAppendix",
    "CanonicalProvision",
    "ProvisionVersion",
]

INDEX_DEFINITIONS = [
    ("ProvisionVersion", "valid_from"),
    ("ProvisionVersion", "valid_to"),
    ("ProvisionVersion", "is_current"),
    ("CanonicalProvision", "document_id"),
    ("AmendmentAction", "operation"),
]


class SchemaManager:
    """Manages creation of Cypher constraints and indexes in Neo4j."""

    @classmethod
    def create_constraints(cls, session: Session) -> list[str]:
        """Creates unique constraints on the 'id' property for all primary labels.

        Returns the list of executed Cypher statements.
        """
        executed: list[str] = []
        for label in PRIMARY_NODE_LABELS:
            clean_label = validate_identifier(label)
            constraint_name = f"constraint_{clean_label.lower()}_id_unique"
            query = (
                f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                f"FOR (n:{clean_label}) REQUIRE n.id IS UNIQUE"
            )
            logger.info("Ensuring constraint: %s", constraint_name)
            session.run(query)
            executed.append(query)
        return executed

    @classmethod
    def create_indexes(cls, session: Session) -> list[str]:
        """Creates secondary performance indexes.

        Returns the list of executed Cypher statements.
        """
        executed: list[str] = []
        for label, prop in INDEX_DEFINITIONS:
            clean_label = validate_identifier(label)
            clean_prop = validate_identifier(prop)
            index_name = f"index_{clean_label.lower()}_{clean_prop.lower()}"
            query = (
                f"CREATE INDEX {index_name} IF NOT EXISTS "
                f"FOR (n:{clean_label}) ON (n.{clean_prop})"
            )
            logger.info("Ensuring index: %s", index_name)
            session.run(query)
            executed.append(query)
        return executed

    @classmethod
    def init_schema(cls, session: Session) -> None:
        """Initializes all constraints and indexes in the Neo4j database."""
        logger.info("Initializing Neo4j schema constraints and indexes...")
        cls.create_constraints(session)
        cls.create_indexes(session)
        logger.info("Neo4j schema initialization completed.")
