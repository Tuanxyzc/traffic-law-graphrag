"""FastAPI Application Entrypoint and Lifespan Management."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.config import get_api_settings
from src.api.dependencies import get_neo4j_client, get_pipeline
from src.api.middleware.error_handler import register_exception_handlers
from src.api.middleware.timing import TimingMiddleware
from src.api.routes import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages application startup and graceful shutdown lifecycles."""
    settings = get_api_settings()
    logger.info("Initializing %s v%s...", settings.title, settings.version)

    # 1. Startup: verify Neo4j connectivity
    try:
        client = get_neo4j_client()
        if client.verify_connectivity():
            logger.info("Neo4j database connection verified successfully at %s", client.uri)
        else:
            logger.warning("Could not establish connection to Neo4j at startup.")
    except Exception as exc:
        logger.warning("Neo4j connection check encountered exception: %s", exc)

    # 2. Startup: Initialize pipeline singleton
    try:
        pipeline = get_pipeline()
        logger.info(
            "GraphRAGPipeline initialized with embedding model: %s",
            pipeline.retriever.config.embedding_model,
        )
    except Exception as exc:
        logger.warning("Pipeline pre-warming encountered exception: %s", exc)

    yield

    # 3. Shutdown: clean up driver connections
    logger.info("Shutting down %s...", settings.title)
    try:
        client = get_neo4j_client()
        if client._driver is not None:
            client.driver.close()
            logger.info("Neo4j driver connection closed.")
    except Exception as exc:
        logger.warning("Exception during Neo4j driver closure: %s", exc)


def create_app() -> FastAPI:
    """Factory creating and configuring the FastAPI application instance."""
    settings = get_api_settings()

    app = FastAPI(
        title=settings.title,
        version=settings.version,
        description=settings.description,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Middleware: CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware: Timing & Request-ID
    app.add_middleware(TimingMiddleware)

    # Register standardized error handlers
    register_exception_handlers(app)

    # Include API Routers
    app.include_router(api_router)

    # Mount Static Files & Serve UI
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app


# Application instance for ASGI servers (e.g. uvicorn src.api.main:app)
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_api_settings()
    uvicorn.run(
        "src.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
