"""Dependency Injection providers for FastAPI application."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from src.api.services.graph_service import GraphService
from src.api.services.ingest_service import IngestService
from src.api.services.query_service import QueryService
from src.graph.neo4j.connection import Neo4jClient
from src.pipeline.pipeline import GraphRAGPipeline

_neo4j_client: Neo4jClient | None = None
_pipeline: GraphRAGPipeline | None = None
_ingest_service: IngestService | None = None


def get_neo4j_client() -> Neo4jClient:
    """Returns singleton Neo4jClient."""
    global _neo4j_client
    if _neo4j_client is None:
        _neo4j_client = Neo4jClient()
    return _neo4j_client


def get_pipeline() -> GraphRAGPipeline:
    """Returns singleton GraphRAGPipeline."""
    global _pipeline
    if _pipeline is None:
        _pipeline = GraphRAGPipeline()
    return _pipeline


def get_query_service(
    pipeline: Annotated[GraphRAGPipeline, Depends(get_pipeline)],
) -> QueryService:
    """Returns QueryService bound to the resolved pipeline dependency."""
    return QueryService(pipeline=pipeline)


def get_graph_service(
    client: Annotated[Neo4jClient, Depends(get_neo4j_client)],
) -> GraphService:
    """Returns GraphService bound to the resolved Neo4jClient dependency."""
    return GraphService(neo4j_client=client)


def get_ingest_service() -> IngestService:
    """Returns singleton IngestService holding background task states."""
    global _ingest_service
    if _ingest_service is None:
        _ingest_service = IngestService()
    return _ingest_service
