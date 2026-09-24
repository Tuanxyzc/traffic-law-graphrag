"""FastAPI router for Corpus Ingestion and Indexing."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import get_ingest_service
from src.api.schemas.ingest import IngestRequest, IngestTaskStatusResponse
from src.api.services.ingest_service import IngestService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["Ingest"])


@router.post(
    "/corpus",
    response_model=IngestTaskStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kích hoạt tác vụ lập chỉ mục văn bản pháp luật (Background Task)",
    description="Nhận tệp JSON các đơn vị ngữ nghĩa (Semantic Units) và nạp vào Neo4j kèm vector embeddings trong tiến trình nền.",
)
async def trigger_corpus_ingestion(
    request: IngestRequest,
    service: Annotated[IngestService, Depends(get_ingest_service)],
) -> IngestTaskStatusResponse:
    """Schedules background corpus ingestion."""
    logger.info("Received corpus ingestion request for file: %s", request.json_file_path)
    task_status = await service.start_ingest_task(
        file_path=request.json_file_path,
        batch_size=request.batch_size,
        recreate_index=request.recreate_index,
    )
    return task_status


@router.get(
    "/status/{task_id}",
    response_model=IngestTaskStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Kiểm tra tiến độ tác vụ lập chỉ mục",
    description="Truy xuất trạng thái thực thi hiện tại của một tác vụ lập chỉ mục ngầm bằng mã `task_id`.",
)
async def check_ingest_status(
    task_id: str,
    service: Annotated[IngestService, Depends(get_ingest_service)],
) -> IngestTaskStatusResponse:
    """Retrieves status of background ingestion task."""
    status_obj = service.get_task_status(task_id)
    if status_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tác vụ lập chỉ mục với mã: '{task_id}'",
        )
    return status_obj
