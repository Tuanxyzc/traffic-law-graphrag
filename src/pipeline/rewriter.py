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

_KNOWN_DOC_KEYS_ALT = "|".join(re.escape(k) for k in KNOWN_DOCUMENT_MAP)
KNOWN_DOC_NUMS_REGEX = re.compile(rf"\b({_KNOWN_DOC_KEYS_ALT})\b")
_KNOWN_DOC_BOUNDED_ALT = "|".join(rf"\b{re.escape(k)}\b" for k in KNOWN_DOCUMENT_MAP)
DIRECT_STATUTORY_QUOTE_REGEX = re.compile(
    r"^(?:trích|nội dung|cho tôi biết|xem)?\s*(?:toàn bộ|toàn văn)?\s*"
    r"(?:điều|khoản|điểm)\s+\d+[a-zđ]?\s*"
    rf".*(?:nghị\s*định|nđ|nd|luật|luat|\b\d{{2,3}}/\d{{4}}/|{_KNOWN_DOC_BOUNDED_ALT})",
    re.IGNORECASE,
)


def resolve_canonical_doc_id(doc_ref: str | None) -> str | None:
    """Normalizes document references to canonical IDs in Neo4j."""
    if not doc_ref:
        return None
    cleaned = doc_ref.strip()
    if cleaned in KNOWN_DOCUMENT_MAP.values():
        return cleaned

    match = KNOWN_DOC_NUMS_REGEX.search(cleaned)
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
        doc_nums = KNOWN_DOC_NUMS_REGEX.findall(q_lower)

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
    if q_lower in greetings:
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
    is_direct_statutory_quote = bool(DIRECT_STATUTORY_QUOTE_REGEX.search(q_lower))
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


COLLOQUIAL_LEGAL_MAPPINGS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:vượt\s+đèn\s+đỏ|vượt\s+đèn\s+vàng|vượt\s+đèn)\b",
            re.IGNORECASE,
        ),
        "không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
    ),
    (
        re.compile(r"\b(?:xe\s+máy|xe\s+mô\s+tô|xe\s+gắn\s+máy)\b", re.IGNORECASE),
        "xe mô tô, xe gắn máy",
    ),
    (
        re.compile(r"\b(?:xe\s+ô\s+tô|ô\s+tô)\b", re.IGNORECASE),
        "xe ô tô",
    ),
    (
        re.compile(
            r"\b(?:uống\s+rượu|uống\s+bia|nồng\s+độ\s+cồn|có\s+cồn|say\s+xỉn)\b",
            re.IGNORECASE,
        ),
        "điều khiển xe trên đường mà trong máu hoặc hơi thở có nồng độ cồn",
    ),
    (
        re.compile(
            r"\b(?:không\s+(?:đội\s+)?mũ\s+bảo\s+hiểm|không\s+nón\s+bảo\s+hiểm)\b",
            re.IGNORECASE,
        ),
        "không đội mũ bảo hiểm cho người đi mô tô, xe máy",
    ),
    (
        re.compile(
            r"\b(?:chạy\s+quá\s+tốc\s+độ|bắn\s+tốc\s+độ|quá\s+tốc\s+độ)\b",
            re.IGNORECASE,
        ),
        "điều khiển xe chạy quá tốc độ quy định",
    ),
    (
        re.compile(
            r"\b(?:đi\s+ngược\s+chiều|chạy\s+ngược\s+chiều)\b",
            re.IGNORECASE,
        ),
        "đi ngược chiều của đường một chiều, đi ngược chiều trên đường có biển Cấm đi ngược chiều",
    ),
    (
        re.compile(r"\b(?:lạng\s+lách|đánh\s+võng)\b", re.IGNORECASE),
        "điều khiển xe lạng lách, đánh võng",
    ),
    (
        re.compile(
            r"\b(?:không\s+xi\s+nhan|quên\s+xi\s+nhan|không\s+bật\s+đèn\s+tín\s+hiệu)\b",
            re.IGNORECASE,
        ),
        "không có báo hiệu bằng đèn trước khi chuyển hướng",
    ),
    (
        re.compile(
            r"\b(?:đi\s+vào\s+đường\s+cấm|chạy\s+vào\s+đường\s+cấm)\b",
            re.IGNORECASE,
        ),
        "đi vào khu vực cấm, đường có biển báo hiệu có nội dung cấm",
    ),
]


def normalize_colloquial_terms(text: str | None) -> str:
    """Normalizes colloquial traffic terms to official statutory terminology."""
    if not text or not isinstance(text, str):
        return ""
    normalized = text
    for pattern, statutory_term in COLLOQUIAL_LEGAL_MAPPINGS:
        normalized = pattern.sub(statutory_term, normalized)
    return normalized


