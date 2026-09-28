"""Deterministic Legal Evaluator: Provision Citations, Fine Ranges, and Validity Warnings."""

from __future__ import annotations

import logging
import re
from typing import Any

from src.eval.models import (
    BenchmarkItemEvaluationResult,
    DeterministicBenchmarkItem,
    DeterministicScore,
    EvaluationSample,
    FactualGroundTruth,
    FailureRootCause,
    GenerationAssertions,
    GenerationEvaluationResult,
    RetrievalEvaluationResult,
    RetrievalGroundTruth,
)

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

POINTS_DEDUCTED_PATTERN = re.compile(
    r"trừ\s*(?:điểm\s*giấy\s*phép\s*lái\s*xe|điểm\s*gplx|gplx)?\s*"
    r"(\d+|mười\s*hai|mười|tám|sáu|bốn|hai)\s*điểm",
    re.IGNORECASE,
)

NO_POINTS_PATTERN = re.compile(
    r"không\s*(?:bị\s*)?trừ\s*điểm",
    re.IGNORECASE,
)

SUSPENSION_RANGE_PATTERN = re.compile(
    r"tước\s*(?:quyền\s*sử\s*dụng\s*)?(?:GPLX|giấy\s*phép\s*lái\s*xe|bằng\s*lái(?:\s*xe)?)?\s*"
    r"(?:từ\s*)?(\d+)\s*(?:tháng\s*)?(?:đến|-)\s*(\d+)\s*tháng",
    re.IGNORECASE,
)

SUSPENSION_SINGLE_PATTERN = re.compile(
    r"tước\s*(?:quyền\s*sử\s*dụng\s*)?(?:GPLX|giấy\s*phép\s*lái\s*xe|bằng\s*lái(?:\s*xe)?)?\s*"
    r"(\d+)\s*tháng",
    re.IGNORECASE,
)

PROVISION_CODE_PATTERN = re.compile(
    r"([a-zA-Z0-9_\-]+(?:_D\d+)?(?:_K\d+)?(?:_D[a-zA-Z0-9]+)?)"
)

# Textual Vietnamese citation patterns: "Điểm X Khoản Y Điều Z [Nghị định/Luật W]"
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

REFUSAL_PHRASES = [
    "không thuộc phạm vi",
    "ngoài phạm vi",
    "nằm ngoài phạm vi",
    "không điều chỉnh",
    "không áp dụng",
    "không có thẩm quyền",
    "không quy định xử phạt",
    "không bị phạt",
    "không có chế tài",
    "không xử phạt",
    "chưa có quy định xử phạt",
    "chỉ hỗ trợ",
    "chỉ giải đáp",
    "không hỗ trợ",
]

WORD_TO_NUMBER = {
    "hai": 2,
    "bốn": 4,
    "sáu": 6,
    "tám": 8,
    "mười": 10,
    "mười hai": 12,
}


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
        val = val * 1_000_000

    return val


def extract_fine_range(text: str) -> tuple[int | None, int | None]:
    """Extracts minimum and maximum fine amounts in VND from text."""
    if not text:
        return None, None

    clean_text = (
        text.replace("**", " ").replace("*", " ").replace("_", " ").replace("#", " ")
    )

    # 1. Try range pattern: "từ X đến Y [đồng/triệu]"
    range_match = FINE_RANGE_PATTERN.search(clean_text)
    if range_match:
        num1, unit1, num2, unit2 = range_match.groups()
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


def extract_points_deducted(text: str) -> int | None:
    """Extracts driving license points deducted from answer text."""
    if not text:
        return None
    if NO_POINTS_PATTERN.search(text):
        return 0
    match = POINTS_DEDUCTED_PATTERN.search(text)
    if not match:
        return None
    raw_val = match.group(1).lower().strip()
    if raw_val.isdigit():
        return int(raw_val)
    return WORD_TO_NUMBER.get(raw_val)


def extract_license_suspension(text: str) -> tuple[int | None, int | None]:
    """Extracts driving license suspension months from answer text."""
    if not text:
        return None, None

    range_match = SUSPENSION_RANGE_PATTERN.search(text)
    if range_match:
        min_m, max_m = range_match.groups()
        return int(min_m), int(max_m)

    single_match = SUSPENSION_SINGLE_PATTERN.search(text)
    if single_match:
        m = int(single_match.group(1))
        return m, m

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

    # 1. Direct citations
    for c in citations:
        c_clean = c.strip()
        if not c_clean:
            continue
        extracted.add(normalize_provision_id(c_clean))
        canon = parse_textual_citation(c_clean)
        if canon:
            extracted.add(canon)

    # 2. Textual citations from answer body
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

    # 3. Standard code IDs from answer text
    for match in PROVISION_CODE_PATTERN.finditer(answer_text):
        token = match.group(1)
        if "_D" in token or token.startswith("LUAT_") or "ND_CP" in token:
            extracted.add(normalize_provision_id(token))

    # 4. Fallback to retrieved_unit_ids if nothing was extracted
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


