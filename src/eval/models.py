"""Data contracts and schemas for GraphRAG Evaluation & Benchmarking."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TestCategory(str, Enum):
    """Categorization of traffic law evaluation test cases."""

    # 6 Benchmark Problem Groups
    THESAURUS_NORMALIZATION = "THESAURUS_NORMALIZATION"  # Chuẩn hóa từ lóng, khẩu ngữ
    KEYWORD_COLLISION = "KEYWORD_COLLISION"  # Va chạm từ khóa hiệu lệnh, công vụ
    ENTITY_EXPANSION = "ENTITY_EXPANSION"  # Mở rộng thực thể xe ô tô, mô tô
    MULTI_HOP_CROSS_DOC = (
        "MULTI_HOP_CROSS_DOC"  # Đa bước liên kết Luật và Nghị định/Thông tư
    )
    TEMPORAL_AMENDMENT = "TEMPORAL_AMENDMENT"  # Điều khoản sửa đổi, hiệu lực lùi
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # Câu hỏi ngoài phạm vi đường bộ

    # Legacy Backward-Compatibility Aliases
    FINE_LOOKUP = "FINE_LOOKUP"  # Tra cứu mức phạt vi phạm
    TEMPORAL_VALIDITY = (
        "TEMPORAL_VALIDITY"  # Hiệu lực ngày tháng, quy định có hiệu lực muộn
    )
    DOCUMENT_AMENDMENT = (
        "DOCUMENT_AMENDMENT"  # Quan hệ sửa đổi, bãi bỏ, thay thế văn bản
    )
    MULTI_HOP_RULE_SANCTION = (
        "MULTI_HOP_RULE_SANCTION"  # Kết hợp Luật cấm + Nghị định xử phạt
    )


# Backward-compatibility alias
EvaluationCategory = TestCategory

# Prevent pytest from attempting to collect TestCategory as a test class
TestCategory.__test__ = False  # type: ignore[attr-defined]


# ============================================================================
# 1. Deterministic Benchmark Data Contracts (Input Schemas)
# ============================================================================


class SanctionSlot(BaseModel):
    """Structured legal sanctions for a vehicle category."""

    model_config = ConfigDict(frozen=True, extra="allow")

    fine_min: int | None = Field(default=None, description="Tiền phạt tối thiểu VNĐ")
    fine_max: int | None = Field(default=None, description="Tiền phạt tối đa VNĐ")
    points_deducted: int | None = Field(default=None, description="Số điểm GPLX bị trừ")
    license_suspended_months: int | None = Field(
        default=None,
        description="Thời gian tước quyền sử dụng GPLX (số tháng)",
    )
    license_suspended_months_min: int | None = Field(
        default=None,
        description="Thời gian tước quyền sử dụng GPLX tối thiểu (số tháng)",
    )
    license_suspended_months_max: int | None = Field(
        default=None,
        description="Thời gian tước quyền sử dụng GPLX tối đa (số tháng)",
    )


class RetrievalGroundTruth(BaseModel):
    """Authoritative set-theoretic ground truth for retrieval evaluation."""

    model_config = ConfigDict(frozen=True)

    must_have_node_ids: list[str] = Field(
        default_factory=list,
        description="Các ID node/chunk bắt buộc phải có trong context",
    )
    optional_node_ids: list[str] = Field(
        default_factory=list, description="Các ID node bổ trợ"
    )
    must_not_have_node_ids: list[str] = Field(
        default_factory=list,
        description="Các ID node cấm xuất hiện (chống rác / sai thực thể)",
    )


class FactualGroundTruth(BaseModel):
    """Factual sanctions, citations, and dates for generation verification."""

    model_config = ConfigDict(frozen=True)

    vehicle_sanctions: dict[str, SanctionSlot] = Field(
        default_factory=dict,
        description="Bảng chế tài chuẩn phân tách theo thực thể xe (xe_o_to, xe_mo_to, xe_dap)",
    )
    required_citations: list[str] = Field(
        default_factory=list,
        description="Các chuỗi trích dẫn điều khoản bắt buộc",
    )
    exact_dates: list[str] = Field(
        default_factory=list, description="Các mốc ngày tháng chuẩn"
    )


class GenerationAssertions(BaseModel):
    """Assertions to verify LLM generation deterministically without judge LLMs."""

    model_config = ConfigDict(frozen=True)

    must_contain_regex: list[str] = Field(
        default_factory=list,
        description="Biểu thức chính quy bắt buộc khớp với câu trả lời",
    )
    must_not_contain_keywords: list[str] = Field(
        default_factory=list,
        description="Các từ ngữ cấm xuất hiện trong output",
    )
    is_refusal_expected: bool = Field(
        default=False, description="True nếu hệ thống bắt buộc phải từ chối"
    )
    is_amended_warning_expected: bool = Field(
        default=False,
        description="True nếu bắt buộc phải cảnh báo quy định đã bị sửa đổi",
    )


class DeterministicBenchmarkItem(BaseModel):
    """Standardized testcase for Deterministic Benchmark."""

    model_config = ConfigDict(frozen=True, extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _coerce_identifiers(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "test_id" not in d and "id" in d:
                d["test_id"] = d["id"]
            if "id" not in d and "test_id" in d:
                d["id"] = d["test_id"]
            return d
        return data

    test_id: str = Field(..., description="Mã định danh duy nhất (TC_xxx)")
    category: TestCategory = Field(..., description="Danh mục kiểm chuẩn pháp lý")
    question: str = Field(..., description="Câu hỏi gốc của người dân")
    retrieval_gt: RetrievalGroundTruth = Field(default_factory=RetrievalGroundTruth)
    factual_gt: FactualGroundTruth = Field(default_factory=FactualGroundTruth)
    assertions: GenerationAssertions = Field(default_factory=GenerationAssertions)
    notes: str | None = Field(default=None, description="Ghi chú mục đích test case")

    def to_legacy_sample(self) -> EvaluationSample:
        """Adapter converting this deterministic item to legacy EvaluationSample."""
        fine_min = None
        fine_max = None
        points = None
        for s in self.factual_gt.vehicle_sanctions.values():
            if s.fine_min is not None:
                fine_min = s.fine_min
            if s.fine_max is not None:
                fine_max = s.fine_max
            if s.points_deducted is not None:
                points = s.points_deducted

        return EvaluationSample(
            id=self.test_id,
            category=self.category,
            question=self.question,
            expected_provision_ids=self.retrieval_gt.must_have_node_ids,
            expected_fine_min=fine_min,
            expected_fine_max=fine_max,
            expected_points_deducted=points,
            is_amended_case=self.assertions.is_amended_warning_expected,
            expected_warning_keywords=[],
            ground_truth_answer=f"Căn cứ: {', '.join(self.factual_gt.required_citations)}",
            notes=self.notes,
        )


# ============================================================================
# 2. Evaluation Results & Root-Cause Attribution Models
# ============================================================================


class FailureRootCause(str, Enum):
    """Categorized root causes of evaluation failure."""

    NONE = "NONE"
    RETRIEVAL_MISSING_MUST_HAVE = "RETRIEVAL_MISSING_MUST_HAVE"
    RETRIEVAL_FORBIDDEN_NODE_COLLISION = "RETRIEVAL_FORBIDDEN_NODE_COLLISION"
    GENERATION_SANCTION_MISMATCH = "GENERATION_SANCTION_MISMATCH"
    GENERATION_REGEX_UNMATCHED = "GENERATION_REGEX_UNMATCHED"
    GENERATION_FORBIDDEN_KEYWORD_LEAK = "GENERATION_FORBIDDEN_KEYWORD_LEAK"
    GENERATION_REFUSAL_EXPECTED_FAIL = "GENERATION_REFUSAL_EXPECTED_FAIL"
    GENERATION_AMENDMENT_WARNING_MISSING = "GENERATION_AMENDMENT_WARNING_MISSING"


class RetrievalEvaluationResult(BaseModel):
    """Evaluation result for retrieval layer (Set-Theoretic)."""

    model_config = ConfigDict(frozen=True)

    must_have_matched: list[str] = Field(default_factory=list)
    must_have_missing: list[str] = Field(default_factory=list)
    must_not_have_detected: list[str] = Field(default_factory=list)
    optional_matched: list[str] = Field(default_factory=list)
    recall: float = Field(default=0.0, ge=0.0, le=1.0)
    collision_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    passed: bool = Field(default=False)


class GenerationEvaluationResult(BaseModel):
    """Evaluation result for generation layer (Slot-Filling & Regex Fact-Checking)."""

    model_config = ConfigDict(frozen=True)

    vehicle_sanctions_passed: dict[str, bool] = Field(default_factory=dict)
    extracted_sanctions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    regex_passed: dict[str, bool] = Field(default_factory=dict)
    forbidden_keywords_detected: list[str] = Field(default_factory=list)
    citations_passed: bool = Field(default=True)
    dates_passed: bool = Field(default=True)
    refusal_passed: bool = Field(default=True)
    amended_warning_passed: bool = Field(default=True)
    passed: bool = Field(default=False)


class BenchmarkItemEvaluationResult(BaseModel):
    """Per-sample benchmark evaluation outcome with failure attribution."""

    model_config = ConfigDict(frozen=True)

    test_id: str
    category: TestCategory
    question: str = Field(default="", description="Original citizen question")
    mode: str = Field(default="e2e", description="'retrieval' or 'e2e'")
    retrieval_result: RetrievalEvaluationResult
    generation_result: GenerationEvaluationResult | None = None
    overall_passed: bool = Field(default=False)
    root_cause: FailureRootCause = Field(default=FailureRootCause.NONE)
    execution_time_ms: float = Field(default=0.0)


class BenchmarkRunSummary(BaseModel):
    """Overall benchmark aggregate summary for CI/CD and reporting."""

    model_config = ConfigDict(frozen=True)

    timestamp: str
    mode: str  # 'retrieval' | 'e2e'
    total_samples: int = Field(default=0)
    passed_samples: int = Field(default=0)
    overall_pass_rate: float = Field(default=0.0)
    retrieval_pass_rate: float = Field(default=0.0)
    generation_pass_rate: float | None = None
    root_cause_counts: dict[str, int] = Field(default_factory=dict)
    category_breakdown: dict[str, dict[str, Any]] = Field(default_factory=dict)
    results: list[BenchmarkItemEvaluationResult] = Field(default_factory=list)


# ============================================================================
# 3. Legacy Models Preserved for Backward Compatibility
# ============================================================================


class EvaluationSample(BaseModel):
    """A single legal evaluation test case with ground truth (Legacy)."""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_deterministic_dict(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "id" not in d and "test_id" in d:
                d["id"] = d["test_id"]
            if "ground_truth_answer" not in d:
                d["ground_truth_answer"] = d.get("notes") or ""
            if "expected_provision_ids" not in d and "retrieval_gt" in d:
                r_gt = d.get("retrieval_gt") or {}
                if isinstance(r_gt, dict):
                    d["expected_provision_ids"] = r_gt.get("must_have_node_ids", [])
            if "expected_fine_min" not in d and "factual_gt" in d:
                f_gt = d.get("factual_gt") or {}
                if isinstance(f_gt, dict):
                    sanc = f_gt.get("vehicle_sanctions", {})
                    for s in sanc.values():
                        if isinstance(s, dict):
                            if s.get("fine_min") is not None:
                                d["expected_fine_min"] = s["fine_min"]
                            if s.get("fine_max") is not None:
                                d["expected_fine_max"] = s["fine_max"]
                            if s.get("points_deducted") is not None:
                                d["expected_points_deducted"] = s["points_deducted"]
            return d
        return data

    id: str = Field(..., description="Unique test case identifier (e.g. TC_001)")
    category: EvaluationCategory = Field(
        ..., description="Evaluation category of this question"
    )
    question: str = Field(
        ..., description="Colloquial citizen question in natural Vietnamese"
    )
    expected_provision_ids: list[str] = Field(
        default_factory=list,
        description="List of authoritative provision IDs required (e.g. ['168_2024_ND-CP_D6_K3_Da'])",
    )
    expected_fine_min: int | None = Field(
        default=None, description="Expected minimum fine in VND (e.g. 800000)"
    )
    expected_fine_max: int | None = Field(
        default=None, description="Expected maximum fine in VND (e.g. 1000000)"
    )
    expected_points_deducted: int | None = Field(
        default=None, description="Expected driving license points deducted if any"
    )
    is_amended_case: bool = Field(
        default=False,
        description="True if the provision has been amended/superseded by another document",
    )
    expected_warning_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords expected in warning banner (e.g. ['hết hiệu lực', 'sửa đổi bởi', 'thay thế'])",
    )
    ground_truth_answer: str = Field(
        ..., description="Standard reference legal answer grounded in statutes"
    )
    notes: str | None = Field(
        default=None, description="Explanatory notes or rationale for this test case"
    )


class DeterministicScore(BaseModel):
    """Tier 1: Deterministic evaluation of legal provision citations and fines (Legacy)."""

    model_config = ConfigDict(frozen=True)

    provision_precision: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Precision of cited provisions"
    )
    provision_recall: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Recall of expected provisions"
    )
    provision_f1: float = Field(
        default=0.0, ge=0.0, le=1.0, description="F1-score of cited provisions"
    )
    matched_provisions: list[str] = Field(
        default_factory=list, description="Provisions both expected and cited"
    )
    missing_provisions: list[str] = Field(
        default_factory=list, description="Provisions expected but NOT cited"
    )
    unexpected_provisions: list[str] = Field(
        default_factory=list, description="Provisions cited but NOT in expected list"
    )

    fine_min_match: bool | None = Field(
        default=None, description="True if extracted minimum fine matches expected"
    )
    fine_max_match: bool | None = Field(
        default=None, description="True if extracted maximum fine matches expected"
    )
    fine_exact_match: bool | None = Field(
        default=None,
        description="True if both min and max fine match expected range exactly",
    )
    extracted_fine_min: int | None = Field(
        default=None, description="Extracted minimum fine in VND from answer"
    )
    extracted_fine_max: int | None = Field(
        default=None, description="Extracted maximum fine in VND from answer"
    )

    warning_detected: bool = Field(
        default=False,
        description="True if warning about validity or amendment was found in answer/evidence",
    )
    warning_match: bool | None = Field(
        default=None,
        description="True if warning detection correctly corresponds to is_amended_case",
    )

    deterministic_passed: bool = Field(
        default=False,
        description="True if all applicable deterministic checks pass",
    )


class RagasScore(BaseModel):
    """Tier 2: LLM-as-a-Judge standard RAGAS metrics (Legacy)."""

    model_config = ConfigDict(frozen=True)

    faithfulness: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Degree to which answer claims are grounded in retrieved contexts",
    )
    answer_relevancy: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Degree to which answer addresses the user's question",
    )
    context_precision: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Rank-weighted proportion of retrieved contexts relevant to ground truth",
    )
    context_recall: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Proportion of ground truth statements grounded in retrieved contexts",
    )
    ragas_passed: bool = Field(
        default=False,
        description="True if all computed RAGAS scores meet minimum thresholds",
    )
    error_message: str | None = Field(
        default=None, description="Error message if LLM judging failed or timed out"
    )


class EvaluationResult(BaseModel):
    """Combined evaluation result for an individual test case (Legacy)."""

    model_config = ConfigDict(frozen=True)

    sample: EvaluationSample = Field(..., description="Original test case sample")
    generated_answer: str = Field(
        ..., description="Final answer produced by GraphRAG pipeline"
    )
    citations: list[str] = Field(
        default_factory=list, description="Citations generated by pipeline"
    )
    retrieved_contexts: list[str] = Field(
        default_factory=list, description="Context chunks used in evidence package"
    )
    retrieved_unit_ids: list[str] = Field(
        default_factory=list, description="IDs of semantic units retrieved"
    )
    deterministic_score: DeterministicScore = Field(
        ..., description="Tier 1 deterministic metrics"
    )
    ragas_score: RagasScore | None = Field(
        default=None, description="Tier 2 RAGAS metrics (None if tier=deterministic)"
    )
    latency_ms: float = Field(
        default=0.0, description="Pipeline query execution time in milliseconds"
    )
    overall_passed: bool = Field(
        default=False,
        description="Overall pass status considering both deterministic and RAGAS criteria",
    )


class CategoryMetricSummary(BaseModel):
    """Aggregated evaluation metrics for a specific category (Legacy)."""

    model_config = ConfigDict(frozen=True)

    total_samples: int = Field(default=0)
    passed_samples: int = Field(default=0)
    pass_rate: float = Field(default=0.0)
    avg_provision_recall: float = Field(default=0.0)
    avg_provision_precision: float = Field(default=0.0)
    avg_faithfulness: float | None = Field(default=None)
    avg_answer_relevancy: float | None = Field(default=None)


class EvaluationSummary(BaseModel):
    """Aggregate benchmark report across all executed evaluation samples (Legacy)."""

    model_config = ConfigDict(frozen=True)

    timestamp: str = Field(..., description="Execution ISO timestamp")
    tier: str = Field(
        default="full",
        description="Evaluation tier executed: 'deterministic' or 'full'",
    )
    total_samples: int = Field(default=0, description="Total test cases evaluated")
    passed_samples: int = Field(default=0, description="Total passed test cases")
    overall_pass_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Overall proportion of tests passed"
    )

    avg_provision_recall: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Macro-average provision recall across samples",
    )
    avg_provision_precision: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Macro-average provision precision across samples",
    )
    avg_provision_f1: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Macro-average provision F1 score across samples",
    )
    fine_accuracy: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Proportion of applicable cases with exact fine match",
    )
    warning_accuracy: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Proportion of amendment/validity warnings correctly signaled",
    )

    avg_faithfulness: float | None = Field(
        default=None, description="Macro-average RAGAS faithfulness"
    )
    avg_answer_relevancy: float | None = Field(
        default=None, description="Macro-average RAGAS answer relevancy"
    )
    avg_context_precision: float | None = Field(
        default=None, description="Macro-average RAGAS context precision"
    )
    avg_context_recall: float | None = Field(
        default=None, description="Macro-average RAGAS context recall"
    )

    avg_latency_ms: float = Field(
        default=0.0, description="Average pipeline execution latency in ms"
    )
    category_breakdown: dict[str, CategoryMetricSummary] = Field(
        default_factory=dict, description="Metric breakdown by category"
    )
    results: list[EvaluationResult] = Field(
        default_factory=list, description="Per-sample evaluation records"
    )
