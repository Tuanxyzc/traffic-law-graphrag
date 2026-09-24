"""FastAPI router for Liveness, Readiness, and Metrics."""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from src.api.dependencies import get_neo4j_client, get_pipeline
from src.graph.neo4j.connection import Neo4jClient
from src.pipeline.pipeline import GraphRAGPipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health & Monitoring"])

_START_TIME = time.time()


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
    description="Kiểm tra ứng dụng FastAPI đang hoạt động (dùng cho Docker & Kubernetes Liveness probe).",
)
async def liveness_probe() -> dict[str, str]:
    """Lightweight liveness check."""
    return {"status": "ok"}


@router.get(
    "/api/v1/health",
    status_code=status.HTTP_200_OK,
    summary="Readiness Probe",
    description="Kiểm tra tính sẵn sàng của các tài nguyên phụ thuộc: Kết nối Neo4j, Mô hình Embedding, Bộ khóa API LLM.",
)
async def readiness_probe(
    client: Annotated[Neo4jClient, Depends(get_neo4j_client)],
    pipeline: Annotated[GraphRAGPipeline, Depends(get_pipeline)],
    response: Response,
) -> dict[str, Any]:
    """Readiness probe checking internal and external dependencies."""
    neo4j_ok = client.verify_connectivity()
    key_manager = pipeline.key_manager
    total_keys = 0
    active_providers: list[str] = []
    if key_manager:
        total_keys = sum(len(keys) for keys in getattr(key_manager, "_providers_keys", {}).values())
        active_providers = getattr(key_manager, "_active_providers", [])

    is_ready = neo4j_ok
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if is_ready else "degraded",
        "neo4j_connected": neo4j_ok,
        "neo4j_uri": client.uri,
        "llm_keys_available": total_keys,
        "active_llm_providers": active_providers,
        "embedding_model": pipeline.retriever.config.embedding_model,
        "uptime_seconds": round(time.time() - _START_TIME, 2),
    }


@router.get(
    "/api/v1/metrics",
    status_code=status.HTTP_200_OK,
    summary="System Metrics",
    description="Thông tin tổng quan về thời gian hoạt động và trạng thái bộ nhớ.",
)
async def get_metrics() -> dict[str, Any]:
    """Basic runtime metrics."""
    return {
        "uptime_seconds": round(time.time() - _START_TIME, 2),
        "service": "traffic-law-graphrag-api",
        "version": "1.0.0",
    }
