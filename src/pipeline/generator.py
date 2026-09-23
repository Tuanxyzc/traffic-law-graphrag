"""Answer Generator producing strictly grounded legal responses from evidence packages."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests  # type: ignore[import-untyped]

from src.extraction.key_manager import KeyManager
from src.pipeline.config import PipelineConfig
from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.models import EvidencePackage, GenerationResult
from src.pipeline.prompts import GENERATE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

CITATION_REGEX = re.compile(
    r"(?:(?:Điểm|điểm)\s+[a-zđ]\s+)?(?:(?:Khoản|khoản)\s+\d+\s+)?(?:Điều|điều)\s+\d+(?:\s+Nghị\s+định\s+[\w/-]+)?",
    re.IGNORECASE,
)


def extract_citations_from_text(
    text: str, package: EvidencePackage | None = None
) -> list[str]:
    """Extracts statutory citation patterns (e.g. Điểm a Khoản 1 Điều 5) from text."""
    if package is not None:
        # If this is a system catalog query, or there are 0 provisions/amendments in evidence, citations must be empty
        if package.system_documents or (
            not package.items and not package.document_amendments
        ):
            return []

    matches = CITATION_REGEX.findall(text)
    unique_citations: list[str] = []
    seen: set[str] = set()
    for m in matches:
        clean = m.strip()
        if clean.lower() not in seen and len(clean) > 4:
            seen.add(clean.lower())
            unique_citations.append(clean)
    return unique_citations


def has_sanctions_in_package(package: EvidencePackage) -> bool:
    """Checks whether the evidence package contains concrete sanction details (fine amounts or point deductions)."""
    for item in package.items:
        prov = item.validated_provision
        texts = [
            item.original_chunk_text or "",
            prov.content_text or "",
            prov.parent_clause_content or "",
            item.superseding_text or "",
        ]
        combined = " ".join(texts).lower()
        if re.search(
            r"phạt tiền từ\s+\d+|bị trừ\s+\d+\s+điểm|tước quyền sử dụng\s+giấy phép",
            combined,
        ):
            return True
        for ref in prov.cross_references:
            rel = (ref.relation_type or "").upper()
            ref_c = (ref.content or "").lower()
            if rel in (
                "TRU_DIEM_GPLX",
                "TUOC_QUYEN_GPLX",
                "TICH_THU",
                "APPLIED_SANCTION",
            ):
                return True
            if "trừ" in ref_c and "điểm" in ref_c:
                return True
            if "tước quyền" in ref_c:
                return True

    for am in package.document_amendments:
        am_combined = f"{am.instruction or ''} {am.replacement_content or ''}".lower()
        if re.search(
            r"phạt tiền từ\s+\d+|bị trừ\s+\d+\s+điểm|tước quyền sử dụng\s+giấy phép|tịch thu",
            am_combined,
        ):
            return True

    return False


def clean_generated_answer(text: str | None, has_sanctions: bool = True) -> str:
    """Cleans generated answer by deduplicating repetitive sections and pruning redundant no-sanction notes."""
    if not text or not isinstance(text, str):
        return ""

    # Strip prompt leakage XML tags
    cleaned_text = re.sub(
        r"</?(?:can_cu_phap_ly|chi_dan_tu_van|evidence|instructions)>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # 1. Deduplicate repeated markdown header sections (breaking degenerative completion loops)
    lines = cleaned_text.split("\n")
    cleaned_lines: list[str] = []
    seen_headers: set[str] = set()
    skipping_duplicate_section = False

    for line in lines:
        m = re.match(r"^\s*(#{1,4})\s+(.+)$", line)
        if m:
            normalized_header = re.sub(r"[*_#`]", "", m.group(2)).strip().lower()
            if normalized_header in seen_headers:
                skipping_duplicate_section = True
                continue
            else:
                skipping_duplicate_section = False
                seen_headers.add(normalized_header)
        elif skipping_duplicate_section:
            continue

        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)

    # 2. If no sanctions in evidence, prune any unwanted section explaining lack of penalties
    if not has_sanctions:
        blocks = re.split(r"(?:\n\s*---\s*\n|\n(?=#{1,4}\s+))", result)
        retained_blocks: list[str] = []
        for block in blocks:
            b_strip = block.strip()
            if not b_strip:
                continue
            b_lower = b_strip.lower()
            is_no_sanction_block = (
                "ghi chú" in b_lower
                or "hình thức xử phạt" in b_lower
                or "mức phạt" in b_lower
                or "trừ điểm" in b_lower
            ) and (
                "không trực tiếp chế tài" in b_lower
                or "không quy định mức phạt" in b_lower
                or "không quy định hình thức xử phạt" in b_lower
                or "không có mức phạt" in b_lower
                or (
                    "không quy định" in b_lower
                    and ("phạt tiền" in b_lower or "trừ điểm" in b_lower)
                )
            )
            if not is_no_sanction_block:
                retained_blocks.append(b_strip)

        if retained_blocks:
            result = (
                "\n\n---\n\n".join(retained_blocks)
                if len(retained_blocks) > 1
                else retained_blocks[0]
            )

    # Strip role repetition prefixes like "Bạn là chuyên viên tư vấn pháp luật..."
    result = re.sub(
        r"^(?:(?:Bạn|Tôi)\s+là\s+chuyên\s+viên\s+tư\s+vấn\s+pháp\s+luật\s+giao\s+thông\s+đường\s+bộ\s+Việt\s+Nam[.\s]*)+",
        "",
        result.strip(),
        flags=re.IGNORECASE,
    )

    # Strip conversational echo prefixes like "Trả lời :", "Câu trả lời :", "CÂU TRẢ LỜI CĂN CỨ PHÁP LUẬT :" at start
    result = re.sub(
        r"^(?:Trả\s+lời\s*:|Câu\s+trả\s+lời\s*:|Tư\s+vấn\s*:|CÂU\s+TRẢ\s+LỜI(?:\s+CĂN\s+CỨ\s+PHÁP\s+LUẬT)?\s*:)\s*",
        "",
        result.strip(),
        flags=re.IGNORECASE,
    )

    # Strip trailing horizontal dividers or excessive line breaks
    result = re.sub(r"(?:\n\s*---\s*)+\Z", "", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def verify_action_grounding(
    answer_text: str,
    rewritten_query: Any,
    package: EvidencePackage,
) -> tuple[bool, list[str]]:
    """Verifies that generated answer adheres to action grounding constraints dynamically without hardcoding.

    Checks:
    1. Negative term drift: Answer does not introduce terms from must_not_have_terms
       (e.g., drift to traffic lights when asked about traffic police signals).
    2. Target entity coverage: If target_entities has multiple vehicles, answer mentions them.
    3. Grounding integrity: Extracted statutory citations correspond to provisions present
       in the evidence package or referenced provisions.

    Returns:
        tuple[bool, list[str]]: (is_valid, warnings)
    """
    warnings: list[str] = []
    if not answer_text or not isinstance(answer_text, str):
        return True, warnings

    ans_lower = answer_text.lower()

    # 1. Negative term drift check
    must_not_have = (
        getattr(rewritten_query, "must_not_have_terms", [])
        if hasattr(rewritten_query, "must_not_have_terms")
        else []
    )
    user_q_lower = (package.user_query or "").lower()
    keywords = [
        kw.lower()
        for kw in getattr(rewritten_query, "identified_keywords", [])
        if isinstance(kw, str)
    ]
    for term in must_not_have:
        if term and term.lower() in ans_lower:
            t_lower = term.lower()
            if t_lower in user_q_lower or any(t_lower in kw for kw in keywords):
                continue
            warnings.append(
                f"Phát hiện trôi lệch hành vi: câu trả lời chứa thuật ngữ cấm '{term}'"
            )

    # 2. Target entities coverage check
    target_entities = (
        getattr(rewritten_query, "target_entities", [])
        if hasattr(rewritten_query, "target_entities")
        else []
    )
    entity_keywords = {
        "xe_o_to": ["ô tô", "o to", "xe con", "xe tải"],
        "xe_mo_to": ["mô tô", "mo to", "xe máy", "xe gắn máy"],
        "xe_may_chuyen_dung": ["chuyên dùng", "máy thi công", "xe lu", "máy ủi"],
        "xe_dap": ["xe đạp", "xe thô sơ"],
        "nguoi_di_bo": ["người đi bộ", "đi bộ"],
        "vat_nuoi": ["súc vật", "vật nuôi"],
    }
    if len(target_entities) > 1:
        for ent in target_entities:
            kw_list = entity_keywords.get(ent, [ent.replace("_", " ")])
            if not any(kw in ans_lower for kw in kw_list):
                warnings.append(
                    f"Thiếu nhóm phương tiện mục tiêu: câu trả lời chưa đề cập đến '{ent}'"
                )

    # 3. Grounding integrity check: verify citations in answer correspond to package
    package_article_ids: set[str] = set()
    package_article_titles: list[str] = []
    for item in package.items:
        prov = item.validated_provision
        if prov.parent_article_id:
            package_article_ids.add(prov.parent_article_id.lower())
        if prov.provision_id:
            package_article_ids.add(prov.provision_id.lower())
        if prov.parent_article_title:
            package_article_titles.append(prov.parent_article_title.lower())
        for ref in prov.cross_references:
            if ref.target_id:
                package_article_ids.add(ref.target_id.lower())
            if ref.title:
                package_article_titles.append(ref.title.lower())

    for am in package.document_amendments:
        if am.article_id:
            package_article_ids.add(am.article_id.lower())
        if am.target_id:
            package_article_ids.add(am.target_id.lower())
        if am.article_title:
            package_article_titles.append(am.article_title.lower())

    if package_article_ids or package_article_titles:
        citations = extract_citations_from_text(answer_text, package=package)
        for cit in citations:
            m_art = re.search(r"(?:điều|dieu)\s+(\d+)", cit, re.IGNORECASE)
            if m_art:
                art_num = m_art.group(1)
                art_marker = f"_d{art_num}"
                art_marker_word = f"điều {art_num}"
                matches_id = any(
                    art_marker == pid
                    or f"{art_marker}_" in pid
                    or pid.endswith(art_marker)
                    for pid in package_article_ids
                )
                matches_title = any(
                    art_marker_word in t for t in package_article_titles
                )
                if not matches_id and not matches_title:
                    warnings.append(
                        f"Căn cứ pháp lý chưa được kiểm chứng trong dữ liệu trích xuất: '{cit}'"
                    )

    is_valid = len(warnings) == 0
    return is_valid, warnings


class AnswerGenerator:
    """Generates strictly grounded legal answers from EvidencePackage using Local LLM or Gemini REST API."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        key_manager: KeyManager | None = None,
        evidence_builder: EvidenceBuilder | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or PipelineConfig.from_env()
        self.key_manager = key_manager or KeyManager()
        self.evidence_builder = evidence_builder or EvidenceBuilder(config=self.config)
        self.model = self.config.model_name
        self.max_retries = self.config.max_retries
        self.session = session or requests.Session()

    def _build_user_prompt(self, evidence: EvidencePackage, has_sanctions: bool) -> str:
        """Builds user prompt for answer generation."""
        if (
            not evidence.items
            and not evidence.document_amendments
            and not evidence.system_documents
        ):
            return (
                f'CÂU HỎI / LỜI NHẮN CỦA NGƯỜI DÂN: "{evidence.user_query}"\n\n'
                f"TÌNH TRẠNG TRA CỨU: Không tìm thấy điều khoản quy định pháp luật giao thông đường bộ nào trong cơ sở dữ liệu phù hợp với câu hỏi này.\n\n"
                f"HƯỚNG DẪN XỬ LÝ:\n"
                f"1. NẾU ĐÂY LÀ LỜI CHÀO HỎI, GIAO TIẾP HOẶC HỎI DANH TÍNH (ví dụ: 'xin chào', 'bạn là ai', 'chào bạn'):\n"
                f"   - Hãy chào hỏi lại người dân một cách lịch sự, thân thiện.\n"
                f"   - Giới thiệu rõ ràng bạn là Trợ lý AI Cố vấn Pháp luật Trật tự An toàn Giao thông Đường bộ Việt Nam, luôn sẵn sàng hỗ trợ giải đáp các quy định, mức xử phạt vi phạm hành chính và quy tắc an toàn giao thông.\n"
                f"2. NẾU ĐÂY LÀ CÂU HỎI NGOÀI PHẠM VI (không liên quan đến trật tự, an toàn giao thông đường bộ, ví dụ: hỏi công thức nấu ăn, thời tiết, lập trình, giải trí, sức khỏe...):\n"
                f"   - Hãy từ chối một cách lịch sự, nêu rõ bạn là Trợ lý chuyên sâu về Pháp luật Trật tự An toàn Giao thông Đường bộ Việt Nam nên chỉ hỗ trợ các câu hỏi thuộc lĩnh vực này.\n"
                f"   - Mời người dân đặt câu hỏi về luật giao thông đường bộ, quy định xử phạt vi phạm hành chính, hoặc quy tắc an toàn giao thông.\n"
                f"3. NẾU ĐÂY LÀ CÂU HỎI VỀ GIAO THÔNG NHƯNG CHƯA ĐỦ THÔNG TIN HOẶC HỆ THỐNG CHƯA CẬP NHẬT:\n"
                f"   - Thông báo rõ ràng hiện tại cơ sở dữ liệu chưa tìm thấy quy định trực tiếp cho trường hợp này, và đề nghị người dân cung cấp thêm ngữ cảnh cụ thể (loại phương tiện, hành vi vi phạm...). Tuyệt đối không tự suy diễn hoặc bịa đặt điều luật, số hiệu văn bản."
            )

        evidence_text = self.evidence_builder.format_for_llm(evidence)
        rw = evidence.rewritten_query

        bullets: list[str] = [
            f'- Trả lời trực tiếp, tự nhiên, gãy gọn vào câu hỏi của người dân: "{evidence.user_query}".',
        ]

        # 1. Target entities guidance (Dynamic Multi-Vehicle Handling)
        target_entities: list[str] = (
            getattr(rw, "target_entities", [])
            if hasattr(rw, "target_entities") and rw.target_entities
            else []
        )
        if len(target_entities) > 1:
            entities_str = ", ".join(target_entities)
            bullets.append(
                f"- Câu hỏi áp dụng cho nhiều nhóm phương tiện ({entities_str}). "
                "Hãy phân tách rõ ràng từng nhóm phương tiện trong câu trả lời; "
                "với mỗi nhóm phương tiện, nêu đầy đủ: mức tiền phạt (từ quy định chính), "
                "số điểm GPLX bị trừ (hoặc hình thức tước quyền nếu có từ quy định tham chiếu 1-hop), "
                "và viện dẫn chính xác căn cứ pháp lý."
            )
        else:
            bullets.append(
                "- Phân định rõ loại phương tiện mà người dân hỏi (xe mô tô, xe gắn máy vs xe máy chuyên dùng vs xe ô tô)."
            )

        # 2. Sanction vs Non-sanction guidance
        if evidence.system_documents:
            bullets.append(
                "- Liệt kê danh mục văn bản, không đề cập đến mức phạt tiền hay trừ điểm "
                "vì đây là câu hỏi tra cứu danh mục tài liệu của hệ thống."
            )
        elif has_sanctions:
            bullets.append(
                "- Nêu cụ thể mức phạt tiền và trừ điểm giấy phép lái xe theo đúng quy định "
                "trong căn cứ tương ứng với loại phương tiện."
            )
        else:
            bullets.append(
                "- Trong căn cứ không có mức phạt tiền hoặc trừ điểm (hoặc câu hỏi chỉ hỏi về quy tắc), "
                "tuyệt đối KHÔNG nhắc đến hay thanh minh về việc không có phạt tiền/trừ điểm. "
                "Chỉ tập trung nêu rõ quy tắc và hành vi vi phạm."
            )

        # 3. Violation Sanction vs Law Enforcement Powers Distinction
        query_intent = getattr(rw, "intent", None)
        if query_intent == "violation_sanction":
            bullets.append(
                "- Tập trung giải đáp các chế tài xử phạt hành chính đối với người vi phạm; "
                "tuyệt đối không đưa các quy định về thẩm quyền, biện pháp nghiệp vụ của lực lượng thực thi công vụ "
                "(như quyền tuần tra, kiểm soát, dừng phương tiện, truy đuổi của CSGT) vào làm chế tài xử phạt của người dân."
            )

        # 4. Action matching accuracy
        bullets.append(
            "- Đối chiếu chính xác hành vi vi phạm: chỉ áp dụng các Điểm, Khoản có nội dung khớp đúng với hành vi người dân hỏi, "
            "không nhầm lẫn sang các hành vi vi phạm khác."
        )

        bullets.append(
            "- Dẫn chứng chuẩn xác Điều, Khoản, Điểm và Tên văn bản quy phạm pháp luật làm căn cứ."
        )
        bullets.append(
            "- Nếu có điều khoản đã bị thay thế hoặc sửa đổi (xem cờ cảnh báo), hướng dẫn áp dụng theo quy định mới nhất hiện hành."
        )

        chi_dan_text = "\n".join(bullets)

        return (
            f"<can_cu_phap_ly>\n"
            f"{evidence_text}\n"
            f"</can_cu_phap_ly>\n\n"
            f"<chi_dan_tu_van>\n"
            f"{chi_dan_text}\n"
            f"</chi_dan_tu_van>"
        )

    def _generate_local(
        self,
        user_prompt: str,
        has_sanctions: bool,
        evidence: EvidencePackage,
    ) -> GenerationResult:
        """Generates answer using Localhost LLM via OpenAI-compatible chat completions REST API."""
        endpoint = self.config.generator_local_endpoint.rstrip("/")
        url = (
            endpoint
            if endpoint.endswith("/chat/completions")
            else f"{endpoint}/chat/completions"
        )
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.generator_local_api_key:
            headers["Authorization"] = f"Bearer {self.config.generator_local_api_key}"

        payload: dict[str, Any] = {
            "model": self.config.generator_local_model,
            "messages": [
                {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.generator_local_temperature,
        }

        try:
            resp = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.config.generator_local_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise ValueError("Empty choices in Local LLM generate response")
            first_choice = choices[0] or {}
            message = first_choice.get("message") or {}
            text_content = message.get("content")
            if not text_content or not isinstance(text_content, str):
                raise ValueError("Empty content in Local LLM generate choice")

            clean_answer = clean_generated_answer(
                text_content, has_sanctions=has_sanctions
            )
            citations = extract_citations_from_text(clean_answer, package=evidence)
            is_grounded, warnings = verify_action_grounding(
                clean_answer, evidence.rewritten_query, evidence
            )
            if warnings:
                logger.warning(
                    "Grounding verification warnings for query '%s': %s",
                    evidence.user_query,
                    warnings,
                )

            return GenerationResult(
                answer=clean_answer,
                citations=citations,
                raw_response=text_content,
                grounding_verified=is_grounded,
                verification_warnings=warnings,
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
            logger.error("Local LLM answer generation failed (HTTPError): %s", err_msg)
            return GenerationResult(
                answer="Hệ thống tạm thời không thể tạo câu trả lời do gián đoạn kết nối tới dịch vụ mô hình ngôn ngữ cục bộ. Vui lòng kiểm tra lại dịch vụ Local LLM.",
                citations=[],
            )
        except Exception as exc:
            logger.error(
                "Local LLM answer generation failed: %s",
                exc,
            )
            return GenerationResult(
                answer="Hệ thống tạm thời không thể tạo câu trả lời do gián đoạn kết nối tới dịch vụ mô hình ngôn ngữ cục bộ. Vui lòng kiểm tra lại dịch vụ Local LLM.",
                citations=[],
            )

    def _generate_gemini(
        self,
        user_prompt: str,
        has_sanctions: bool,
        evidence: EvidencePackage,
    ) -> GenerationResult:
        """Backward-compatible alias for _generate_cloud."""
        return self._generate_cloud(
            user_prompt=user_prompt,
            has_sanctions=has_sanctions,
            evidence=evidence,
        )

    def _generate_cloud(
        self,
        user_prompt: str,
        has_sanctions: bool,
        evidence: EvidencePackage,
    ) -> GenerationResult:
        """Generates answer using multi-provider Cloud LLM (Gemini, Groq, Cerebras, Cohere)."""
        retries = 0
        while retries < self.max_retries:
            try:
                pkey = self.key_manager.get_provider_key(purpose="generate")
            except Exception as e:
                logger.error(
                    "Failed to obtain API key across providers for AnswerGenerator: %s",
                    e,
                )
                break

            provider = pkey.provider
            key = pkey.key
            # Use configured model for gemini if specified, otherwise provider's model
            model = (
                self.config.model_name
                if provider == "gemini" and self.config.model_name
                else pkey.model
            )
            endpoint = pkey.endpoint.rstrip("/")
            api_type = pkey.api_type

            try:
                if api_type == "gemini":
                    url = f"{endpoint}/models/{model}:generateContent?key={key}"
                    headers: dict[str, str] = {"Content-Type": "application/json"}
                    payload: dict[str, Any] = {
                        "system_instruction": {
                            "parts": [{"text": GENERATE_SYSTEM_PROMPT}]
                        },
                        "contents": [
                            {"role": "user", "parts": [{"text": user_prompt}]}
                        ],
                        "generationConfig": {
                            "temperature": self.config.temperature_generate,
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
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self.config.temperature_generate,
                    }

                resp = self.session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )

                # HTTP 429 Rate limited
                if resp.status_code == 429:
                    logger.warning(
                        "Quota reached (HTTP 429) for provider '%s'. Rotating key / failing over...",
                        provider,
                    )
                    self.key_manager.mark_rate_limited(key, provider=provider)
                    retries += 1
                    continue

                # Server errors (500, 502, 503, 504)
                if resp.status_code in (500, 502, 503, 504):
                    retries += 1
                    logger.warning(
                        "Server error %d from provider '%s' during answer generation. Rotating key with short cooldown...",
                        resp.status_code,
                        provider,
                    )
                    self.key_manager.mark_server_error(
                        key, cooldown_seconds=15.0, provider=provider
                    )
                    time.sleep(min(retries * 1.5, 6))
                    continue

                # Client errors (400, 401, 403, 404)
                if 400 <= resp.status_code < 500:
                    logger.error(
                        "Fatal client error %d from provider '%s' during answer generation: %s",
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
                            "Empty candidate response from Gemini API for answer generation."
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
                            "Empty choices response from provider '%s' for answer generation.",
                            provider,
                        )
                        retries += 1
                        continue
                    text_content = choices[0].get("message", {}).get("content", "")

                if not text_content:
                    logger.warning(
                        "Empty text content from provider '%s' answer candidate.",
                        provider,
                    )
                    retries += 1
                    continue

                clean_answer = clean_generated_answer(
                    text_content, has_sanctions=has_sanctions
                )
                citations = extract_citations_from_text(clean_answer, package=evidence)
                is_grounded, warnings = verify_action_grounding(
                    clean_answer, evidence.rewritten_query, evidence
                )
                if warnings:
                    logger.warning(
                        "Grounding verification warnings for query '%s': %s",
                        evidence.user_query,
                        warnings,
                    )

                return GenerationResult(
                    answer=clean_answer,
                    citations=citations,
                    raw_response=text_content,
                    grounding_verified=is_grounded,
                    verification_warnings=warnings,
                )

            except requests.RequestException as req_err:
                retries += 1
                logger.warning(
                    "Request error during answer generation for provider '%s': %s. Retry %d/%d",
                    provider,
                    req_err,
                    retries,
                    self.max_retries,
                )
                self.key_manager.mark_server_error(
                    key, cooldown_seconds=15.0, provider=provider
                )
                time.sleep(min(retries * 1.5, 6))

        logger.error(
            "Failed to generate answer after %d attempts across available providers.",
            self.max_retries,
        )
        return GenerationResult(
            answer="Hệ thống tạm thời không thể tạo câu trả lời do gián đoạn kết nối tới dịch vụ mô hình ngôn ngữ. Vui lòng thử lại sau.",
            citations=[],
        )

    def generate(self, evidence: EvidencePackage) -> GenerationResult:
        """Generates grounded answer with statutory citations.

        Args:
            evidence: Formatted EvidencePackage.

        Returns:
            GenerationResult containing answer text and extracted citations.
        """
        has_sanctions = (
            False
            if (
                not evidence.items
                and not evidence.document_amendments
                and not evidence.system_documents
            )
            else has_sanctions_in_package(evidence)
        )
        user_prompt = self._build_user_prompt(evidence, has_sanctions=has_sanctions)

        if self.config.generator_use_local:
            return self._generate_local(
                user_prompt=user_prompt,
                has_sanctions=has_sanctions,
                evidence=evidence,
            )
        return self._generate_cloud(
            user_prompt=user_prompt,
            has_sanctions=has_sanctions,
            evidence=evidence,
        )
