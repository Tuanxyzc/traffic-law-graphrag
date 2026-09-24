"""API Data contracts and schemas package."""

from src.api.schemas.common import (
    BaseResponse,
    ErrorDetail,
    ErrorResponse,
    PaginationParams,
)
from src.api.schemas.graph import (
    AmendmentRecordSchema,
    CrossReferenceSchema,
    DocumentMetaResponse,
    ProvisionDetailResponse,
    ProvisionVersionSchema,
)
from src.api.schemas.ingest import IngestRequest, IngestTaskStatusResponse
from src.api.schemas.query import (
    CitationItem,
    QueryRequest,
    QueryResponse,
    StreamChunkEvent,
    SubGraphEdgeSchema,
    SubGraphNodeSchema,
    SubGraphSchema,
)

__all__ = [
    "AmendmentRecordSchema",
    "BaseResponse",
    "CitationItem",
    "CrossReferenceSchema",
    "DocumentMetaResponse",
    "ErrorDetail",
    "ErrorResponse",
    "IngestRequest",
    "IngestTaskStatusResponse",
    "PaginationParams",
    "ProvisionDetailResponse",
    "ProvisionVersionSchema",
    "QueryRequest",
    "QueryResponse",
    "StreamChunkEvent",
    "SubGraphEdgeSchema",
    "SubGraphNodeSchema",
    "SubGraphSchema",
]
