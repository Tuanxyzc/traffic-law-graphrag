"""Query Service orchestrating GraphRAG pipeline and Server-Sent Events (SSE) streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from src.api.schemas.query import (
    QueryResponse,
    SubGraphEdgeSchema,
    SubGraphNodeSchema,
    SubGraphSchema,
)
from src.pipeline.models import PipelineResult
from src.pipeline.pipeline import GraphRAGPipeline

logger = logging.getLogger(__name__)


def convert_pipeline_subgraph(result: PipelineResult) -> SubGraphSchema | None:
    """Converts pipeline internal SubGraph to API schema."""
    if not result.subgraph or not result.subgraph.nodes:
        return None
    return SubGraphSchema(
        nodes=[
            SubGraphNodeSchema(id=n.id, label=n.label, properties=n.properties)
            for n in result.subgraph.nodes
        ],
        relationships=[
            SubGraphEdgeSchema(source=r.source, target=r.target, type=r.type, properties=r.properties)
            for r in result.subgraph.relationships
        ],
    )


class QueryService:
    """Service mediating synchronous and streaming interactions with GraphRAGPipeline."""

    def __init__(self, pipeline: GraphRAGPipeline) -> None:
        self.pipeline = pipeline

    async def execute_query(
        self,
        query: str,
        document_id: str | None = None,
        top_k: int = 5,
        include_subgraph: bool = True,
    ) -> QueryResponse:
        """Executes full GraphRAG pipeline in a separate worker thread to avoid blocking event loop."""
        logger.info("Executing synchronous GraphRAG query: '%s'", query)
        result: PipelineResult = await asyncio.to_thread(
            self.pipeline.run,
            user_query=query,
            document_id=document_id,
            top_k=top_k,
        )

        subgraph_schema = convert_pipeline_subgraph(result) if include_subgraph else None
        rewritten_obj = result.rewritten_query
        intent_str = getattr(rewritten_obj, "intent", "violation_sanction")
        search_query_str = getattr(rewritten_obj, "search_query", str(rewritten_obj))

        return QueryResponse(
            status="success" if intent_str != "out_of_scope" else "out_of_scope",
            user_query=result.user_query,
            search_query=search_query_str,
            intent=intent_str,
            answer=result.answer,
            citations=result.citations,
            subgraph=subgraph_schema,
            execution_time_ms=result.execution_time_ms,
            grounding_verified=result.grounding_verified,
            verification_warnings=result.verification_warnings,
        )

    async def execute_query_stream(
        self,
        query: str,
        document_id: str | None = None,
        top_k: int = 5,
        include_subgraph: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Streams step-by-step pipeline execution stages and answer tokens via Server-Sent Events (SSE)."""
        start_time = time.perf_counter()

        def format_sse(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        # 1. Stage: Rewriting
        yield format_sse(
            "stage",
            {"stage": "rewriting", "message": "Đang phân tích ý định và chuẩn hóa thuật ngữ pháp lý..."},
        )
        await asyncio.sleep(0.01)

        # 2. Stage: Retrieval & Graph Validation
        yield format_sse(
            "stage",
            {"stage": "retrieving", "message": "Đang tìm kiếm lai (Dense & BM25) và kiểm định đồ thị Neo4j..."},
        )

        # Execute pipeline core off-thread
        try:
            result: PipelineResult = await asyncio.to_thread(
                self.pipeline.run,
                user_query=query,
                document_id=document_id,
                top_k=top_k,
            )
        except Exception as exc:
            logger.exception("Error during streaming pipeline execution")
            yield format_sse("error", {"error": str(exc)})
            return

        # 3. Emit Subgraph event if requested
        if include_subgraph and result.subgraph and result.subgraph.nodes:
            subgraph_schema = convert_pipeline_subgraph(result)
            if subgraph_schema:
                yield format_sse("subgraph", subgraph_schema.model_dump())

        # 4. Stage: Generating Answer
        yield format_sse(
            "stage",
            {"stage": "generating", "message": "Đang tổng hợp câu trả lời dựa trên căn cứ pháp lý..."},
        )

        # Stream answer in chunks (words/tokens) to deliver responsive user experience
        words = result.answer.split(" ")
        for i in range(0, len(words), 3):
            token_chunk = " ".join(words[i : i + 3]) + " "
            yield format_sse("token", {"token": token_chunk})
            await asyncio.sleep(0.02)

        # 5. Final Stage: Done
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        rewritten_obj = result.rewritten_query
        intent_str = getattr(rewritten_obj, "intent", "violation_sanction")
        search_query_str = getattr(rewritten_obj, "search_query", str(rewritten_obj))

        yield format_sse(
            "done",
            {
                "user_query": result.user_query,
                "search_query": search_query_str,
                "intent": intent_str,
                "citations": result.citations,
                "execution_time_ms": elapsed_ms,
                "grounding_verified": result.grounding_verified,
                "verification_warnings": result.verification_warnings,
            },
        )
