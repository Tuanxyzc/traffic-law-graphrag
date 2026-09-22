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
from src.pipeline.rewriter import QueryRewriter, normalize_colloquial_terms
from src.rag.models import RetrievedChunk
from src.rag.retriever import HybridRetriever

logger = logging.getLogger(__name__)


def classify_chunk_vehicle(chunk: RetrievedChunk) -> str | None:
    """Classifies a retrieved chunk into a standardized vehicle entity without hardcoding article numbers.

    Returns:
        One of 'xe_o_to', 'xe_mo_to', 'xe_may_chuyen_dung', 'xe_dap', 'nguoi_di_bo', 'vat_nuoi', or None.
    """
    title = (chunk.metadata.tieu_de_dieu or "").lower()
    text = (chunk.text or "").lower()
    raw_text = (chunk.raw_text or "").lower()
    combined = f"{title} {text} {raw_text}"

    # 1. Specialized construction/agricultural vehicles
    if "máy kéo" in title or "xe máy chuyên dùng" in title:
        return "xe_may_chuyen_dung"
    # 2. Motorcycles / scooters / mopeds
    if "xe mô tô" in title or "xe gắn máy" in title or "mô tô" in title:
        return "xe_mo_to"
    # 3. Cars / automobiles
    if "xe ô tô" in title or "ô tô" in title:
        return "xe_o_to"
    # 4. Bicycles / non-motorized
    if "xe đạp" in title or "xe thô sơ" in title:
        return "xe_dap"
    # 5. Pedestrians
    if "người đi bộ" in title:
        return "nguoi_di_bo"
    # 6. Animal-drawn / leading animals
    if "vật nuôi" in title or "súc vật" in title:
        return "vat_nuoi"

    # Fallback to scanning body text if title does not explicitly mention vehicle category
    if "máy kéo" in combined or "xe máy chuyên dùng" in combined:
        if "xe mô tô" not in combined and "xe gắn máy" not in combined:
            return "xe_may_chuyen_dung"
    if "xe ô tô" in combined or "ô tô" in combined:
        return "xe_o_to"
    if "xe mô tô" in combined or "xe gắn máy" in combined:
        return "xe_mo_to"
    if "xe đạp" in combined or "xe thô sơ" in combined:
        return "xe_dap"
    if "người đi bộ" in combined:
        return "nguoi_di_bo"
    if "vật nuôi" in combined or "súc vật" in combined:
        return "vat_nuoi"

    return None


