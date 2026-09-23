"""Deterministic Legal Evaluator: Provision Citations, Fine Ranges, and Validity Warnings."""

from __future__ import annotations

import logging
import re

from src.eval.models import DeterministicScore, EvaluationSample

logger = logging.getLogger(__name__)

# Regular expressions for fine amount extraction
FINE_RANGE_PATTERN = re.compile(
    r"(?:phạt\s+tiền\s+từ|từ)\s+"
    r"([\d\.\,]+)\s*(triệu|tr|nghìn|k|đồng|đ)?\s*"
    r"(?:đến|-)\s*"
    r"([\d\.\,]+)\s*(triệu|tr|nghìn|k|đồng|đ)?",
    re.IGNORECASE,
)

SINGLE_FINE_PATTERN = re.compile(
    r"(?:phạt\s+tiền\s+mức|phạt\s+tiền|phạt)\s+"
    r"([\d\.\,]+)\s*(triệu|tr|nghìn|k|đồng|đ)",
    re.IGNORECASE,
)

PROVISION_CODE_PATTERN = re.compile(
    r"([a-zA-Z0-9_\-]+(?:_D\d+)?(?:_K\d+)?(?:_D[a-zA-Z0-9]+)?)"
)

# Textual Vietnamese citation patterns: "Điều X Khoản Y Điểm Z [Nghị định/Luật W]"
TEXTUAL_CITATION_PATTERN = re.compile(
    r"(?:Điểm\s+([a-zA-Z0-9_]+)\s+)?(?:Khoản\s+(\d+)\s+)?Điều\s+(\d+)(?:\s+(?:của\s+)?(Luật|Nghị\s+định|Thông\s+tư)\s+([0-9\/\-]+(?:\/[a-zA-Z0-9\-]+)?))?",
    re.IGNORECASE,
)

WARNING_PHRASES = [
    "hết hiệu lực",
    "đã được sửa đổi",
    "được sửa đổi",
    "sửa đổi, bổ sung bởi",
    "thay thế bởi",
    "đã bị thay thế",
    "đã bị bãi bỏ",
    "bãi bỏ bởi",
    "chưa có hiệu lực",
    "lưu ý hiệu lực",
    "cảnh báo",
]


def parse_vnd_amount(num_str: str, unit_str: str | None = None) -> int | None:
    """Parses Vietnamese currency string into integer VND amount."""
    clean_num = num_str.replace(".", "").replace(",", "").strip()
    if not clean_num.isdigit():
        return None

    val = int(clean_num)
    unit = (unit_str or "").lower().strip()

    if "triệu" in unit or unit == "tr":
        val = val * 1_000_000
    elif "nghìn" in unit or unit == "k":
        val = val * 1_000
    elif val < 1_000:
        # e.g., "phạt từ 2 đến 3 triệu" -> 2 should be 2,000,000
        val = val * 1_000_000

    return val


def extract_fine_range(text: str) -> tuple[int | None, int | None]:
    """Extracts minimum and maximum fine amounts in VND from text."""
    if not text:
        return None, None

    # Strip markdown formatting so numbers wrapped in ** are parsed cleanly
    clean_text = (
        text.replace("**", " ").replace("*", " ").replace("_", " ").replace("#", " ")
    )

    # 1. Try range pattern: "từ X đến Y [đồng/triệu]"
    range_match = FINE_RANGE_PATTERN.search(clean_text)
    if range_match:
        num1, unit1, num2, unit2 = range_match.groups()
        # If first unit is omitted, inherit from second unit (e.g. "từ 2 đến 3 triệu đồng")
        inherited_unit = unit2 if not unit1 else unit1
        val_min = parse_vnd_amount(num1, inherited_unit)
        val_max = parse_vnd_amount(num2, unit2)
        if val_min is not None and val_max is not None:
            if val_min > val_max:
                val_min, val_max = val_max, val_min
            return val_min, val_max

    # 2. Try single fine pattern
    single_match = SINGLE_FINE_PATTERN.search(clean_text)
    if single_match:
        num, unit = single_match.groups()
        val = parse_vnd_amount(num, unit)
        if val is not None:
            return val, val

    return None, None


def normalize_provision_id(prov_id: str) -> str:
    """Normalizes provision identifier into canonical format."""
    return prov_id.strip().upper().replace("Đ", "D").replace("-", "_").replace("/", "_")


