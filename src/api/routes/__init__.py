"""API Routers package aggregating all endpoint routers."""

from fastapi import APIRouter

from src.api.routes.graph import router as graph_router
from src.api.routes.health import router as health_router
from src.api.routes.ingest import router as ingest_router
from src.api.routes.query import router as query_router

api_router = APIRouter()

# Group standard v1 routers
api_router.include_router(query_router, prefix="/api/v1")
api_router.include_router(graph_router, prefix="/api/v1")
api_router.include_router(ingest_router, prefix="/api/v1")

# Health routes are included directly (handles both /health and /api/v1/health)
api_router.include_router(health_router)

__all__ = ["api_router"]