def apply_retrieval_guard(
    chunks: list[RetrievedChunk],
    must_have_terms: list[str] | None = None,
    must_not_have_terms: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Filters candidate chunks that violate semantic discriminative constraints.

    If must_have_terms are specified and at least one chunk matches, chunks that do NOT contain
    any must-have term BUT DO contain a must-not-have term will be purged.
    If no chunks match must_have_terms, falls back to returning all chunks to avoid empty results.
    """
    if not chunks:
        return []

    clean_must_have = [
        t.strip().lower() for t in (must_have_terms or []) if t.strip()
    ]
    clean_must_not = [
        t.strip().lower() for t in (must_not_have_terms or []) if t.strip()
    ]

    if not clean_must_have and not clean_must_not:
        return chunks

    def chunk_contains_terms(chunk: RetrievedChunk, terms: list[str]) -> bool:
        haystack = f"{chunk.metadata.tieu_de_dieu or ''} {chunk.text or ''} {chunk.raw_text or ''}".lower()
        return any(term in haystack for term in terms)

    matching_must_have = [
        c for c in chunks if chunk_contains_terms(c, clean_must_have)
    ] if clean_must_have else []

    if clean_must_have and matching_must_have:
        # Purge chunks that lack must_have_terms and contain must_not_have_terms
        cleaned_chunks: list[RetrievedChunk] = []
        for c in chunks:
            has_must = chunk_contains_terms(c, clean_must_have)
            has_must_not = chunk_contains_terms(c, clean_must_not) if clean_must_not else False
            if has_must or not has_must_not:
                cleaned_chunks.append(c)
            else:
                logger.debug(
                    "Purged chunk %s due to semantic constraint violation (contains: %s)",
                    c.id,
                    clean_must_not,
                )
        return cleaned_chunks if cleaned_chunks else chunks

    if clean_must_not and not clean_must_have:
        non_violating = [
            c for c in chunks if not chunk_contains_terms(c, clean_must_not)
        ]
        return non_violating if non_violating else chunks

    return chunks


def reciprocal_rank_fusion(
    chunk_lists: list[list[RetrievedChunk]],
    top_k: int = 5,
    rrf_k: int = 60,
    target_entities: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Combines multiple ranked chunk lists using Reciprocal Rank Fusion (RRF) with Diversified Entity Balancing.

    Args:
        chunk_lists: Lists of ranked candidate chunks from multiple queries.
        top_k: Number of candidate chunks to return.
        rrf_k: Smoothing constant for RRF formula.
        target_entities: List of target vehicle entities (e.g. ['xe_o_to', 'xe_mo_to']). When provided,
            guarantees balanced representation by selecting the top-scoring chunk for each target entity first.
    """
    scores: dict[str, float] = {}
    chunks_map: dict[str, RetrievedChunk] = {}

    for ranked_list in chunk_lists:
        for rank, chunk in enumerate(ranked_list):
            chunk_id = chunk.id
            if chunk_id not in chunks_map:
                chunks_map[chunk_id] = chunk
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)

    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    all_sorted_chunks = [chunks_map[cid] for cid in sorted_ids]

    if not target_entities:
        return all_sorted_chunks[:top_k]

    # Diversified Entity Balancing:
    selected_chunks: list[RetrievedChunk] = []
    selected_ids: set[str] = set()

    clean_targets = [e.strip().lower() for e in target_entities if e.strip()]
    # Step 1: Guarantee at least 1 top chunk for each target entity if available in candidates
    for entity in clean_targets:
        for chunk in all_sorted_chunks:
            if chunk.id not in selected_ids:
                veh = classify_chunk_vehicle(chunk)
                if veh == entity:
                    selected_chunks.append(chunk)
                    selected_ids.add(chunk.id)
                    break

    # Step 2: Fill remaining top_k slots with highest-scoring remaining candidates
    for chunk in all_sorted_chunks:
        if len(selected_chunks) >= top_k:
            break
        if chunk.id not in selected_ids:
            selected_chunks.append(chunk)
            selected_ids.add(chunk.id)

    return selected_chunks[:top_k]


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
        if rewritten.intent == "out_of_scope":
            logger.info(
                "Executing out_of_scope routing for non-traffic query: bypassing retrieval and graph hops."
            )
            candidate_chunks = []

        elif rewritten.intent == "system_meta_query":
            logger.info(
                "Executing system_meta_query routing: retrieving full document catalog."
            )
            system_docs = self.validator.get_all_documents()
            evidence_package = self.evidence_builder.build(
                user_query=clean_query,
                rewritten_query=rewritten,
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
                rewritten_query=rewritten,
                answer=generation_res.answer,
                citations=generation_res.citations,
                evidence_package=evidence_package,
                subgraph=evidence_package.subgraph,
                execution_time_ms=elapsed_ms,
                grounding_verified=generation_res.grounding_verified,
                verification_warnings=generation_res.verification_warnings,
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

        else:
            # Multi-Query Retrieval & Reciprocal Rank Fusion (Original + 3 Rewritten Variations)
            queries_to_retrieve: list[str] = []
            seen_queries: set[str] = set()

            candidate_queries = [
                search_query,
                clean_query,
                rewritten.rule_query,
                rewritten.sanction_query,
            ]
            if search_query == clean_query:
                norm_colloquial = normalize_colloquial_terms(clean_query)
                if norm_colloquial and norm_colloquial.lower() != clean_query.lower():
                    candidate_queries.append(norm_colloquial)
            for q in candidate_queries:
                if q:
                    norm = q.strip()
                    if norm and norm.lower() not in seen_queries:
                        seen_queries.add(norm.lower())
                        queries_to_retrieve.append(norm)

            if len(queries_to_retrieve) > 1 and self.config.enable_dual_query:
                logger.info(
                    "Executing Multi-Query RRF Retrieval with %d queries: %s",
                    len(queries_to_retrieve),
                    queries_to_retrieve,
                )
                chunk_lists = []
                for q_str in queries_to_retrieve:
                    ret_res = self.retriever.retrieve(
                        query=q_str,
                        top_k=effective_k,
                        document_id=document_id,
                    )
                    chunk_lists.append(list(ret_res.chunks))
                candidate_chunks = reciprocal_rank_fusion(
                    chunk_lists,
                    top_k=effective_k,
                    target_entities=rewritten.target_entities,
                )
            else:
                single_query = search_query or clean_query
                rag_result = self.retriever.retrieve(
                    query=single_query,
                    top_k=effective_k,
                    document_id=document_id,
                )
                candidate_chunks = list(rag_result.chunks)

            # Apply semantic discriminative retrieval guardrail
            candidate_chunks = apply_retrieval_guard(
                candidate_chunks,
                must_have_terms=rewritten.must_have_terms,
                must_not_have_terms=rewritten.must_not_have_terms,
            )

        logger.info("Retrieved %d candidate chunks from RAG.", len(candidate_chunks))
        for idx, c in enumerate(candidate_chunks, start=1):
            logger.info(
                "  Candidate [%d]: ID=%s | RRF=%.6f | Dense=%s (rank %s) | Sparse=%s (rank %s)",
                idx,
                c.id,
                c.score,
                f"{c.dense_score:.4f}" if c.dense_score is not None else "N/A",
                str(c.dense_rank) if c.dense_rank is not None else "-",
                f"{c.sparse_score:.4f}" if c.sparse_score is not None else "N/A",
                str(c.sparse_rank) if c.sparse_rank is not None else "-",
            )

        # 3. Neo4j Graph Validation & 1-Hop Expansion
        if candidate_chunks:
            unit_ids = [chunk.id for chunk in candidate_chunks]
            validated_provisions = self.validator.validate_provisions(unit_ids)
            logger.info("Validated %d provisions from graph.", len(validated_provisions))
        else:
            validated_provisions = []
            logger.info("Candidate chunks empty, skipping graph validation.")

        # 4. Evidence Package Assembly
        evidence_package = self.evidence_builder.build(
            user_query=clean_query,
            rewritten_query=rewritten,
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
            rewritten_query=rewritten,
            answer=generation_res.answer,
            citations=generation_res.citations,
            evidence_package=evidence_package,
            subgraph=evidence_package.subgraph,
            execution_time_ms=elapsed_ms,
            grounding_verified=generation_res.grounding_verified,
            verification_warnings=generation_res.verification_warnings,
        )

    # Alias query to run for backwards compatibility
    query = run
