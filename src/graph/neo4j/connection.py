import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from types import TracebackType
from typing import Any, Self

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from neo4j import Driver, GraphDatabase, Session

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Manages the Neo4j database driver, session lifecycle, and connectivity."""

    def __init__(
        self,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
        **driver_config: Any,
    ) -> None:
        self.uri: str = uri or os.getenv("NEO4J_URI") or "bolt://localhost:7687"
        self.username: str = username or os.getenv("NEO4J_USERNAME") or "neo4j"
        self.password: str = password or os.getenv("NEO4J_PASSWORD") or "password"
        self.database: str = database or os.getenv("NEO4J_DATABASE") or "neo4j"
        self.driver_config = driver_config
        self._driver: Driver | None = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
                **self.driver_config,
            )
        return self._driver

    def verify_connectivity(self) -> bool:
        """Verifies database reachability.

        Returns True if reachable, False otherwise.
        """
        try:
            self.driver.verify_connectivity()
            logger.info("Successfully connected to Neo4j at %s", self.uri)
            return True
        except Exception as exc:
            logger.warning("Failed to connect to Neo4j at %s: %s", self.uri, exc)
            return False

    @contextmanager
    def session(self, database: str | None = None) -> Generator[Session, None, None]:
        """Provides a managed Neo4j Session within a context manager."""
        db = database or self.database
        session = self.driver.session(database=db)
        try:
            yield session
        finally:
            session.close()

    def close(self) -> None:
        """Closes the Neo4j driver and releases connection pools."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
