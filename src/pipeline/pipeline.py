"""End-to-End GraphRAG Pipeline orchestrator linking Rewriter, RAG, Neo4j, Evidence, and LLM."""

from __future__ import annotations

import logging
import time

from src.extraction.key_manager import KeyManager
from src.pipeline.config import PipelineConfig
from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.generator import AnswerGenerator
from src.pipeline.graph_validator import GraphValidator
from src.pipeline.models import DocumentAmendmentItem, PipelineResult
from src.pipeline.rewriter import QueryRewriter
from src.rag.models import RetrievedChunk
from src.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    chunk_lists: list[list[RetrievedChunk]],
    top_k: int = 5,
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Combines multiple ranked chunk lists using Reciprocal Rank Fusion (RRF)."""
    scores: dict[str, float] = {}
    chunks_map: dict[str, RetrievedChunk] = {}

    for ranked_list in chunk_lists:
        for rank, chunk in enumerate(ranked_list):
            chunk_id = chunk.id
            if chunk_id not in chunks_map:
                chunks_map[chunk_id] = chunk
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)

    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    return [chunks_map[cid] for cid in sorted_ids[:top_k]]


class GraphRAGPipeline:
    """Orchestrates colloquial query rewriting, hybrid retrieval, graph validation, evidence packaging, and answer generation."""

    def __init__(
        self,
        rewriter: QueryRewriter | None = None,
        retriever: HybridRetriever | None = None,
        validator: GraphValidator | None = None,
        evidence_builder: EvidenceBuilder | None = None,
        generator: AnswerGenerator | None = None,
        config: PipelineConfig | None = None,
        key_manager: KeyManager | None = None,
    ) -> None:
        self.config = config or PipelineConfig.from_env()
        self.key_manager = key_manager or KeyManager()
        self.rewriter = rewriter or QueryRewriter(
            config=self.config, key_manager=self.key_manager
        )
        self.retriever = retriever or HybridRetriever()
        self.validator = validator or GraphValidator(config=self.config)
        self.evidence_builder = evidence_builder or EvidenceBuilder(config=self.config)
        self.generator = generator or AnswerGenerator(
            config=self.config, key_manager=self.key_manager
        )

    def run(
        self,
        user_query: str,
        document_id: str | None = None,
        top_k: int | None = None,
    ) -> PipelineResult:
        """Executes the complete GraphRAG pipeline from citizen query to verified legal answer.

        Args:
            user_query: Natural colloquial question from citizen.
            document_id: Optional document ID to restrict retrieval.
            top_k: Candidate retrieval chunk count override.

        Returns:
            PipelineResult containing answer, citations, evidence, and timings.
        """
        start_time = time.perf_counter()
        clean_query = user_query.strip()
        logger.info("Starting GraphRAG pipeline for query: '%s'", clean_query)

        # 1. Colloquial Query Rewriting with Intent Decomposition
        rewritten = self.rewriter.rewrite(clean_query)
        search_query = rewritten.search_query
        logger.info(
            "Search query after rewrite: '%s' (intent: %s)",
            search_query,
            rewritten.intent,
        )

        effective_k = top_k or self.config.top_k
        doc_amendments: list[DocumentAmendmentItem] = []
        candidate_chunks: list[RetrievedChunk] = []

        # 2. Smart Retrieval & Intent Routing
        if rewritten.intent == "system_meta_query":
            logger.info(
                "Executing system_meta_query routing: retrieving full document catalog."
            )
            system_docs = self.validator.get_all_documents()
            evidence_package = self.evidence_builder.build(
                user_query=clean_query,
                rewritten_query=search_query,
                retrieved_chunks=[],
                validated_provisions=[],
                system_documents=system_docs,
            )
            generation_res = self.generator.generate(evidence_package)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            logger.info(
                "GraphRAG pipeline completed system_meta_query in %.2fms.", elapsed_ms
            )
            return PipelineResult(
                user_query=clean_query,
                rewritten_query=search_query,
                answer=generation_res.answer,
                citations=generation_res.citations,
                evidence_package=evidence_package,
                subgraph=evidence_package.subgraph,
                execution_time_ms=elapsed_ms,
            )

        elif rewritten.intent == "document_amendment" and (
            rewritten.source_doc or rewritten.target_doc
        ):
            doc_a = rewritten.source_doc or rewritten.target_doc or ""
            doc_b = rewritten.target_doc if doc_a != rewritten.target_doc else None
            doc_amendments = self.validator.find_document_amendments(doc_a, doc_b)
            logger.info(
                "Retrieved %d document amendments from Neo4j graph traversal.",
                len(doc_amendments),
            )

            # Supplementary candidate chunk retrieval preserving full document query
            rag_result = self.retriever.retrieve(
                query=search_query,
                top_k=effective_k,
                document_id=document_id,
            )
            candidate_chunks = list(rag_result.chunks)

        elif (
            rewritten.rule_query
            and rewritten.sanction_query
            and rewritten.rule_query != rewritten.sanction_query
        ):
            k_rule = max(2, effective_k // 2)
            k_sanction = max(3, effective_k - k_rule + 1)
            logger.info(
                "Executing multi-query retrieval with RRF: rule_k=%d, sanction_k=%d",
                k_rule,
                k_sanction,
            )

            rule_res = self.retriever.retrieve(
                query=rewritten.rule_query,
                top_k=k_rule,
                document_id=document_id,
            )
            sanction_res = self.retriever.retrieve(
                query=rewritten.sanction_query,
                top_k=k_sanction,
                document_id=document_id,
            )
            candidate_chunks = reciprocal_rank_fusion(
                [list(sanction_res.chunks), list(rule_res.chunks)],
                top_k=effective_k,
            )

        else:
            # Dual-Query RRF Retrieval: Fuse rewritten query and original citizen query
            if (
                self.config.enable_dual_query
                and clean_query.lower() != search_query.lower()
            ):
                logger.info(
                    "Executing Dual-Query RRF: '%s' <-> '%s'", clean_query, search_query
                )
                rag_res_rw = self.retriever.retrieve(
                    query=search_query, top_k=effective_k, document_id=document_id
                )
                rag_res_orig = self.retriever.retrieve(
                    query=clean_query, top_k=effective_k, document_id=document_id
                )
                candidate_chunks = reciprocal_rank_fusion(
                    [list(rag_res_rw.chunks), list(rag_res_orig.chunks)],
                    top_k=effective_k,
                )
            else:
                rag_result = self.retriever.retrieve(
                    query=search_query,
                    top_k=effective_k,
                    document_id=document_id,
                )
                candidate_chunks = list(rag_result.chunks)

        logger.info("Retrieved %d candidate chunks from RAG.", len(candidate_chunks))

        # 3. Neo4j Graph Validation & 1-Hop Expansion
        unit_ids = [chunk.id for chunk in candidate_chunks]
        validated_provisions = self.validator.validate_provisions(unit_ids)
        logger.info("Validated %d provisions from graph.", len(validated_provisions))

        # 4. Evidence Package Assembly
        evidence_package = self.evidence_builder.build(
            user_query=clean_query,
            rewritten_query=search_query,
            retrieved_chunks=candidate_chunks,
            validated_provisions=validated_provisions,
            document_amendments=doc_amendments,
        )

        # 5. Grounded LLM Generation
        generation_res = self.generator.generate(evidence_package)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        logger.info("GraphRAG pipeline completed in %.2fms.", elapsed_ms)

        return PipelineResult(
            user_query=clean_query,
            rewritten_query=search_query,
            answer=generation_res.answer,
            citations=generation_res.citations,
            evidence_package=evidence_package,
            subgraph=evidence_package.subgraph,
            execution_time_ms=elapsed_ms,
        )

    # Alias query to run for backwards compatibility
    query = run
