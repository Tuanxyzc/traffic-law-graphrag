"""Hybrid Retriever: combines Dense Vector search and Sparse BM25 search via Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from neo4j import Session

from src.graph.neo4j.connection import Neo4jClient
from src.rag.config import RAGConfig
from src.rag.embedding import EmbeddingManager
from src.rag.models import ChunkMetadata, RetrievalResult, RetrievedChunk

logger = logging.getLogger(__name__)

# Reserved Lucene characters that must be escaped or cleaned for full-text search
LUCENE_SPECIAL_CHARS_PATTERN = re.compile(r"([\+\-\&\|\!\(\)\{\}\[\]\^\"~\*\?\:\\/])")


def sanitize_lucene_query(query: str, max_terms: int = 30) -> str:
    """Sanitizes user queries for safe execution in Neo4j Lucene full-text indexes.

    Escapes Lucene special characters with backslashes so syntax errors are avoided,
    and caps the number of terms to avoid Lucene TooManyClauses (maxClauseCount=1024).
    """
    if not query or not query.strip():
        return ""
    words = query.strip().split()
    if len(words) > max_terms:
        words = words[:max_terms]
    truncated_query = " ".join(words)
    sanitized = LUCENE_SPECIAL_CHARS_PATTERN.sub(r"\\\1", truncated_query)
    return sanitized


class HybridRetriever:
    """Orchestrates hybrid dense vector and sparse fulltext search over legal semantic units."""

    def __init__(
        self,
        client: Neo4jClient | None = None,
        embedding_manager: EmbeddingManager | None = None,
        config: RAGConfig | None = None,
    ) -> None:
        self.config = config or RAGConfig()
        self.client = client
        self.embedding_manager = embedding_manager or EmbeddingManager(
            config=self.config
        )

    def _query_vector(
        self,
        session: Session,
        query_vector: list[float],
        candidate_k: int,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Executes dense vector search using Neo4j Vector Index."""
        query = (
            "CALL db.index.vector.queryNodes($index_name, $k, $query_vector) "
            "YIELD node, score "
            "WHERE ($doc_id IS NULL OR node.document_id = $doc_id) "
            "RETURN node.id AS id, node.text AS text, node.raw_text AS raw_text, node.document_id AS document_id, "
            "       node.dieu AS dieu, node.khoan AS khoan, node.diem AS diem, "
            "       node.tieu_de_dieu AS tieu_de_dieu, node.chuong AS chuong, "
            "       node.tieu_de_chuong AS tieu_de_chuong, node.level AS level, "
            "       node.hieu_luc_tu AS hieu_luc_tu, score AS dense_score"
        )
        try:
            result = session.run(
                query,
                index_name=self.config.vector_index_name,
                k=candidate_k,
                query_vector=query_vector,
                doc_id=document_id,
            )
            records: list[dict[str, Any]] = []
            for record in result:
                row = dict(record)
                if row.get("dense_score") is not None:
                    # Neo4j cosine similarity score is normalized as (1 + cosine) / 2
                    # Convert back to standard cosine similarity range [-1.0, 1.0]
                    row["dense_score"] = round(2.0 * float(row["dense_score"]) - 1.0, 4)
                records.append(row)
            return records
        except Exception as exc:
            logger.error("Vector index query failed: %s", exc)
            return []

    def _query_fulltext(
        self,
        session: Session,
        query_text: str,
        candidate_k: int,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Executes sparse lexical BM25 search using Neo4j Full-Text Index."""
        sanitized = sanitize_lucene_query(query_text)
        if not sanitized:
            return []

        query = (
            "CALL db.index.fulltext.queryNodes($index_name, $query_text) "
            "YIELD node, score "
            "WHERE ($doc_id IS NULL OR node.document_id = $doc_id) "
            "RETURN node.id AS id, node.text AS text, node.raw_text AS raw_text, node.document_id AS document_id, "
            "       node.dieu AS dieu, node.khoan AS khoan, node.diem AS diem, "
            "       node.tieu_de_dieu AS tieu_de_dieu, node.chuong AS chuong, "
            "       node.tieu_de_chuong AS tieu_de_chuong, node.level AS level, "
            "       node.hieu_luc_tu AS hieu_luc_tu, score AS sparse_score "
            "LIMIT $k"
        )
        try:
            result = session.run(
                query,
                index_name=self.config.fulltext_index_name,
                query_text=sanitized,
                doc_id=document_id,
                k=candidate_k,
            )
            return [dict(record) for record in result]
        except Exception as exc:
            logger.error("Fulltext index query failed: %s", exc)
            return []

    def _fuse_rrf(
        self,
        dense_results: list[dict[str, Any]],
        sparse_results: list[dict[str, Any]],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Merges and ranks candidate items using Reciprocal Rank Fusion (RRF)."""
        # Layer 1: Floor Similarity Threshold check on Top-1 dense result
        if dense_results:
            top_1_dense = dense_results[0].get("dense_score")
            if (
                top_1_dense is not None
                and top_1_dense < self.config.min_similarity_threshold
            ):
                logger.info(
                    "Top-1 dense score %.4f is below floor threshold %.4f. Discarding all candidate chunks.",
                    top_1_dense,
                    self.config.min_similarity_threshold,
                )
                return []

        k_const = self.config.rrf_k
        w_dense = self.config.dense_weight
        w_sparse = self.config.sparse_weight

        # candidate_map: id -> {
        #   "item": dict, "rrf": float,
        #   "dense_rank": int|None, "dense_score": float|None,
        #   "sparse_rank": int|None, "sparse_score": float|None
        # }
        candidates: dict[str, dict[str, Any]] = {}

        # 1. Process Dense Results (1-based rank)
        for rank, item in enumerate(dense_results, start=1):
            unit_id = item["id"]
            if unit_id not in candidates:
                candidates[unit_id] = {
                    "item": item,
                    "rrf": 0.0,
                    "dense_rank": rank,
                    "dense_score": item.get("dense_score"),
                    "sparse_rank": None,
                    "sparse_score": None,
                }
            candidates[unit_id]["rrf"] += w_dense / (k_const + rank)

        # 2. Process Sparse Results (1-based rank)
        for rank, item in enumerate(sparse_results, start=1):
            unit_id = item["id"]
            if unit_id not in candidates:
                candidates[unit_id] = {
                    "item": item,
                    "rrf": 0.0,
                    "dense_rank": None,
                    "dense_score": None,
                    "sparse_rank": rank,
                    "sparse_score": item.get("sparse_score"),
                }
            else:
                candidates[unit_id]["sparse_rank"] = rank
                candidates[unit_id]["sparse_score"] = item.get("sparse_score")
            candidates[unit_id]["rrf"] += w_sparse / (k_const + rank)

        # 3. Sort candidates by RRF score descending
        sorted_candidates = sorted(
            candidates.values(),
            key=lambda x: x["rrf"],
            reverse=True,
        )

        # Layer 2: Dynamic-K / Relative Drop-off Pruning
        if self.config.enable_dynamic_k and dense_results:
            top_1_dense = dense_results[0].get("dense_score")
            if top_1_dense is not None:
                min_allowed_dense = max(
                    top_1_dense * self.config.relative_dropoff_ratio,
                    top_1_dense - self.config.max_score_gap,
                )
                filtered_candidates: list[dict[str, Any]] = []
                for idx, c in enumerate(sorted_candidates[:top_k]):
                    if idx == 0:
                        # Always keep the top candidate (minimum 1 chunk)
                        filtered_candidates.append(c)
                        continue
                    c_dense = c.get("dense_score")
                    if c_dense is None or c_dense >= min_allowed_dense:
                        filtered_candidates.append(c)
                    else:
                        logger.debug(
                            "Pruning candidate %s: dense_score %s < min_allowed_dense %.4f",
                            c["item"].get("id"),
                            c_dense,
                            min_allowed_dense,
                        )
                sorted_candidates = filtered_candidates
            else:
                sorted_candidates = sorted_candidates[:top_k]
        else:
            sorted_candidates = sorted_candidates[:top_k]

        # 4. Build Typed RetrievedChunk instances
        retrieved_chunks: list[RetrievedChunk] = []
        for c in sorted_candidates:
            raw = c["item"]
            metadata = ChunkMetadata(
                document_id=raw.get("document_id", ""),
                dieu=str(raw.get("dieu", "")),
                khoan=str(raw["khoan"]) if raw.get("khoan") else None,
                diem=str(raw["diem"]) if raw.get("diem") else None,
                tieu_de_dieu=raw.get("tieu_de_dieu"),
                chuong=raw.get("chuong"),
                tieu_de_chuong=raw.get("tieu_de_chuong"),
                level=int(raw.get("level", 4)),
                hieu_luc_tu=raw.get("hieu_luc_tu"),
            )
            retrieved_chunks.append(
                RetrievedChunk(
                    id=raw["id"],
                    text=raw["text"],
                    raw_text=raw.get("raw_text"),
                    score=round(c["rrf"], 6),
                    dense_score=round(c["dense_score"], 4)
                    if c["dense_score"] is not None
                    else None,
                    dense_rank=c["dense_rank"],
                    sparse_score=round(c["sparse_score"], 4)
                    if c["sparse_score"] is not None
                    else None,
                    sparse_rank=c["sparse_rank"],
                    metadata=metadata,
                )
            )

        return retrieved_chunks

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        document_id: str | None = None,
    ) -> RetrievalResult:
        """Performs full hybrid retrieval for a query string."""
        start_time = time.perf_counter()
        k = top_k or self.config.default_top_k
        candidate_k = max(k * 3, self.config.min_candidate_k)

        if not query or not query.strip():
            return RetrievalResult(
                query=query,
                top_k=k,
                chunks=[],
                execution_time_ms=0.0,
            )

        # 1. Embed query
        query_vector = self.embedding_manager.embed_query(query)

        # 2. Execute dual search in Neo4j
        client = self.client or Neo4jClient()
        with client.session() as session:
            dense_results = self._query_vector(
                session=session,
                query_vector=query_vector,
                candidate_k=candidate_k,
                document_id=document_id,
            )

            # Layer 1 Early Exit: If Top-1 dense similarity is below floor threshold,
            # skip fulltext search and return empty chunks immediately.
            if dense_results:
                top_1_dense = dense_results[0].get("dense_score")
                if (
                    top_1_dense is not None
                    and top_1_dense < self.config.min_similarity_threshold
                ):
                    logger.info(
                        "Top-1 dense score %.4f below floor threshold %.4f for query '%s'. Early exiting with 0 chunks.",
                        top_1_dense,
                        self.config.min_similarity_threshold,
                        query,
                    )
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                    return RetrievalResult(
                        query=query,
                        top_k=k,
                        chunks=[],
                        execution_time_ms=elapsed_ms,
                    )

            sparse_results = self._query_fulltext(
                session=session,
                query_text=query,
                candidate_k=candidate_k,
                document_id=document_id,
            )

        # 3. Fuse results with RRF
        chunks = self._fuse_rrf(dense_results, sparse_results, top_k=k)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return RetrievalResult(
            query=query,
            top_k=k,
            chunks=chunks,
            execution_time_ms=elapsed_ms,
        )