def sanitize_rewritten_query_string(text: Any, max_words: int = 30) -> str | None:
    """Sanitizes query string by collapsing consecutive duplicate words and capping word count."""
    if not text or not isinstance(text, str):
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

        if self.config.rewriter_use_local:
            return self._rewrite_local(clean_query, det_intent, det_source, det_target)
        return self._rewrite_cloud(clean_query, det_intent, det_source, det_target)

    def _parse_rewrite_response(
        self,
        text_content: str | None,
        clean_query: str,
        det_intent: Literal[
            "violation_sanction",
            "document_amendment",
            "general_rule",
            "system_meta_query",
            "out_of_scope",
        ],
        det_source: str | None,
        det_target: str | None,
    ) -> RewrittenQuery:
        """Parses model response text into a typed RewrittenQuery."""
        if not text_content or not isinstance(text_content, str):
            return RewrittenQuery(
                original_query=clean_query,
                search_query=clean_query,
                rule_query=None,
                sanction_query=None,
                identified_keywords=[],
                intent=det_intent,
                source_doc=det_source,
                target_doc=det_target,
            )

        clean_text = text_content.strip()
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL)
        if m:
            clean_text = m.group(1)
        elif "{" in clean_text and "}" in clean_text:
            start = clean_text.find("{")
            end = clean_text.rfind("}") + 1
            clean_text = clean_text[start:end]

        parsed: dict[str, Any] = {}
        try:
            loaded = json.loads(clean_text)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            # Handle potential trailing commas or minor JSON quirks from small local LLMs
            fixed_json = re.sub(r",\s*([\]}])", r"\1", clean_text)
            try:
                loaded = json.loads(fixed_json)
                if isinstance(loaded, dict):
                    parsed = loaded
            except json.JSONDecodeError:
                parsed = {}
                sq_m = re.search(r'"search_query"\s*:\s*"([^"]+)"', clean_text)
                rq_m = re.search(r'"rule_query"\s*:\s*"([^"]+)"', clean_text)
                sanq_m = re.search(r'"sanction_query"\s*:\s*"([^"]+)"', clean_text)
                if sq_m:
                    parsed["search_query"] = sq_m.group(1)
                if rq_m:
                    parsed["rule_query"] = rq_m.group(1)
                if sanq_m:
                    parsed["sanction_query"] = sanq_m.group(1)
                mht_m = re.search(r'"must_have_terms"\s*:\s*\[(.*?)\]', clean_text)
                if mht_m:
                    parsed["must_have_terms"] = [
                        x.strip().strip('"').strip("'")
                        for x in mht_m.group(1).split(",")
                        if x.strip().strip('"').strip("'")
                    ]
                mnht_m = re.search(r'"must_not_have_terms"\s*:\s*\[(.*?)\]', clean_text)
                if mnht_m:
                    parsed["must_not_have_terms"] = [
                        x.strip().strip('"').strip("'")
                        for x in mnht_m.group(1).split(",")
                        if x.strip().strip('"').strip("'")
                    ]
                te_m = re.search(r'"target_entities"\s*:\s*\[(.*?)\]', clean_text)
                if te_m:
                    parsed["target_entities"] = [
                        x.strip().strip('"').strip("'")
                        for x in te_m.group(1).split(",")
                        if x.strip().strip('"').strip("'")
                    ]

        raw_search_val = parsed.get("search_query")
        if raw_search_val and isinstance(raw_search_val, str):
            raw_search = raw_search_val.strip() or clean_query
        else:
            raw_search = clean_query

        search_query = (
            sanitize_rewritten_query_string(raw_search, max_words=30) or clean_query
        )
        rule_query = sanitize_rewritten_query_string(
            parsed.get("rule_query"), max_words=25
        )
        sanction_query = sanitize_rewritten_query_string(
            parsed.get("sanction_query"), max_words=25
        )
        keywords_val = parsed.get("identified_keywords")
        keywords = (
            [str(k).strip() for k in keywords_val if str(k).strip()]
            if isinstance(keywords_val, list)
            else []
        )

        must_have_val = parsed.get("must_have_terms")
        must_have_terms = (
            [str(t).strip() for t in must_have_val if str(t).strip()]
            if isinstance(must_have_val, list)
            else []
        )

        must_not_val = parsed.get("must_not_have_terms")
        must_not_have_terms = (
            [str(t).strip() for t in must_not_val if str(t).strip()]
            if isinstance(must_not_val, list)
            else []
        )

        target_ent_val = parsed.get("target_entities")
        target_entities = (
            [str(e).strip() for e in target_ent_val if str(e).strip()]
            if isinstance(target_ent_val, list)
            else []
        )

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

        source_doc = resolve_canonical_doc_id(parsed.get("source_doc")) or det_source
        target_doc = resolve_canonical_doc_id(parsed.get("target_doc")) or det_target

        if (source_doc or target_doc) and det_intent == "document_amendment":
            intent = "document_amendment"

        logger.info(
            "Rewrote query '%s' -> intent: %s | src: %s | tgt: %s | search: '%s' | must_have: %s | must_not: %s | entities: %s",
            clean_query,
            intent,
            source_doc,
            target_doc,
            search_query,
            must_have_terms,
            must_not_have_terms,
            target_entities,
        )
        return RewrittenQuery(
            original_query=clean_query,
            search_query=search_query,
            rule_query=rule_query,
            sanction_query=sanction_query,
            identified_keywords=keywords,
            must_have_terms=must_have_terms,
            must_not_have_terms=must_not_have_terms,
            target_entities=target_entities,
            intent=intent,
            source_doc=source_doc,
            target_doc=target_doc,
        )

    def _rewrite_local(
        self,
        clean_query: str,
        det_intent: Literal[
            "violation_sanction",
            "document_amendment",
            "general_rule",
            "system_meta_query",
            "out_of_scope",
        ],
        det_source: str | None,
        det_target: str | None,
    ) -> RewrittenQuery:
        """Rewrites query using Localhost LLM via OpenAI-compatible chat completions REST API."""
        endpoint = self.config.rewriter_local_endpoint.rstrip("/")
        url = (
            endpoint
            if endpoint.endswith("/chat/completions")
            else f"{endpoint}/chat/completions"
        )
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.rewriter_local_api_key:
            headers["Authorization"] = f"Bearer {self.config.rewriter_local_api_key}"

        payload: dict[str, Any] = {
            "model": self.config.rewriter_local_model,
            "messages": [
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f'Phân tích và mở rộng câu hỏi sau sang 3 biến thể pháp lý (đúng định dạng JSON):\n"{clean_query}"',
                },
            ],
            "temperature": self.config.rewriter_local_temperature,
        }

        try:
            resp = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.config.rewriter_local_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise ValueError("Empty choices in Local LLM rewrite response")
            first_choice = choices[0] or {}
            message = first_choice.get("message") or {}
            text_content = message.get("content")
            if not text_content or not isinstance(text_content, str):
                raise ValueError("Empty content in Local LLM rewrite choice")
            return self._parse_rewrite_response(
                text_content, clean_query, det_intent, det_source, det_target
            )
        except requests.exceptions.HTTPError as exc:
            err_msg = str(exc)
            if exc.response is not None:
                try:
                    err_json = exc.response.json()
                    if isinstance(err_json, dict) and "error" in err_json:
                        err_msg = f"{exc}: {err_json['error']}"
                except Exception:
                    if exc.response.text:
                        err_msg = f"{exc}: {exc.response.text.strip()}"
            logger.warning(
                "Local LLM query rewrite failed (HTTPError): %s. Falling back to original query.",
                err_msg,
            )
            return RewrittenQuery(
                original_query=clean_query,
                search_query=clean_query,
                rule_query=None,
                sanction_query=None,
                identified_keywords=[],
                intent=det_intent,
                source_doc=det_source,
                target_doc=det_target,
            )
        except Exception as exc:
            logger.warning(
                "Local LLM query rewrite failed: %s. Falling back to original query.",
                exc,
            )
            return RewrittenQuery(
                original_query=clean_query,
                search_query=clean_query,
                rule_query=None,
                sanction_query=None,
                identified_keywords=[],
                intent=det_intent,
                source_doc=det_source,
                target_doc=det_target,
            )

    def _rewrite_gemini(
        self,
        clean_query: str,
        det_intent: Literal[
            "violation_sanction",
            "document_amendment",
            "general_rule",
            "system_meta_query",
            "out_of_scope",
        ],
        det_source: str | None,
        det_target: str | None,
    ) -> RewrittenQuery:
        """Backward-compatible alias for _rewrite_cloud."""
        return self._rewrite_cloud(clean_query, det_intent, det_source, det_target)

    def _rewrite_cloud(
        self,
        clean_query: str,
        det_intent: Literal[
            "violation_sanction",
            "document_amendment",
            "general_rule",
            "system_meta_query",
            "out_of_scope",
        ],
        det_source: str | None,
        det_target: str | None,
    ) -> RewrittenQuery:
        """Rewrites query using multi-provider Cloud LLM (Gemini, Groq, Cerebras, Cohere)."""
        retries = 0
        while retries < self.max_retries:
            try:
                pkey = self.key_manager.get_provider_key(purpose="rewrite")
            except Exception as e:
                logger.warning(
                    "Failed to obtain API key across providers: %s. Falling back to original query.",
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

            provider = pkey.provider
            key = pkey.key
            model = (
                self.config.rewrite_model_name
                if provider == "gemini" and self.config.rewrite_model_name
                else pkey.model
            )
            endpoint = pkey.endpoint.rstrip("/")
            api_type = pkey.api_type

            try:
                if api_type == "gemini":
                    url = f"{endpoint}/models/{model}:generateContent?key={key}"
                    headers: dict[str, str] = {"Content-Type": "application/json"}
                    user_content = f'Câu hỏi của người dân: "{clean_query}"'
                    payload: dict[str, Any] = {
                        "system_instruction": {
                            "parts": [{"text": REWRITE_SYSTEM_PROMPT}]
                        },
                        "contents": [
                            {"role": "user", "parts": [{"text": user_content}]}
                        ],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "responseSchema": REWRITE_JSON_SCHEMA,
                            "temperature": self.config.temperature_rewrite,
                            "maxOutputTokens": 1500,
                        },
                    }
                else:  # "openai" (Groq, Cerebras, Cohere)
                    url = (
                        endpoint
                        if endpoint.endswith("/chat/completions")
                        else f"{endpoint}/chat/completions"
                    )
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                    }
                    openai_user_content = f'Phân tích và mở rộng câu hỏi sau sang 3 biến thể pháp lý (đúng định dạng JSON):\n"{clean_query}"'
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                            {"role": "user", "content": openai_user_content},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": self.config.temperature_rewrite,
                    }

                resp = self.session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )

                # Case 1: Rate limit (HTTP 429)
                if resp.status_code == 429:
                    logger.warning(
                        "Rate limit (HTTP 429) hit during query rewrite for provider '%s'. Rotating key / failing over...",
                        provider,
                    )
                    self.key_manager.mark_rate_limited(key, provider=provider)
                    retries += 1
                    continue

                # Case 2: Server errors (500, 502, 503, 504)
                if resp.status_code in (500, 502, 503, 504):
                    retries += 1
                    logger.warning(
                        "Server error %d from provider '%s' during rewrite. Rotating key with short cooldown...",
                        resp.status_code,
                        provider,
                    )
                    self.key_manager.mark_server_error(
                        key, cooldown_seconds=15.0, provider=provider
                    )
                    time.sleep(min(retries * 1.5, 6))
                    continue

                # Case 3: Client errors (400, 401, 403, 404)
                if 400 <= resp.status_code < 500:
                    logger.error(
                        "Client error %d from provider '%s' during rewrite: %s",
                        resp.status_code,
                        provider,
                        resp.text,
                    )
                    self.key_manager.mark_server_error(
                        key, cooldown_seconds=120.0, provider=provider
                    )
                    retries += 1
                    continue

                resp.raise_for_status()
                data = resp.json()

                if api_type == "gemini":
                    candidates = data.get("candidates", [])
                    if not candidates:
                        logger.warning(
                            "Empty candidate response from Gemini API for query rewrite."
                        )
                        retries += 1
                        continue
                    text_content = (
                        candidates[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                else:  # openai (Groq, Cerebras, Cohere)
                    choices = data.get("choices", [])
                    if not choices:
                        logger.warning(
                            "Empty choices response from provider '%s' for query rewrite.",
                            provider,
                        )
                        retries += 1
                        continue
                    text_content = choices[0].get("message", {}).get("content", "")

                if not text_content:
                    logger.warning(
                        "Empty text content in rewrite candidate from provider '%s'.",
                        provider,
                    )
                    retries += 1
                    continue

                return self._parse_rewrite_response(
                    text_content, clean_query, det_intent, det_source, det_target
                )

            except (requests.RequestException, json.JSONDecodeError) as req_err:
                retries += 1
                logger.warning(
                    "Error during query rewrite with provider '%s': %s. Retry %d/%d",
                    provider,
                    req_err,
                    retries,
                    self.max_retries,
                )
                self.key_manager.mark_server_error(
                    key, cooldown_seconds=15.0, provider=provider
                )
                time.sleep(min(retries * 1.5, 6))

        # Fallback when all retries fail
        logger.warning(
            "Query rewriting failed after %d retries across providers. Falling back to original query.",
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