def detect_refusal(text: str) -> bool:
    """Checks if answer contains out-of-scope refusal language."""
    text_lower = text.lower()
    return any(p in text_lower for p in REFUSAL_PHRASES)


# ============================================================================
# Core Decoupled Deterministic Evaluation Engine (Mode 1 & Mode 2)
# ============================================================================


def evaluate_retrieval(
    ground_truth: RetrievalGroundTruth,
    retrieved_node_ids: list[str],
) -> RetrievalEvaluationResult:
    """Evaluates retrieval layer against authoritative ground truth using Set Theory."""
    retrieved_set = {normalize_provision_id(nid) for nid in retrieved_node_ids}

    # 1. Must-have checking
    must_have_matched = [
        m
        for m in ground_truth.must_have_node_ids
        if matches_provision(m, retrieved_set)
    ]
    must_have_missing = [
        m for m in ground_truth.must_have_node_ids if m not in must_have_matched
    ]
    total_must_have = len(ground_truth.must_have_node_ids)
    recall = len(must_have_matched) / total_must_have if total_must_have > 0 else 1.0

    # 2. Must-not-have collision checking (Noise & Collision Filter)
    must_not_have_detected = [
        f
        for f in ground_truth.must_not_have_node_ids
        if matches_provision(f, retrieved_set)
    ]
    total_forbidden = len(ground_truth.must_not_have_node_ids)
    collision_rate = (
        len(must_not_have_detected) / total_forbidden if total_forbidden > 0 else 0.0
    )

    # 3. Optional node matching
    optional_matched = [
        opt
        for opt in ground_truth.optional_node_ids
        if matches_provision(opt, retrieved_set)
    ]

    # Pass rule: recall == 1.0 AND 0 forbidden collisions
    passed = (recall >= 1.0) and (len(must_not_have_detected) == 0)

    return RetrievalEvaluationResult(
        must_have_matched=must_have_matched,
        must_have_missing=must_have_missing,
        must_not_have_detected=must_not_have_detected,
        optional_matched=optional_matched,
        recall=round(recall, 4),
        collision_rate=round(collision_rate, 4),
        passed=passed,
    )


def evaluate_generation(
    ground_truth: FactualGroundTruth,
    assertions: GenerationAssertions,
    generated_answer: str,
    evidence_warning: str | None = None,
) -> GenerationEvaluationResult:
    """Evaluates generation output deterministically via Slot-Filling, Regex, & Noise Filtering."""
    extracted_min, extracted_max = extract_fine_range(generated_answer)
    extracted_points = extract_points_deducted(generated_answer)
    extracted_susp_min, extracted_susp_max = extract_license_suspension(
        generated_answer
    )

    extracted_sanctions_record: dict[str, dict[str, Any]] = {
        "extracted_values": {
            "fine_min": extracted_min,
            "fine_max": extracted_max,
            "points_deducted": extracted_points,
            "license_suspended_months_min": extracted_susp_min,
            "license_suspended_months_max": extracted_susp_max,
        }
    }

    # 1. Vehicle sanctions validation
    vehicle_sanctions_passed: dict[str, bool] = {}
    for vehicle, slot in ground_truth.vehicle_sanctions.items():
        v_passed = True
        if slot.fine_min is not None:
            if extracted_min != slot.fine_min:
                v_passed = False
        if slot.fine_max is not None:
            if extracted_max != slot.fine_max:
                v_passed = False
        if slot.points_deducted is not None:
            if extracted_points != slot.points_deducted:
                v_passed = False
        if slot.license_suspended_months_min is not None:
            if extracted_susp_min != slot.license_suspended_months_min:
                v_passed = False
        if slot.license_suspended_months_max is not None:
            if extracted_susp_max != slot.license_suspended_months_max:
                v_passed = False
        vehicle_sanctions_passed[vehicle] = v_passed

    # 2. Regex assertions matching
    regex_passed: dict[str, bool] = {}
    for pattern in assertions.must_contain_regex:
        matched = bool(re.search(pattern, generated_answer, re.IGNORECASE))
        regex_passed[pattern] = matched

    # 3. Forbidden keywords detection
    forbidden_detected: list[str] = []
    answer_lower = generated_answer.lower()
    for kw in assertions.must_not_contain_keywords:
        if kw.lower() in answer_lower:
            forbidden_detected.append(kw)

    # 4. Citations & Dates
    citations_passed = True
    for cit in ground_truth.required_citations:
        if cit.lower() not in answer_lower:
            # Check partial match on key keywords
            parts = [p.strip() for p in cit.split() if len(p.strip()) > 2]
            if not all(p.lower() in answer_lower for p in parts):
                citations_passed = False
                break

    dates_passed = True
    if ground_truth.exact_dates:
        dates_passed = any(d.lower() in answer_lower for d in ground_truth.exact_dates)

    # 5. Behavioral flags
    refusal_passed = True
    if assertions.is_refusal_expected:
        refusal_passed = detect_refusal(generated_answer)

    amended_warning_passed = True
    if assertions.is_amended_warning_expected:
        combined_text = f"{generated_answer} {evidence_warning or ''}"
        amended_warning_passed = detect_warning(combined_text)

    # All criteria must hold for generation pass
    all_sanctions_ok = (
        all(vehicle_sanctions_passed.values()) if vehicle_sanctions_passed else True
    )
    all_regex_ok = all(regex_passed.values()) if regex_passed else True
    no_forbidden_keywords = len(forbidden_detected) == 0

    passed = bool(
        all_sanctions_ok
        and all_regex_ok
        and no_forbidden_keywords
        and refusal_passed
        and amended_warning_passed
    )

    return GenerationEvaluationResult(
        vehicle_sanctions_passed=vehicle_sanctions_passed,
        extracted_sanctions=extracted_sanctions_record,
        regex_passed=regex_passed,
        forbidden_keywords_detected=forbidden_detected,
        citations_passed=citations_passed,
        dates_passed=dates_passed,
        refusal_passed=refusal_passed,
        amended_warning_passed=amended_warning_passed,
        passed=passed,
    )


