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
    return False


def clean_generated_answer(text: str, has_sanctions: bool = True) -> str:
    """Cleans generated answer by deduplicating repetitive sections and pruning redundant no-sanction notes."""
    # 1. Deduplicate repeated markdown header sections (breaking degenerative completion loops)
    lines = text.split("\n")
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

        result = (
            "\n\n---\n\n".join(retained_blocks)
            if len(retained_blocks) > 1
            else ("".join(retained_blocks))
        )

    # Strip trailing horizontal dividers or excessive line breaks
    result = re.sub(r"(?:\n\s*---\s*)+\Z", "", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


class AnswerGenerator:
    """Generates strictly grounded legal answers from EvidencePackage using Gemini REST API."""

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

    def generate(self, evidence: EvidencePackage) -> GenerationResult:
        """Generates grounded answer with statutory citations.

        Args:
            evidence: Formatted EvidencePackage.

        Returns:
            GenerationResult containing answer text and extracted citations.
        """
        if (
            not evidence.items
            and not evidence.document_amendments
            and not evidence.system_documents
        ):
            has_sanctions = False
            user_prompt = (
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
        else:
            evidence_text = self.evidence_builder.format_for_llm(evidence)
            has_sanctions = has_sanctions_in_package(evidence)

            if evidence.system_documents:
                sanction_instruction = (
                    "2. Về danh mục văn bản: Trình bày đầy đủ, phân loại rõ ràng các Luật và Nghị định có trong bằng chứng. "
                    "Tuyệt đối KHÔNG đề cập đến mức phạt tiền hay trừ điểm vì đây là câu hỏi về danh mục tài liệu của hệ thống."
                )
            elif has_sanctions:
                sanction_instruction = (
                    "2. Nêu rõ hình thức xử phạt (mức phạt tiền, tước GPLX, trừ điểm GPLX có trong bằng chứng). "
                    "Phân tách rõ ràng theo loại phương tiện nếu có."
                )
            else:
                sanction_instruction = (
                    "2. Về hình thức xử phạt và trừ điểm GPLX: BẰNG CHỨNG KHÔNG CÓ THÔNG TIN VỀ TIỀN PHẠT HAY TRỪ ĐIỂM "
                    "(hoặc câu hỏi không hỏi về vi phạm/xử phạt), TUYỆT ĐỐI KHÔNG CẦN NÊU RA LÀ KHÔNG CÓ, không tạo mục ghi chú giải thích. "
                    "Chỉ tập trung trả lời trực tiếp, đúng trọng tâm câu hỏi của người dân."
                )

            user_prompt = (
                f"HÃY GIẢI ĐÁP CÂU HỎI SAU DỰA HOÀN TOÀN VÀO GÓI BẰNG CHỨNG PHÁP LÝ:\n\n"
                f"{evidence_text}\n\n"
                f"YÊU CẦU TRẢ LỜI:\n"
                f'1. Trả lời trực tiếp, rõ ràng, đúng trọng tâm cho câu hỏi của người dân: "{evidence.user_query}".\n'
                f"{sanction_instruction}\n"
                f"3. Dẫn chiếu chính xác Điểm, Khoản, Điều, Văn bản.\n"
                f"4. Nếu có quy định cũ đã bị thay thế (xem cờ cảnh báo), phân tích ngắn gọn quy định trước đây và quy định hiện hành đang áp dụng."
            )

        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": GENERATE_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.config.temperature_generate,
            },
        }

        retries = 0
        while retries < self.max_retries:
            try:
                key = self.key_manager.get_key()
            except Exception as e:
                logger.error("Failed to obtain API key for AnswerGenerator: %s", e)
                break

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={key}"

            try:
                resp = self.session.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )

                # HTTP 429 Rate limited
                if resp.status_code == 429:
                    logger.warning(
                        "Quota reached during answer generation. Rotating key..."
                    )
                    self.key_manager.mark_rate_limited(key)
                    retries += 1
                    continue

                # Server errors (500, 502, 503, 504)
                if resp.status_code in (500, 502, 503, 504):
                    retries += 1
                    logger.warning(
                        "Server error %d from Gemini API during answer generation. Retrying...",
                        resp.status_code,
                    )
                    time.sleep(min(retries * 2, 8))
                    continue

                # Client error (400, 403, 404)
                if 400 <= resp.status_code < 500:
                    logger.error(
                        "Fatal client error %d during answer generation: %s",
                        resp.status_code,
                        resp.text,
                    )
                    break

                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    logger.warning(
                        "Empty candidate response from Gemini API for answer generation."
                    )
                    break

                text_content = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if not text_content:
                    logger.warning("Empty text part in Gemini answer candidate.")
                    break

                clean_answer = clean_generated_answer(
                    text_content, has_sanctions=has_sanctions
                )
                citations = extract_citations_from_text(clean_answer, package=evidence)

                return GenerationResult(
                    answer=clean_answer,
                    citations=citations,
                    raw_response=text_content,
                )

            except requests.RequestException as req_err:
                retries += 1
                logger.warning(
                    "Request error during answer generation: %s. Retry %d/%d",
                    req_err,
                    retries,
                    self.max_retries,
                )
                time.sleep(min(retries * 2, 8))

        logger.error("Failed to generate answer after %d attempts.", self.max_retries)
        return GenerationResult(
            answer="Hệ thống tạm thời không thể tạo câu trả lời do gián đoạn kết nối tới dịch vụ mô hình ngôn ngữ. Vui lòng thử lại sau.",
            citations=[],
        )