TEXTUAL_PROV_PAT1 = re.compile(
    r"(?:Điểm\s+([a-zA-Z0-9]+)\s+)?(?:Khoản\s+(\d+)\s+)?Điều\s+(\d+)\s+(?:của\s+)?(?:Nghị\s+định|Luật|Thông\s+tư)\s+(?:số\s+)?([0-9\/\-a-zA-Z_đĐ]+)",
    re.IGNORECASE,
)

TEXTUAL_PROV_PAT2 = re.compile(
    r"Điều\s+(\d+)(?:\s+Khoản\s+(\d+))?(?:\s+Điểm\s+([a-zA-Z0-9]+))?\s+(?:của\s+)?(?:Nghị\s+định|Luật|Thông\s+tư)\s+(?:số\s+)?([0-9\/\-a-zA-Z_đĐ]+)",
    re.IGNORECASE,
)


def parse_textual_citation(citation: str) -> str | None:
    """Converts a Vietnamese textual legal citation into standard provision ID."""
    # Try Order 1: Điểm X Khoản Y Điều Z Văn bản W
    m1 = TEXTUAL_PROV_PAT1.search(citation)
    if m1:
        diem, khoan, dieu, doc = m1.groups()
        doc_clean = normalize_provision_id(doc)
        res = f"{doc_clean}_D{dieu}"
        if khoan:
            res += f"_K{khoan}"
        if diem:
            res += f"_D{diem.upper()}"
        return res

    # Try Order 2: Điều Z Khoản Y Điểm X Văn bản W
    m2 = TEXTUAL_PROV_PAT2.search(citation)
    if m2:
        dieu, khoan, diem, doc = m2.groups()
        doc_clean = normalize_provision_id(doc)
        res = f"{doc_clean}_D{dieu}"
        if khoan:
            res += f"_K{khoan}"
        if diem:
            res += f"_D{diem.upper()}"
        return res

    return None


def extract_cited_provisions(
    citations: list[str],
    answer_text: str,
    retrieved_unit_ids: list[str] | None = None,
) -> set[str]:
    """Extracts all recognized statutory provision identifiers from citations and answer text."""
    extracted: set[str] = set()

    # 1. Add direct citations (both raw and canonicalized from text)
    for c in citations:
        c_clean = c.strip()
        if not c_clean:
            continue
        extracted.add(normalize_provision_id(c_clean))
        canon = parse_textual_citation(c_clean)
        if canon:
            extracted.add(canon)

    # 2. Parse textual citations from the answer body
    for m in TEXTUAL_PROV_PAT1.finditer(answer_text):
        diem, khoan, dieu, doc = m.groups()
        doc_clean = normalize_provision_id(doc)
        res = f"{doc_clean}_D{dieu}"
        if khoan:
            res += f"_K{khoan}"
        if diem:
            res += f"_D{diem.upper()}"
        extracted.add(res)

    for m in TEXTUAL_PROV_PAT2.finditer(answer_text):
        dieu, khoan, diem, doc = m.groups()
        doc_clean = normalize_provision_id(doc)
        res = f"{doc_clean}_D{dieu}"
        if khoan:
            res += f"_K{khoan}"
        if diem:
            res += f"_D{diem.upper()}"
        extracted.add(res)

    # 3. Extract standard code IDs from answer text (e.g. 168_2024_ND-CP_D6_K3)
    for match in PROVISION_CODE_PATTERN.finditer(answer_text):
        token = match.group(1)
        if "_D" in token or token.startswith("LUAT_") or "ND_CP" in token:
            extracted.add(normalize_provision_id(token))

    # 4. If nothing was extracted from citations and answer, fallback to retrieved_unit_ids
    if not extracted and retrieved_unit_ids:
        for uid in retrieved_unit_ids:
            extracted.add(normalize_provision_id(uid))

    return extracted


def matches_provision(expected: str, cited_candidates: set[str]) -> bool:
    """Checks if expected provision ID matches any cited provision ID (exact or parent/child match)."""
    norm_expected = normalize_provision_id(expected)
    if norm_expected in cited_candidates:
        return True

    for cand in cited_candidates:
        if norm_expected == cand:
            return True
        # Partial hierarchy match: e.g. expected 168_2024_ND_CP_D6_K3_DA vs cited 168_2024_ND_CP_D6_K3
        if norm_expected.startswith(cand) or cand.startswith(norm_expected):
            return True

    return False