def evaluate_benchmark_item(
    item: DeterministicBenchmarkItem,
    retrieved_unit_ids: list[str],
    generated_answer: str | None = None,
    citations: list[str] | None = None,
    evidence_warning: str | None = None,
    mode: str = "e2e",
    execution_time_ms: float = 0.0,
) -> BenchmarkItemEvaluationResult:
    """Evaluates a single benchmark item for either Mode 1 (Retrieval) or Mode 2 (End-to-End)."""
    ret_res = evaluate_retrieval(item.retrieval_gt, retrieved_unit_ids)

    if mode == "retrieval":
        overall_passed = ret_res.passed
        root_cause = FailureRootCause.NONE
        if not overall_passed:
            if ret_res.must_not_have_detected:
                root_cause = FailureRootCause.RETRIEVAL_FORBIDDEN_NODE_COLLISION
            else:
                root_cause = FailureRootCause.RETRIEVAL_MISSING_MUST_HAVE

        return BenchmarkItemEvaluationResult(
            test_id=item.test_id,
            category=item.category,
            question=item.question,
            mode="retrieval",
            retrieval_result=ret_res,
            generation_result=None,
            overall_passed=overall_passed,
            root_cause=root_cause,
            execution_time_ms=execution_time_ms,
        )

    # Mode 2: End-to-End
    gen_res = evaluate_generation(
        ground_truth=item.factual_gt,
        assertions=item.assertions,
        generated_answer=generated_answer or "",
        evidence_warning=evidence_warning,
    )

    overall_passed = ret_res.passed and gen_res.passed
    root_cause = FailureRootCause.NONE

    if not overall_passed:
        if len(ret_res.must_not_have_detected) > 0:
            root_cause = FailureRootCause.RETRIEVAL_FORBIDDEN_NODE_COLLISION
        elif len(ret_res.must_have_missing) > 0:
            root_cause = FailureRootCause.RETRIEVAL_MISSING_MUST_HAVE
        elif not gen_res.refusal_passed:
            root_cause = FailureRootCause.GENERATION_REFUSAL_EXPECTED_FAIL
        elif not gen_res.amended_warning_passed:
            root_cause = FailureRootCause.GENERATION_AMENDMENT_WARNING_MISSING
        elif len(gen_res.forbidden_keywords_detected) > 0:
            root_cause = FailureRootCause.GENERATION_FORBIDDEN_KEYWORD_LEAK
        elif any(not p for p in gen_res.regex_passed.values()):
            root_cause = FailureRootCause.GENERATION_REGEX_UNMATCHED
        elif any(not p for p in gen_res.vehicle_sanctions_passed.values()):
            root_cause = FailureRootCause.GENERATION_SANCTION_MISMATCH
        else:
            root_cause = FailureRootCause.GENERATION_SANCTION_MISMATCH

    return BenchmarkItemEvaluationResult(
        test_id=item.test_id,
        category=item.category,
        question=item.question,
        mode="e2e",
        retrieval_result=ret_res,
        generation_result=gen_res,
        overall_passed=overall_passed,
        root_cause=root_cause,
        execution_time_ms=execution_time_ms,
    )


# ============================================================================
# Legacy Evaluator Adapter (DeterministicEvaluator)
# ============================================================================


class DeterministicEvaluator:
    """Evaluates legal answers against expected provisions, fine amounts, and validity flags (Legacy API)."""

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
        """Executes complete deterministic evaluation of a test case for legacy callers."""
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

        unexpected: list[str] = []
        for cand in cited_set:
            if not any(
                matches_provision(exp, {cand}) for exp in sample.expected_provision_ids
            ):
                unexpected.append(cand)

        total_expected = len(sample.expected_provision_ids)
        total_cited = len(cited_set)

        if total_expected == 0:
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

        combined_text = f"{generated_answer} {evidence_warning or ''}"
        warning_detected = detect_warning(
            combined_text, sample.expected_warning_keywords
        )

        warning_match: bool | None = None
        if sample.is_amended_case:
            warning_match = warning_detected
        else:
            warning_match = True

        if total_expected == 0:
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
