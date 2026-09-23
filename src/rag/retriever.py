"""Hybrid Retriever: combines Dense Vector search and Sparse BM25 search via Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
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


def compute_lexical_density(query_text: str, candidate_text: str) -> float:
    """Computes keyword density and overlap ratio between query and candidate text.

    Includes bigram phrase matching, statutory phrase expansions, and noise suppression
    (e.g. prioritizing traffic light chunks over overtaking 'vượt xe' chunks).
    """
    if not query_text or not candidate_text:
        return 0.0
    query_tokens = [
        tok for tok in re.findall(r"\w+", query_text.lower()) if len(tok) > 1
    ]
    if not query_tokens:
        return 0.0

    q_lower = query_text.lower()
    cand_lower = candidate_text.lower()
    unique_query_tokens = set(query_tokens)
    matched_tokens = sum(1 for tok in unique_query_tokens if tok in cand_lower)
    coverage = matched_tokens / len(unique_query_tokens)

    # Term frequency (capped to prevent extreme repetition bias)
    term_freq = sum(cand_lower.count(tok) for tok in unique_query_tokens)
    capped_freq = min(term_freq, 20)

    # 1. Bigram phrase matching
    query_bigrams = [
        f"{query_tokens[i]} {query_tokens[i + 1]}" for i in range(len(query_tokens) - 1)
    ]
    phrase_bonus = sum(2.0 for bg in query_bigrams if bg in cand_lower)

    # 2. Statutory phrase expansion for key traffic concepts
    statutory_expansions = [
        (
            ("đèn đỏ", "đèn tín hiệu", "vượt đèn"),
            ["đèn tín hiệu", "đèn tín hiệu giao thông", "hiệu lệnh của đèn"],
        ),
        (
            ("xe máy", "mô tô"),
            ["xe mô tô", "xe gắn máy", "xe mô tô, xe gắn máy"],
        ),
        (
            ("nồng độ cồn", "uống rượu", "uống bia"),
            ["nồng độ cồn", "trong máu hoặc hơi thở"],
        ),
        (("mũ bảo hiểm",), ["mũ bảo hiểm"]),
        (("tốc độ", "quá tốc độ"), ["quá tốc độ"]),
        (("ngược chiều",), ["ngược chiều"]),
    ]
    for trigger_phrases, target_phrases in statutory_expansions:
        if any(tp in q_lower for tp in trigger_phrases):
            for tgt in target_phrases:
                if tgt in cand_lower:
                    phrase_bonus += 3.0
                    break

    # 3. Noise suppression: query about traffic lights, but candidate is about overtaking ('vượt xe') without 'đèn'
    if (
        any(k in q_lower for k in ["đèn đỏ", "đèn tín hiệu", "vượt đèn"])
        and "vượt xe" in cand_lower
        and "đèn" not in cand_lower
    ):
        phrase_bonus -= 4.0

    # If no tokens and no phrases matched, return 0.0
    if matched_tokens == 0 and phrase_bonus <= 0:
        return 0.0

    score = coverage * 10.0 + capped_freq * 0.1 + phrase_bonus
    return round(max(score, 0.0), 4)


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

    def _query_articles_fulltext(
        self,
        session: Session,
        query_text: str,
        candidate_k: int,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Executes sparse lexical BM25 search over Article nodes using article_fulltext_index."""
        sanitized = sanitize_lucene_query(query_text)
        if not sanitized:
            return []

        query = (
            "CALL db.index.fulltext.queryNodes($index_name, $query_text) "
            "YIELD node, score "
            "WHERE ($doc_id IS NULL OR node.id STARTS WITH $doc_id) "
            "RETURN node.id AS id, node.title AS title, node.content AS content, "
            "       node.number AS number, score AS article_score "
            "LIMIT $k"
        )
        try:
            result = session.run(
                query,
                index_name=self.config.article_fulltext_index_name,
                query_text=sanitized,
                doc_id=document_id,
                k=candidate_k,
            )
            articles: list[dict[str, Any]] = []
            for rank, record in enumerate(result, start=1):
                row = dict(record)
                row["article_rank"] = rank
                articles.append(row)
            return articles
        except Exception as exc:
            logger.warning(
                "Article fulltext query failed (index might not exist yet): %s", exc
            )
            return []

    def _expand_and_filter_article_units(
        self,
        session: Session,
        articles: list[dict[str, Any]],
        query_text: str,
        top_k_per_article: int = 3,
    ) -> list[dict[str, Any]]:
        """Traverses graph from Articles to child SemanticUnits and filters top units per Article."""
        if not articles:
            return []

        article_ids = [a["id"] for a in articles if a.get("id")]
        if not article_ids:
            return []

        query = (
            "UNWIND $article_ids AS art_id "
            "MATCH (ar:Article {id: art_id}) "
            "OPTIONAL MATCH (ar)-[:CONTAINS_CLAUSE*0..1]->(c)-[:CONTAINS_POINT*0..1]->(p) "
            "WHERE c = ar OR c:Clause "
            "OPTIONAL MATCH (su1:SemanticUnit) "
            "WHERE (su1)-[:EXTRACTED_FROM]->(p) OR (su1)-[:EXTRACTED_FROM]->(c) OR su1.id = ar.id "
            "OPTIONAL MATCH (su2:SemanticUnit) "
            "WHERE su2.id = ar.id OR su2.id STARTS WITH (ar.id + '_') "
            "WITH ar, [x IN collect(DISTINCT su1) + collect(DISTINCT su2) WHERE x IS NOT NULL] AS raw_sus "
            "UNWIND raw_sus AS su "
            "WITH ar, su WHERE su IS NOT NULL "
            "RETURN DISTINCT ar.id AS article_id, "
            "       su.id AS id, su.text AS text, su.raw_text AS raw_text, "
            "       su.document_id AS document_id, su.dieu AS dieu, su.khoan AS khoan, su.diem AS diem, "
            "       su.tieu_de_dieu AS tieu_de_dieu, su.chuong AS chuong, su.tieu_de_chuong AS tieu_de_chuong, "
            "       su.level AS level, su.hieu_luc_tu AS hieu_luc_tu"
        )
        try:
            result = session.run(query, article_ids=article_ids)
            units_by_article: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for record in result:
                art_id = record["article_id"]
                row = dict(record)
                row.pop("article_id", None)
                units_by_article[art_id].append(row)
        except Exception as exc:
            logger.error("Graph traversal expansion query failed: %s", exc)
            return []

        selected_units: list[dict[str, Any]] = []
        seen_unit_ids: set[str] = set()

        for article in articles:
            art_id = article["id"]
            child_units = units_by_article.get(art_id, [])
            if not child_units:
                continue

            # Deduplicate units within the same article
            unique_child_units: list[dict[str, Any]] = []
            local_seen: set[str] = set()
            for u in child_units:
                if u["id"] not in local_seen:
                    local_seen.add(u["id"])
                    unique_child_units.append(u)

            # Score each child unit internally against query_text
            for u in unique_child_units:
                content_to_score = (
                    f"{u.get('tieu_de_dieu') or ''} "
                    f"{u.get('text') or ''} "
                    f"{u.get('raw_text') or ''}"
                )
                u["internal_score"] = compute_lexical_density(
                    query_text, content_to_score
                )

            # Sort child units by internal_score descending
            unique_child_units.sort(
                key=lambda x: float(x.get("internal_score", 0.0)),
                reverse=True,
            )

            # Pick Top N units for this Article
            top_units = unique_child_units[:top_k_per_article]

            for u in top_units:
                u_id = u["id"]
                if u_id not in seen_unit_ids:
                    seen_unit_ids.add(u_id)
                    u["sparse_score"] = article.get("article_score")
                    selected_units.append(u)

        # Assign global sequential sparse_rank (1, 2, ...) preserving Article ranking and internal score
        for rank, u in enumerate(selected_units, start=1):
            u["sparse_rank"] = rank

        return selected_units

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
        """Performs hierarchical hybrid retrieval for a query string.

        1. Vector search over SemanticUnit nodes (10-20 candidates).
        2. Layer 1 similarity threshold check (early exit if off-topic).
        3. Article fulltext search (Top Articles) + graph traversal to child SemanticUnits.
           Filters Top units per Article by keyword density, inherits rank.
           Falls back to direct SemanticUnit fulltext if no Articles match.
        4. Reciprocal Rank Fusion (RRF) & Dynamic-K pruning to return Top chunks.
        """
        start_time = time.perf_counter()
        k = top_k or self.config.default_top_k
        cand_k_vector = max(self.config.top_k_vector, self.config.min_candidate_k)
        cand_k_article = self.config.top_k_article

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
                candidate_k=cand_k_vector,
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

            # 2b. Hierarchical BM25 Search:
            # 1) Search Top Articles via article_fulltext_index
            article_results = self._query_articles_fulltext(
                session=session,
                query_text=query,
                candidate_k=cand_k_article,
                document_id=document_id,
            )

            # 2) Graph Traversal: Expand Article -> child SemanticUnits, filter Top 2-3 per Article
            if article_results:
                sparse_results = self._expand_and_filter_article_units(
                    session=session,
                    articles=article_results,
                    query_text=query,
                    top_k_per_article=self.config.top_k_semantic_per_article,
                )
            else:
                # Fallback to direct semantic unit fulltext if article fulltext index returned nothing
                sparse_results = self._query_fulltext(
                    session=session,
                    query_text=query,
                    candidate_k=cand_k_vector,
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
