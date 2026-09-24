"""FastAPI router for legal query endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_query_service
from src.api.schemas.query import QueryRequest, QueryResponse
from src.api.services.query_service import QueryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["Query"])


@router.post(
    "",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Tra cứu tư vấn pháp luật giao thông (Đồng bộ)",
    description=(
        "Thực thi toàn trình GraphRAG pipeline: chuẩn hóa thuật ngữ câu hỏi -> "
        "tìm kiếm lai Dense/Sparse -> kiểm định đồ thị Neo4j -> "
        "tổng hợp bằng chứng và sinh câu trả lời có căn cứ pháp lý."
    ),
)
async def query_traffic_law(
    request: QueryRequest,
    service: Annotated[QueryService, Depends(get_query_service)],
) -> QueryResponse:
    """Synchronous endpoint executing full pipeline and returning JSON answer."""
    logger.info("Received query request: '%s' (top_k=%d)", request.query, request.top_k)
    response = await service.execute_query(
        query=request.query,
        document_id=request.document_id,
        top_k=request.top_k,
        include_subgraph=request.include_subgraph,
    )
    return response


@router.post(
    "/stream",
    status_code=status.HTTP_200_OK,
    summary="Tra cứu tư vấn pháp luật giao thông dạng luồng (Server-Sent Events)",
    description=(
        "Trả về tiến trình xử lý và câu trả lời theo thời gian thực dưới dạng Server-Sent Events (SSE). "
        "Phù hợp cho giao diện người dùng hiển thị tức thì (Time-to-First-Token < 700ms)."
    ),
)
async def query_traffic_law_stream(
    request: QueryRequest,
    service: Annotated[QueryService, Depends(get_query_service)],
) -> StreamingResponse:
    """Streaming endpoint yielding SSE events (stage, token, subgraph, done)."""
    logger.info("Received streaming query request: '%s'", request.query)
    stream_generator = service.execute_query_stream(
        query=request.query,
        document_id=request.document_id,
        top_k=request.top_k,
        include_subgraph=request.include_subgraph,
    )
    return StreamingResponse(
        stream_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
