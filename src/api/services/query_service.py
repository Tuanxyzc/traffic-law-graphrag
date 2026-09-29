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
from src.pipeline.models import PipelineResult, RoutingDecision
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
            SubGraphEdgeSchema(
                source=r.source, target=r.target, type=r.type, properties=r.properties
            )
            for r in result.subgraph.relationships
        ],
    )


def extract_routing_action_str(action: Any) -> str | None:
    """Extracts string representation of RoutingAction enum or string."""
    if action is None:
        return None
    if hasattr(action, "value"):
        return str(action.value)
    return str(action)


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

        subgraph_schema = (
            convert_pipeline_subgraph(result) if include_subgraph else None
        )
        rewritten_obj = result.rewritten_query
        intent_str = getattr(rewritten_obj, "intent", "violation_sanction")
        search_query_str = getattr(rewritten_obj, "search_query", str(rewritten_obj))

        routing_action_str = extract_routing_action_str(result.routing_action)

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
            routing_action=routing_action_str,
            matched_unit_id=result.matched_unit_id,
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

        # 0. Stage: Routing (Start)
        yield format_sse(
            "stage",
            {
                "stage": "routing",
                "status": "running",
                "message": "Đang phân tích tọa độ pháp lý & phân luồng truy vấn...",
            },
        )
        await asyncio.sleep(0.01)

        routing_decision = None
        if hasattr(self.pipeline, "router") and self.pipeline.router:
            try:
                cand = await asyncio.to_thread(
                    self.pipeline.router.route,
                    query,
                )
                if isinstance(cand, RoutingDecision):
                    routing_decision = cand
            except Exception as e:
                logger.warning("Error running router in streaming service: %s", e)
                routing_decision = None

        decision_action_str: str | None = None
        if routing_decision is not None:
            decision_action_str = (
                extract_routing_action_str(routing_decision.action) or "HYBRID_SEARCH"
            )
            unit_id_str = getattr(routing_decision, "unit_id", None)
            reason_str = getattr(routing_decision, "reason", None)
            extracted_by_str = getattr(routing_decision, "extracted_by", None)

            # Emit routing decision event
            yield format_sse(
                "stage",
                {
                    "stage": "routing_decision",
                    "status": "completed",
                    "routing_action": decision_action_str,
                    "matched_unit_id": unit_id_str,
                    "reason": reason_str,
                    "extracted_by": extracted_by_str,
                    "message": (
                        f"Phân luồng: Tra cứu định danh (Direct Lookup: {unit_id_str})"
                        if decision_action_str == "DIRECT_LOOKUP"
                        else "Phân luồng: Tìm kiếm ngữ nghĩa lai (Hybrid Search)"
                    ),
                },
            )
            await asyncio.sleep(0.01)

            if decision_action_str == "DIRECT_LOOKUP":
                yield format_sse(
                    "stage",
                    {
                        "stage": "retrieval_bypass",
                        "status": "skipped",
                        "routing_action": "DIRECT_LOOKUP",
                        "message": f"Bỏ qua tìm kiếm lai (Đã xác định đích danh tọa độ: {unit_id_str})",
                    },
                )
                await asyncio.sleep(0.01)
                yield format_sse(
                    "stage",
                    {
                        "stage": "graph",
                        "status": "running",
                        "routing_action": "DIRECT_LOOKUP",
                        "matched_unit_id": unit_id_str,
                        "message": f"Đang tra cứu trực tiếp node {unit_id_str} & liên kết chế tài trên Neo4j...",
                    },
                )
            else:
                yield format_sse(
                    "stage",
                    {
                        "stage": "rewriting",
                        "status": "running",
                        "routing_action": "HYBRID_SEARCH",
                        "message": "Đang phân tích ý định và chuẩn hóa thuật ngữ pháp lý...",
                    },
                )
                await asyncio.sleep(0.01)
                yield format_sse(
                    "stage",
                    {
                        "stage": "retrieving",
                        "status": "running",
                        "routing_action": "HYBRID_SEARCH",
                        "message": "Đang tìm kiếm lai (Dense & BM25) và kiểm định đồ thị Neo4j...",
                    },
                )
        else:
            # Fallback if router not initialized or failed
            yield format_sse(
                "stage",
                {
                    "stage": "rewriting",
                    "status": "running",
                    "message": "Đang phân tích ý định và chuẩn hóa thuật ngữ pháp lý...",
                },
            )
            await asyncio.sleep(0.01)
            yield format_sse(
                "stage",
                {
                    "stage": "retrieving",
                    "status": "running",
                    "message": "Đang tìm kiếm lai (Dense & BM25) và kiểm định đồ thị Neo4j...",
                },
            )

        # Execute pipeline core off-thread
        try:
            run_kwargs: dict[str, Any] = {
                "user_query": query,
                "document_id": document_id,
                "top_k": top_k,
            }
            if routing_decision is not None:
                run_kwargs["routing_decision"] = routing_decision

            result: PipelineResult = await asyncio.to_thread(
                self.pipeline.run,
                **run_kwargs,
            )
        except TypeError:
            # Fallback for mock pipelines that don't accept routing_decision kwarg
            result = await asyncio.to_thread(
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
            {
                "stage": "generating",
                "message": "Đang tổng hợp câu trả lời dựa trên căn cứ pháp lý...",
            },
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
        routing_action_str = extract_routing_action_str(result.routing_action)

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
                "routing_action": routing_action_str,
                "matched_unit_id": result.matched_unit_id,
            },
        )
