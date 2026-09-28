"""Query Router & Entity Parser for JurisGraph-VN.

Implements a high-speed, universal MCP-compliant 2-tier architecture:
- Tier 1: Deterministic Fast Path (Regex & Vietnamese word parser, < 5ms).
  Strict Zero-Hallucination: Requires BOTH explicit statutory coordinates AND explicit document identifier.
  Reuses existing Canonical ID Resolver and graph identity constructors.
- Tier 2: Multi-Provider LLM Tool Call Fallback (Gemini, Groq, Cerebras, Cohere) with standard MCP Tool Schema.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests  # type: ignore[import-untyped]

from src.extraction.key_manager import KeyManager
from src.graph.identity import make_article_id, make_clause_id, make_point_id
from src.pipeline.config import PipelineConfig
from src.pipeline.models import RoutingAction, RoutingDecision
from src.pipeline.prompts import (
    MCP_TOOL_LOOKUP_LEGAL_PROVISION,
    ROUTER_SYSTEM_PROMPT,
    get_gemini_tool_declaration,
    get_openai_tool_schema,
)
from src.pipeline.rewriter import KNOWN_DOCUMENT_MAP, resolve_canonical_doc_id

logger = logging.getLogger(__name__)

# Vietnamese number word lookup
VIETNAMESE_DIGITS: dict[str, int] = {
    "không": 0,
    "một": 1,
    "mốt": 1,
    "nhất": 1,
    "hai": 2,
    "ba": 3,
    "bốn": 4,
    "tư": 4,
    "năm": 5,
    "lăm": 5,
    "sáu": 6,
    "bảy": 7,
    "tám": 8,
    "chín": 9,
}

VIETNAMESE_TENS: dict[str, int] = {
    "mười": 10,
    "hai mươi": 20,
    "ba mươi": 30,
    "bốn mươi": 40,
    "năm mươi": 50,
    "sáu mươi": 60,
    "bảy mươi": 70,
    "tám mươi": 80,
    "chín mươi": 90,
}

# Regex to detect when citizen is asking for article number based on offense (anti-hallucination)
ASKING_FOR_ARTICLE_REGEX = re.compile(
    r"\b(?:điều\s*(?:nào|mấy|gì|bao\s*nhiêu)|"
    r"quy\s*định\s*(?:ở|tại|trong)?\s*điều\s*(?:nào|mấy|gì|bao\s*nhiêu)|"
    r"nằm\s*ở\s*điều\s*(?:nào|mấy|gì|bao\s*nhiêu)|"
    r"là\s*điều\s*(?:mấy|nào|bao\s*nhiêu))\b",
    re.IGNORECASE,
)

# Textual document alias mapping to numbers
TEXTUAL_DOC_NAME_MAPPINGS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:luật\s+trật\s+tự(?:\s+an\s+toàn\s+giao\s+thông)?|luật\s+ttatgtdb)\b",
            re.IGNORECASE,
        ),
        "36",
    ),
    (
        re.compile(r"\b(?:luật\s+đường\s+bộ)\b", re.IGNORECASE),
        "35",
    ),
    (
        re.compile(r"\b(?:luật\s+sửa\s+đổi)\b", re.IGNORECASE),
        "118",
    ),
    (
        re.compile(
            r"\b(?:nghị\s*định\s+một\s+trăm\s+sáu\s+mươi\s+tám)\b", re.IGNORECASE
        ),
        "168",
    ),
    (
        re.compile(r"\b(?:thông\s*tư\s*72|tt\s*72)\b", re.IGNORECASE),
        "72",
    ),
]


def parse_vietnamese_number_string(text: str) -> str | None:
    """Parses an Arabic integer or Vietnamese word number into a clean digit string."""
    clean = text.strip().lower()
    if clean.isdigit():
        return str(int(clean))

    # Single digits
    if clean in VIETNAMESE_DIGITS:
        return str(VIETNAMESE_DIGITS[clean])
    if clean == "mười":
        return "10"

    # Compound numbers e.g. "mười một" -> 11, "hai mươi mốt" -> 21
    tokens = clean.split()
    if len(tokens) == 2:
        first, second = tokens[0], tokens[1]
        if first == "mười" and second in VIETNAMESE_DIGITS:
            return str(10 + VIETNAMESE_DIGITS[second])
        if f"{first} mươi" in VIETNAMESE_TENS and second in VIETNAMESE_DIGITS:
            return str(VIETNAMESE_TENS[f"{first} mươi"] + VIETNAMESE_DIGITS[second])

    if len(tokens) == 3 and tokens[1] == "mươi":
        tens_key = f"{tokens[0]} mươi"
        if tens_key in VIETNAMESE_TENS and tokens[2] in VIETNAMESE_DIGITS:
            return str(VIETNAMESE_TENS[tens_key] + VIETNAMESE_DIGITS[tokens[2]])

    return None


class QueryRouter:
    """Universal MCP-Compliant Hybrid 2-Tier Query Router & Entity Parser for JurisGraph-VN."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        key_manager: KeyManager | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or PipelineConfig.from_env()
        self.key_manager = key_manager or KeyManager()
        self.session = session or requests.Session()
        self.max_retries = max(1, self.config.max_retries)

    def route(self, user_query: str) -> RoutingDecision:
        """Analyzes citizen query and decides routing between DIRECT_LOOKUP and HYBRID_SEARCH.

        Args:
            user_query: Raw natural question from user.

        Returns:
            RoutingDecision containing action, canonical unit_id (if DIRECT_LOOKUP),
            cleaned query, reason, and extraction tier.
        """
        clean_query = user_query.strip()
        if not clean_query:
            return RoutingDecision(
                action=RoutingAction.HYBRID_SEARCH,
                query="",
                reason="Câu hỏi rỗng, mặc định chuyển qua tìm kiếm ngữ nghĩa.",
                extracted_by="tier1_regex",
            )

        # Tier 1: Deterministic Fast Path (Regex & Rule Engine)
        tier1_decision = self._parse_tier1_deterministic(clean_query)
        if tier1_decision is not None:
            logger.info(
                "QueryRouter Tier 1 classified: action=%s, unit_id=%s, reason='%s'",
                tier1_decision.action.value,
                tier1_decision.unit_id,
                tier1_decision.reason,
            )
            return tier1_decision

        # Tier 2: Multi-Provider LLM Tool Call Fallback
        logger.info(
            "QueryRouter falling back to Tier 2 (Multi-Provider LLM Tool Calling) for: '%s'",
            clean_query,
        )
        tier2_decision = self._route_tier2_multi_provider(clean_query)
        logger.info(
            "QueryRouter Tier 2 classified: action=%s, unit_id=%s, reason='%s'",
            tier2_decision.action.value,
            tier2_decision.unit_id,
            tier2_decision.reason,
        )
        return tier2_decision

    def _parse_tier1_deterministic(self, user_query: str) -> RoutingDecision | None:
        """Executes Tier 1 deterministic parsing using regex, vocabulary, and existing ID resolvers.

        Enforces strict Zero-Hallucination:
        - If query asks for article number based on offense -> HYBRID_SEARCH.
        - If query has coordinates but lacks explicit document name/number -> HYBRID_SEARCH.
        - If query has both coordinates and document -> DIRECT_LOOKUP.
        - If query has neither -> HYBRID_SEARCH.
        """
        q_lower = user_query.lower()

        # 1. Anti-Hallucination Guard: Citizen asks what article governs an offense
        if ASKING_FOR_ARTICLE_REGEX.search(q_lower):
            return RoutingDecision(
                action=RoutingAction.HYBRID_SEARCH,
                query=user_query,
                reason="Người dùng đang tìm số Điều/Khoản dựa trên hành vi, bắt buộc phải dùng Hybrid Search để truy xuất.",
                extracted_by="tier1_regex",
            )

        # 2. Extract Document Alias & Canonical ID
        doc_id = self._extract_canonical_document(q_lower)

        # 3. Extract Coordinates (Article, Clause, Point)
        point_letter, clause_num, article_num = self._extract_coordinates(q_lower)

        has_coordinates = bool(article_num or clause_num or point_letter)

        # Case A: No coordinates found at all -> Semantic search
        if not has_coordinates:
            return RoutingDecision(
                action=RoutingAction.HYBRID_SEARCH,
                query=user_query,
                reason="Câu hỏi tìm kiếm ngữ nghĩa/hành vi, không có số hiệu điều khoản cụ thể.",
                extracted_by="tier1_regex",
            )

        # Case B: Has coordinates, but NO valid document identifier was found
        # (Strict zero-hallucination: do NOT default to 168 or any doc)
        if not doc_id:
            return RoutingDecision(
                action=RoutingAction.HYBRID_SEARCH,
                query=user_query,
                reason="Có số hiệu điều khoản nhưng thiếu tên văn bản pháp luật, chuyển sang Hybrid Search để tránh đoán mò.",
                extracted_by="tier1_regex",
            )

        # Case C: Has BOTH coordinates AND explicit document
        # Assemble unit ID using existing canonical functions from src.graph.identity
        if not article_num:
            # If clause or point exists without an article number, cannot form a canonical unit ID
            return RoutingDecision(
                action=RoutingAction.HYBRID_SEARCH,
                query=user_query,
                reason="Thiếu số Điều cha để cấu thành mã đơn vị pháp lý hợp lệ.",
                extracted_by="tier1_regex",
            )

        if point_letter and clause_num:
            unit_id = make_point_id(
                doc_id, str(article_num), str(clause_num), point_letter
            )
        elif clause_num:
            unit_id = make_clause_id(doc_id, str(article_num), str(clause_num))
        else:
            unit_id = make_article_id(doc_id, str(article_num))

        return RoutingDecision(
            action=RoutingAction.DIRECT_LOOKUP,
            unit_id=unit_id,
            query=user_query,
            reason=f"Đầy đủ tọa độ điều khoản và văn bản '{doc_id}', kích hoạt tra cứu trực tiếp.",
            extracted_by="tier1_regex",
        )

    def _extract_canonical_document(self, q_lower: str) -> str | None:
        """Extracts and normalizes document reference reusing resolve_canonical_doc_id()."""
        # A. Check textual aliases first
        for pat, alias in TEXTUAL_DOC_NAME_MAPPINGS:
            if pat.search(q_lower):
                resolved = resolve_canonical_doc_id(alias)
                if resolved:
                    return resolved

        # B. Check standard document expressions: "nghị định 168", "nd168", "nđ 168", "luật 36", "tt72"
        # B1. Prefix patterns: "nd 168", "nd168", "nđ168", "luật 36", "tt 72"
        m_prefix = re.search(
            r"\b(?:nghị\s*định|nghidinh|nđ|nd|luật|luat|thông\s*tư|tt)\s*([0-9]{1,4}(?:/[0-9]{4}/[a-za-z0-9_-]+)?)\b",
            q_lower,
        )
        if m_prefix:
            raw_cand = m_prefix.group(1)
            resolved = resolve_canonical_doc_id(raw_cand)
            if resolved and resolved in KNOWN_DOCUMENT_MAP.values():
                return resolved

        # B2. Compact prefixes: "nd168", "nđ168", "tt72", "luat36"
        m_compact = re.search(r"\b(?:nd|nđ|luat|luật|tt)([0-9]{2,3})\b", q_lower)
        if m_compact:
            raw_cand = m_compact.group(1)
            resolved = resolve_canonical_doc_id(raw_cand)
            if resolved and resolved in KNOWN_DOCUMENT_MAP.values():
                return resolved

        # B3. Check if any known document key appears as an isolated word (e.g. "168/2024", "168")
        # Only when accompanied by legal indicator to avoid matching arbitrary numbers
        if any(
            w in q_lower for w in ["nghị định", "nd", "nđ", "luật", "thông tư", "tt"]
        ):
            for k, doc_val in KNOWN_DOCUMENT_MAP.items():
                if re.search(rf"\b{re.escape(k)}\b", q_lower):
                    return doc_val

        return None

    def _extract_coordinates(
        self, q_lower: str
    ) -> tuple[str | None, str | None, str | None]:
        """Extracts Point (letter), Clause (number), Article (number) coordinates from query."""
        point_letter: str | None = None
        clause_num: str | None = None
        article_num: str | None = None

        # 1. Point (Điểm)
        # e.g. "điểm đ", "điểm d", "điểm a", "điểm 1"
        m_point = re.search(r"\bđiểm\s+([^\W\d_]|[0-9]+)\b", q_lower)
        if m_point:
            point_letter = m_point.group(1).lower()

        # 2. Clause (Khoản)
        # 2A. Direct digits: "khoản 5"
        m_clause_digit = re.search(r"\bkhoản\s+([0-9]+)\b", q_lower)
        if m_clause_digit:
            clause_num = str(int(m_clause_digit.group(1)))
        else:
            # 2B. Spelled-out words: "khoản năm"
            m_clause_word = re.search(
                r"\bkhoản\s+([\w\s]+?)(?=\s+(?:điều|đ\.?|d\.?|điểm|bên|tại|trong|của|về|nghị|nđ|nd|luật|thông\s*tư|tt|xử\s*phạt|phạt|quy\s*định)|$)",
                q_lower,
            )
            if m_clause_word:
                cand = m_clause_word.group(1).strip()
                parsed_c = parse_vietnamese_number_string(cand)
                if parsed_c:
                    clause_num = parsed_c
        if not clause_num:
            # 2C. Shorthand: "k5", "k.5", "k 5"
            m_short_k = re.search(r"\bk\.?\s*([0-9]+)\b", q_lower)
            if m_short_k:
                clause_num = str(int(m_short_k.group(1)))

        # 3. Article (Điều)
        # 3A. Direct digits: "điều 6", "điều 15"
        m_art_digit = re.search(r"\bđiều\s+([0-9]+)\b", q_lower)
        if m_art_digit:
            article_num = str(int(m_art_digit.group(1)))
        else:
            # 3B. Spelled-out words: "điều sáu", "điều bảy"
            m_art_word = re.search(
                r"\bđiều\s+([\w\s]+?)(?=\s+(?:khoản|k\.?|điểm|bên|tại|trong|của|về|nghị|nđ|nd|luật|thông\s*tư|tt|xử\s*phạt|phạt|quy\s*định)|$)",
                q_lower,
            )
            if m_art_word:
                cand = m_art_word.group(1).strip()
                parsed_a = parse_vietnamese_number_string(cand)
                if parsed_a:
                    article_num = parsed_a
        if not article_num:
            # 3C. Shorthand: "d6", "d.6", "đ6", "đ.6", "d 6"
            m_short_d = re.search(r"\b(?:d|đ)\.?\s*([0-9]+)\b", q_lower)
            if m_short_d:
                article_num = str(int(m_short_d.group(1)))

        return point_letter, clause_num, article_num

    def _route_tier2_multi_provider(self, clean_query: str) -> RoutingDecision:
        """Tier 2 fallback using Multi-Provider LLM Tool Calling with MCP Schema."""
        retries = 0
        while retries < self.max_retries:
            try:
                pkey = self.key_manager.get_provider_key(purpose="router")
            except Exception as e:
                logger.warning(
                    "Failed to obtain API key across providers for router: %s. Falling back to HYBRID_SEARCH.",
                    e,
                )
                return RoutingDecision(
                    action=RoutingAction.HYBRID_SEARCH,
                    query=clean_query,
                    reason="Không thể kết nối LLM provider, an toàn chuyển sang Hybrid Search.",
                    extracted_by="tier2_fallback",
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
                    headers = {"Content-Type": "application/json"}
                    payload: dict[str, Any] = {
                        "system_instruction": {
                            "parts": [{"text": ROUTER_SYSTEM_PROMPT}]
                        },
                        "contents": [
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "text": f'Phân tích và quyết định phân luồng cho câu hỏi sau:\n"{clean_query}"'
                                    }
                                ],
                            }
                        ],
                        "tools": [
                            get_gemini_tool_declaration(MCP_TOOL_LOOKUP_LEGAL_PROVISION)
                        ],
                        "generationConfig": {
                            "temperature": 0.0,
                            "maxOutputTokens": 600,
                        },
                    }
                else:  # openai-compatible (Groq, Cerebras, Cohere, Local LLM)
                    url = (
                        endpoint
                        if endpoint.endswith("/chat/completions")
                        else f"{endpoint}/chat/completions"
                    )
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                    }
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": f'Phân tích và quyết định phân luồng cho câu hỏi sau:\n"{clean_query}"',
                            },
                        ],
                        "tools": [
                            get_openai_tool_schema(MCP_TOOL_LOOKUP_LEGAL_PROVISION)
                        ],
                        "tool_choice": "auto",
                        "temperature": 0.0,
                        "max_tokens": 600,
                    }

                resp = self.session.post(
                    url, headers=headers, json=payload, timeout=20.0
                )

                if resp.status_code == 429:
                    logger.warning(
                        "Rate limit (HTTP 429) hit during router for provider '%s'. Rotating key...",
                        provider,
                    )
                    self.key_manager.mark_rate_limited(key, provider=provider)
                    retries += 1
                    continue

                if resp.status_code >= 500:
                    logger.warning(
                        "Server error %d from provider '%s' during router. Rotating key...",
                        resp.status_code,
                        provider,
                    )
                    self.key_manager.mark_rate_limited(
                        key, cooldown_seconds=15.0, provider=provider
                    )
                    retries += 1
                    continue

                if resp.status_code != 200:
                    logger.warning(
                        "Client error %d from provider '%s' during router: %s",
                        resp.status_code,
                        provider,
                        resp.text,
                    )
                    self.key_manager.mark_rate_limited(
                        key, cooldown_seconds=60.0, provider=provider
                    )
                    retries += 1
                    continue

                resp_data = resp.json()
                return self._parse_llm_routing_response(
                    resp_data, api_type=api_type, clean_query=clean_query
                )

            except Exception as exc:
                logger.warning(
                    "Error during query router with provider '%s': %s. Retry %d/%d",
                    provider,
                    exc,
                    retries + 1,
                    self.max_retries,
                )
                self.key_manager.mark_rate_limited(
                    key, cooldown_seconds=15.0, provider=provider
                )
                retries += 1

        return RoutingDecision(
            action=RoutingAction.HYBRID_SEARCH,
            query=clean_query,
            reason="Không nhận được phản hồi hợp lệ từ LLM sau các lượt thử, an toàn chuyển qua Hybrid Search.",
            extracted_by="tier2_fallback",
        )

    def _parse_llm_routing_response(
        self,
        resp_data: dict[str, Any],
        api_type: str,
        clean_query: str,
    ) -> RoutingDecision:
        """Extracts either tool call (unit_id) or structured JSON (HYBRID_SEARCH) from LLM output."""
        try:
            # 1. Check Gemini Response format
            if api_type == "gemini":
                candidates = resp_data.get("candidates", [])
                if not candidates:
                    return RoutingDecision(
                        action=RoutingAction.HYBRID_SEARCH,
                        query=clean_query,
                        reason="Gemini trả về candidate rỗng.",
                        extracted_by="tier2_llm",
                    )
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    # Check function call
                    fn_call = part.get("functionCall")
                    if fn_call and fn_call.get("name") == "lookup_legal_provision":
                        args = fn_call.get("args", {})
                        unit_id = args.get("unit_id")
                        if unit_id:
                            return RoutingDecision(
                                action=RoutingAction.DIRECT_LOOKUP,
                                unit_id=str(unit_id).strip(),
                                query=clean_query,
                                reason="LLM kích hoạt tool lookup_legal_provision thành công.",
                                extracted_by="tier2_llm",
                            )

                    # Check text response (JSON)
                    text = part.get("text", "").strip()
                    if text:
                        return self._parse_json_fallback(text, clean_query)

            # 2. Check OpenAI-Compatible Response format (Groq, Cerebras, Cohere)
            else:
                choices = resp_data.get("choices", [])
                if not choices:
                    return RoutingDecision(
                        action=RoutingAction.HYBRID_SEARCH,
                        query=clean_query,
                        reason="OpenAI provider trả về choices rỗng.",
                        extracted_by="tier2_llm",
                    )
                message = choices[0].get("message", {})
                tool_calls = message.get("tool_calls", [])
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    if fn.get("name") == "lookup_legal_provision":
                        arg_str = fn.get("arguments", "{}")
                        try:
                            args = (
                                json.loads(arg_str)
                                if isinstance(arg_str, str)
                                else arg_str
                            )
                            unit_id = args.get("unit_id")
                            if unit_id:
                                return RoutingDecision(
                                    action=RoutingAction.DIRECT_LOOKUP,
                                    unit_id=str(unit_id).strip(),
                                    query=clean_query,
                                    reason="LLM kích hoạt tool lookup_legal_provision thành công.",
                                    extracted_by="tier2_llm",
                                )
                        except Exception as exc:
                            logger.debug("Failed to parse tool call arguments: %s", exc)

                # If no tool call, parse content text as JSON fallback
                content = message.get("content", "").strip()
                if content:
                    return self._parse_json_fallback(content, clean_query)

        except Exception as e:
            logger.warning("Error parsing LLM routing response: %s", e)

        return RoutingDecision(
            action=RoutingAction.HYBRID_SEARCH,
            query=clean_query,
            reason="Mặc định chuyển sang Hybrid Search.",
            extracted_by="tier2_llm",
        )

    def _parse_json_fallback(self, text: str, clean_query: str) -> RoutingDecision:
        """Parses fallback JSON string returned when LLM decides HYBRID_SEARCH."""
        clean_text = text.strip()
        # Clean markdown codeblocks if present
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
            clean_text = re.sub(r"\s*```$", "", clean_text)

        try:
            parsed = json.loads(clean_text)
            if isinstance(parsed, dict):
                act_str = parsed.get("action", "HYBRID_SEARCH").upper()
                action = (
                    RoutingAction.DIRECT_LOOKUP
                    if act_str == "DIRECT_LOOKUP"
                    else RoutingAction.HYBRID_SEARCH
                )
                unit_id = parsed.get("unit_id")
                query = parsed.get("query") or clean_query
                reason = parsed.get("reason", "Phân luồng từ kết quả phân tích LLM.")
                return RoutingDecision(
                    action=action,
                    unit_id=unit_id,
                    query=query,
                    reason=reason,
                    extracted_by="tier2_llm",
                )
        except Exception as exc:
            logger.debug("Failed to parse JSON fallback response: %s", exc)

        return RoutingDecision(
            action=RoutingAction.HYBRID_SEARCH,
            query=clean_query,
            reason="Không phân tích được JSON từ phản hồi LLM, chuyển sang Hybrid Search.",
            extracted_by="tier2_llm",
        )
