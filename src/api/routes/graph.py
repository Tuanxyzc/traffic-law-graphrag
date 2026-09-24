"""FastAPI router for Knowledge Graph inspection endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.dependencies import get_graph_service
from src.api.schemas.graph import DocumentMetaResponse, ProvisionDetailResponse
from src.api.schemas.query import SubGraphSchema
from src.api.services.graph_service import GraphService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


@router.get(
    "/documents",
    response_model=list[DocumentMetaResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh mục văn bản quy phạm pháp luật",
    description="Tra cứu danh mục toàn bộ văn bản luật, nghị định, thông tư lưu trong Neo4j kèm số lượng điều luật.",
)
async def list_documents(
    service: Annotated[GraphService, Depends(get_graph_service)],
    skip: Annotated[int, Query(ge=0, description="Số bản ghi bỏ qua")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Số bản ghi tối đa trả về")] = 20,
) -> list[DocumentMetaResponse]:
    """Retrieves list of legal documents in knowledge graph."""
    return await service.get_documents(skip=skip, limit=limit)


@router.get(
    "/provisions/{provision_id}",
    response_model=ProvisionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Tra cứu chi tiết và hiệu lực của một Điều/Khoản/Điểm",
    description="Truy xuất thông tin đầy đủ về một điều khoản: hiệu lực thời gian (:ProvisionVersion), sửa đổi [:AMENDS], và tham chiếu 1-hop [:THAM_CHIEU].",
)
async def get_provision_detail(
    provision_id: str,
    service: Annotated[GraphService, Depends(get_graph_service)],
) -> ProvisionDetailResponse:
    """Retrieves full details and validation status of a single provision."""
    detail = await service.get_provision(provision_id=provision_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy điều khoản với mã định danh: '{provision_id}'",
        )
    return detail


@router.get(
    "/subgraph",
    response_model=SubGraphSchema,
    status_code=status.HTTP_200_OK,
    summary="Lấy cấu trúc đồ thị con phục vụ trực quan hóa (Visual Subgraph)",
    description="Truy xuất mạng lưới các nút (Document, Article, Clause, Point) và liên kết giữa chúng cho các điều khoản được chỉ định.",
)
async def get_subgraph_nodes(
    service: Annotated[GraphService, Depends(get_graph_service)],
    unit_ids: Annotated[list[str], Query(description="Danh sách các mã điều khoản cần trực quan hóa")],
) -> SubGraphSchema:
    """Retrieves visual subgraph for given provision IDs."""
    return await service.get_subgraph(unit_ids=unit_ids)