def detect_warning(text: str, custom_keywords: list[str] | None = None) -> bool:
    """Checks if text contains statutory warning flags or amendment notifications."""
    text_lower = text.lower()
    for phrase in WARNING_PHRASES:
        if phrase in text_lower:
            return True

    if custom_keywords:
        for kw in custom_keywords:
            if kw.lower() in text_lower:
                return True

    return False


class DeterministicEvaluator:
    """Evaluates legal answers against expected provisions, fine amounts, and validity flags."""

    def __init__(self, recall_threshold: float = 0.5) -> None:
        self.recall_threshold = recall_threshold

    def evaluate(
        self,
        sample: EvaluationSample,
        generated_answer: str,
        citations: list[str],
        retrieved_unit_ids: list[str] | None = None,
        evidence_warning: str | None = None,
    ) -> DeterministicScore:
        """Executes complete deterministic evaluation of a test case."""
        # 1. Provision Citation Evaluation
        cited_set = extract_cited_provisions(
            citations=citations,
            answer_text=generated_answer,
            retrieved_unit_ids=retrieved_unit_ids,
        )

        matched: list[str] = []
        missing: list[str] = []

        for exp in sample.expected_provision_ids:
            if matches_provision(exp, cited_set):
                matched.append(exp)
            else:
                missing.append(exp)

        # Unexpected provisions (cited but not expected)
        unexpected: list[str] = []
        for cand in cited_set:
            if not any(
                matches_provision(exp, {cand}) for exp in sample.expected_provision_ids
            ):
                unexpected.append(cand)

        total_expected = len(sample.expected_provision_ids)
        total_cited = len(cited_set)

        if total_expected == 0:
            # Out-of-scope question: passing if no hallucinated provisions
            recall = 1.0
            precision = 1.0 if total_cited == 0 else 0.0
        else:
            recall = len(matched) / total_expected
            precision = len(matched) / total_cited if total_cited > 0 else 0.0

        f1 = (
            (2.0 * precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        # 2. Fine Amount Evaluation
        extracted_min, extracted_max = extract_fine_range(generated_answer)

        fine_min_match: bool | None = None
        fine_max_match: bool | None = None
        fine_exact_match: bool | None = None

        if sample.expected_fine_min is not None or sample.expected_fine_max is not None:
            if sample.expected_fine_min is not None:
                fine_min_match = extracted_min == sample.expected_fine_min
            if sample.expected_fine_max is not None:
                fine_max_match = extracted_max == sample.expected_fine_max

            fine_exact_match = (
                (fine_min_match is True or sample.expected_fine_min is None)
                and (fine_max_match is True or sample.expected_fine_max is None)
                and (extracted_min is not None or extracted_max is not None)
            )

        # 3. Validity & Amendment Warning Evaluation
        combined_text = f"{generated_answer} {evidence_warning or ''}"
        warning_detected = detect_warning(
            combined_text, sample.expected_warning_keywords
        )

        warning_match: bool | None = None
        if sample.is_amended_case:
            warning_match = warning_detected
        else:
            warning_match = True

        # 4. Overall Deterministic Pass Decision
        if total_expected == 0:
            # Out-of-scope question
            deterministic_passed = len(unexpected) == 0
        else:
            recall_passed = recall >= self.recall_threshold
            fine_passed = fine_exact_match is not False
            warn_passed = warning_match is not False
            deterministic_passed = bool(recall_passed and fine_passed and warn_passed)

        return DeterministicScore(
            provision_precision=round(precision, 4),
            provision_recall=round(recall, 4),
            provision_f1=round(f1, 4),
            matched_provisions=matched,
            missing_provisions=missing,
            unexpected_provisions=unexpected,
            fine_min_match=fine_min_match,
            fine_max_match=fine_max_match,
            fine_exact_match=fine_exact_match,
            extracted_fine_min=extracted_min,
            extracted_fine_max=extracted_max,
            warning_detected=warning_detected,
            warning_match=warning_match,
            deterministic_passed=deterministic_passed,
        )
