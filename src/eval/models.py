"""Data contracts and schemas for GraphRAG Evaluation & Benchmarking."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EvaluationCategory(str, Enum):
    """Categorization of traffic law evaluation test cases."""

    FINE_LOOKUP = "FINE_LOOKUP"
    TEMPORAL_VALIDITY = "TEMPORAL_VALIDITY"
    DOCUMENT_AMENDMENT = "DOCUMENT_AMENDMENT"
    MULTI_HOP_RULE_SANCTION = "MULTI_HOP_RULE_SANCTION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class EvaluationSample(BaseModel):
    """A single legal evaluation test case with ground truth."""

    model_config = ConfigDict(frozen=True)

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
    """Tier 1: Deterministic evaluation of legal provision citations and fines."""

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
    """Tier 2: LLM-as-a-Judge standard RAGAS metrics."""

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
    """Combined evaluation result for an individual test case."""

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
    """Aggregated evaluation metrics for a specific category."""

    model_config = ConfigDict(frozen=True)

    total_samples: int = Field(default=0)
    passed_samples: int = Field(default=0)
    pass_rate: float = Field(default=0.0)
    avg_provision_recall: float = Field(default=0.0)
    avg_provision_precision: float = Field(default=0.0)
    avg_faithfulness: float | None = Field(default=None)
    avg_answer_relevancy: float | None = Field(default=None)


class EvaluationSummary(BaseModel):
    """Aggregate benchmark report across all executed evaluation samples."""

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
