"""Query Rewriter converting colloquial queries to statutory legal terminology."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal

import requests  # type: ignore[import-untyped]

from src.extraction.key_manager import KeyManager
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver
from src.pipeline.config import PipelineConfig
from src.pipeline.models import RewrittenQuery
from src.pipeline.prompts import REWRITE_JSON_SCHEMA, REWRITE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

KNOWN_DOCUMENT_MAP: dict[str, str] = {
    "118": "118_2025_QH15",
    "151": "151_2024_ND-CP",
    "156": "156_2024_ND-CP",
    "160": "160_2024_ND-CP",
    "165": "165_2024_ND-CP",
    "168": "168_2024_ND-CP",
    "184": "184_2025_ND-CP",
    "236": "236_2026_ND-CP",
    "238": "238_2026_ND-CP",
    "35": "35_2024_QH15",
    "36": "36_2024_QH15",
}


def resolve_canonical_doc_id(doc_ref: str | None) -> str | None:
    """Normalizes document references to canonical IDs in Neo4j."""
    if not doc_ref:
        return None
    cleaned = doc_ref.strip()
    if cleaned in KNOWN_DOCUMENT_MAP.values():
        return cleaned

    match = re.search(r"\b(118|151|156|160|165|168|184|236|238|35|36)\b", cleaned)
    if match:
        num = match.group(1)
        if num in KNOWN_DOCUMENT_MAP:
            return KNOWN_DOCUMENT_MAP[num]

    try:
        resolver = CanonicalIDResolver()
        return resolver.resolve_document(cleaned)
    except Exception:
        return cleaned


def extract_document_intent_and_numbers(
    query: str,
) -> tuple[
    Literal[
        "violation_sanction",
        "document_amendment",
        "general_rule",
        "system_meta_query",
        "out_of_scope",
    ],
    str | None,
    str | None,
]:
    """Deterministically detects document amendment intent and source/target document IDs."""
    q_lower = query.lower()

    # Meta query check
    meta_keywords = [
        "bạn nắm rõ",
        "bạn biết",
        "bạn có",
        "hệ thống có",
        "danh mục luật",
        "danh mục nghị định",
        "các luật mà bạn",
        "các nghị định mà bạn",
        "những văn bản nào",
        "những luật nào",
        "những nghị định nào",
        "tài liệu nào",
        "văn bản mà bạn",
        "hệ thống gồm",
        "cơ sở dữ liệu của bạn",
        "giới thiệu hệ thống",
        "bạn được huấn luyện",
        "danh sách luật",
        "danh sách nghị định",
    ]
    if any(k in q_lower for k in meta_keywords):
        return "system_meta_query", None, None

    is_amendment_query = any(
        k in q_lower
        for k in [
            "sửa đổi",
            "bổ sung",
            "bãi bỏ",
            "thay thế",
            "được sửa",
            "sửa bởi",
            "sua doi",
            "bo sung",
            "thay the",
        ]
    )

    source_doc: str | None = None
    target_doc: str | None = None

    # Pattern: ... được sửa (đổi|bổ sung) bởi [doc]
    m_by = re.search(
        r"(?:được|bi)\s+sửa\s*(?:đổi|bổ\s*sung)?\s*bởi\s+(?:nghị\s*định|nghidinh|nđ|nd|luật|luat)?\s*([0-9]{1,4}(?:/[0-9]{4}/[a-za-z0-9_-]+)?)",
        q_lower,
    )
    if m_by and m_by.group(1):
        source_doc = resolve_canonical_doc_id(m_by.group(1))

    # Pattern: [source] sửa đổi [target]
    m_action = re.search(
        r"(?:nghị\s*định|nghidinh|nđ|nd|luật|luat)?\s*([0-9]{1,4}(?:/[0-9]{4}/[a-za-z0-9_-]+)?)\s+sửa\s*(?:đổi|bổ\s*sung)\s*(?:các\s*quy\s*định|các\s*điều\s*khoản|những\s*gì)?\s*(?:trong|cho|của)?\s*(?:nghị\s*định|nghidinh|nđ|nd|luật|luat)?\s*([0-9]{1,4}(?:/[0-9]{4}/[a-za-z0-9_-]+)?)",
        q_lower,
    )
    if m_action:
        s_cand, t_cand = m_action.group(1), m_action.group(2)
        if s_cand and not source_doc:
            source_doc = resolve_canonical_doc_id(s_cand)
        if t_cand and not target_doc:
            target_doc = resolve_canonical_doc_id(t_cand)

    # General extraction of doc numbers
    doc_nums = re.findall(
        r"(?:nghị\s*định|nghidinh|nđ|nd|luật|luat)\s*([0-9]{1,4}(?:/[0-9]{4}/[a-za-z0-9_-]+)?)",
        q_lower,
    )
    if not doc_nums:
        doc_nums = re.findall(
            r"\b(118|151|156|160|165|168|184|236|238|35|36)\b", q_lower
        )

    if is_amendment_query and len(doc_nums) >= 2:
        if source_doc:
            for d in doc_nums:
                cand = resolve_canonical_doc_id(d)
                if cand != source_doc:
                    target_doc = cand
                    break
        elif not target_doc:
            source_doc = resolve_canonical_doc_id(doc_nums[0])
            target_doc = resolve_canonical_doc_id(doc_nums[1])
    elif is_amendment_query and len(doc_nums) == 1:
        cand = resolve_canonical_doc_id(doc_nums[0])
        if not source_doc and not target_doc:
            if any(w in q_lower for w in ["trong", "của", "bị", "được"]):
                target_doc = cand
            else:
                source_doc = cand

    intent: Literal[
        "violation_sanction", "document_amendment", "general_rule", "system_meta_query"
    ] = (
        "document_amendment"
        if is_amendment_query and (source_doc or target_doc or "điều khoản" in q_lower)
        else "violation_sanction"
    )
    return intent, source_doc, target_doc


def check_bypass_rewrite(query: str) -> tuple[bool, RewrittenQuery | None]:
    """Checks whether LLM query rewrite should be bypassed to avoid semantic drift and unnecessary latency.

    Bypasses when:
    1. The query is a system/meta query asking for known documents or chatbot scope.
    2. The query is already a precise statutory citation/quotation request (e.g. 'Trích toàn bộ điều 1 của ND168').
    """
    clean = query.strip()
    q_lower = clean.lower()

    # 0. Chitchat / Greeting bypass
    greetings = {
        "xin chào",
        "chào bạn",
        "chào em",
        "chào anh",
        "chào chị",
        "hello",
        "hi",
        "bạn là ai",
        "bạn tên gì",
        "bạn làm được gì",
    }
    if q_lower in greetings or any(q_lower == g for g in greetings):
        return True, RewrittenQuery(
            original_query=clean,
            search_query=clean,
            intent="out_of_scope",
            identified_keywords=[],
        )

    # 1. System Meta Query
    det_intent, det_source, det_target = extract_document_intent_and_numbers(clean)
    if det_intent == "system_meta_query":
        return True, RewrittenQuery(
            original_query=clean,
            search_query=clean,
            intent="system_meta_query",
            identified_keywords=["danh mục văn bản", "luật", "nghị định"],
        )

    # 2. Direct Statutory Quote Query (e.g. "Trích toàn bộ điều 1 của ND168")
    is_direct_statutory_quote = bool(
        re.search(
            r"^(?:trích|nội dung|cho tôi biết|xem)?\s*(?:toàn bộ|toàn văn)?\s*"
            r"(?:điều|khoản|điểm)\s+\d+[a-zđ]?\s*"
            r".*(?:nghị\s*định|nđ|nd|luật|luat|\b\d{2,3}/\d{4}/|\b168\b|\b165\b|\b151\b|\b238\b|\b118\b|\b35\b|\b36\b)",
            q_lower,
        )
    )
    is_amendment = any(
        k in q_lower
        for k in ["sửa đổi", "bổ sung", "bãi bỏ", "thay thế", "được sửa", "sửa bởi"]
    )

    if is_direct_statutory_quote and not is_amendment:
        return True, RewrittenQuery(
            original_query=clean,
            search_query=clean,
            rule_query=clean,
            sanction_query=clean,
            intent="general_rule",
            source_doc=det_source,
            target_doc=det_target,
            identified_keywords=["trích dẫn điều khoản"],
        )

    return False, None


def sanitize_rewritten_query_string(
    text: str | None, max_words: int = 30
) -> str | None:
    """Sanitizes query string by collapsing consecutive duplicate words and capping word count."""
    if not text:
        return None
    words = text.strip().split()
    if not words:
        return None
    deduped: list[str] = []
    for w in words:
        if not deduped or w.lower() != deduped[-1].lower():
            deduped.append(w)
    if len(deduped) > max_words:
        deduped = deduped[:max_words]
    return " ".join(deduped)


class QueryRewriter:
    """Converts colloquial user queries into statutory legal terminology."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        key_manager: KeyManager | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or PipelineConfig.from_env()
        self.key_manager = key_manager or KeyManager()
        self.model = self.config.rewrite_model_name
        self.max_retries = self.config.max_retries
        self.session = session or requests.Session()

    def rewrite(self, user_query: str) -> RewrittenQuery:
        """Rewrites a colloquial user query into formal legal search terms.

        If query rewriting is disabled or an error occurs, falls back to the original query.
        """
        clean_query = user_query.strip()
        if not clean_query:
            return RewrittenQuery(
                original_query=clean_query,
                search_query=clean_query,
                identified_keywords=[],
                intent="general_rule",
            )

        det_intent, det_source, det_target = extract_document_intent_and_numbers(
            clean_query
        )

        # Check conditional bypass to eliminate semantic drift and unnecessary latency
        should_bypass, preset_query = check_bypass_rewrite(clean_query)
        if should_bypass and preset_query:
            logger.info(
                "Bypassing query rewrite for query: '%s' (intent: %s)",
                clean_query,
                preset_query.intent,
            )
            return preset_query

        if not self.config.enable_query_rewrite:
            logger.info("Query rewriting disabled via config. Using original query.")
            return RewrittenQuery(
                original_query=clean_query,
                search_query=clean_query,
                identified_keywords=[],
                intent=det_intent,
                source_doc=det_source,
                target_doc=det_target,
            )

        user_content = f'Câu hỏi của người dân: "{clean_query}"'

        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": REWRITE_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": REWRITE_JSON_SCHEMA,
                "temperature": self.config.temperature_rewrite,
                "maxOutputTokens": 1500,
            },
        }

        retries = 0
        while retries < self.max_retries:
            try:
                key = self.key_manager.get_key()
            except Exception as e:
                logger.warning(
                    "Failed to obtain Gemini API key: %s. Falling back to original query.",
                    e,
                )
                return RewrittenQuery(
                    original_query=clean_query,
                    search_query=clean_query,
                    identified_keywords=[],
                    intent=det_intent,
                    source_doc=det_source,
                    target_doc=det_target,
                )

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={key}"

            try:
                resp = self.session.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )

                # Case 1: Rate limit (HTTP 429)
                if resp.status_code == 429:
                    logger.warning(
                        "Gemini API 429 rate limit hit during query rewrite. Rotating key..."
                    )
                    self.key_manager.mark_rate_limited(key)
                    retries += 1
                    continue

                # Case 2: Server errors (500, 502, 503, 504)
                if resp.status_code in (500, 502, 503, 504):
                    retries += 1
                    logger.warning(
                        "Server error %d from Gemini API during rewrite. Retrying...",
                        resp.status_code,
                    )
                    time.sleep(min(retries * 2, 8))
                    continue

                # Case 3: Client errors (400, 403, 404)
                if 400 <= resp.status_code < 500:
                    logger.error(
                        "Client error %d during rewrite: %s",
                        resp.status_code,
                        resp.text,
                    )
                    break

                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    logger.warning(
                        "Empty candidate response from Gemini API for query rewrite."
                    )
                    break

                text_content = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if not text_content:
                    logger.warning("Empty text content in Gemini rewrite candidate.")
                    break

                parsed = json.loads(text_content)
                raw_search = parsed.get("search_query", "").strip() or clean_query
                search_query = (
                    sanitize_rewritten_query_string(raw_search, max_words=30)
                    or clean_query
                )
                rule_query = sanitize_rewritten_query_string(
                    parsed.get("rule_query"), max_words=25
                )
                sanction_query = sanitize_rewritten_query_string(
                    parsed.get("sanction_query"), max_words=25
                )
                keywords = parsed.get("identified_keywords", [])
                if not isinstance(keywords, list):
                    keywords = []

                # Resolve intent & document references
                model_intent = parsed.get("intent")
                intent: Literal[
                    "violation_sanction",
                    "document_amendment",
                    "general_rule",
                    "system_meta_query",
                    "out_of_scope",
                ] = (
                    model_intent
                    if model_intent
                    in (
                        "violation_sanction",
                        "document_amendment",
                        "general_rule",
                        "system_meta_query",
                        "out_of_scope",
                    )
                    else det_intent
                )

                source_doc = (
                    resolve_canonical_doc_id(parsed.get("source_doc")) or det_source
                )
                target_doc = (
                    resolve_canonical_doc_id(parsed.get("target_doc")) or det_target
                )

                # If document amendment detected, ensure intent is set
                if (source_doc or target_doc) and det_intent == "document_amendment":
                    intent = "document_amendment"

                logger.info(
                    "Rewrote query '%s' -> intent: %s | src: %s | tgt: %s | search: '%s'",
                    clean_query,
                    intent,
                    source_doc,
                    target_doc,
                    search_query,
                )
                return RewrittenQuery(
                    original_query=clean_query,
                    search_query=search_query,
                    rule_query=rule_query,
                    sanction_query=sanction_query,
                    identified_keywords=[str(k) for k in keywords],
                    intent=intent,
                    source_doc=source_doc,
                    target_doc=target_doc,
                )

            except (requests.RequestException, json.JSONDecodeError) as req_err:
                retries += 1
                logger.warning(
                    "Error during query rewrite: %s. Retry %d/%d",
                    req_err,
                    retries,
                    self.max_retries,
                )
                time.sleep(min(retries * 2, 8))

        # Fallback when all retries fail
        logger.warning(
            "Query rewriting failed after %d retries. Falling back to original query.",
            self.max_retries,
        )
        return RewrittenQuery(
            original_query=clean_query,
            search_query=clean_query,
            identified_keywords=[],
            intent=det_intent,
            source_doc=det_source,
            target_doc=det_target,
        )
