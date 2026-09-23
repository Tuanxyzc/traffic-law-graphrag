"""Evaluation Orchestrator: Executes GraphRAG pipeline and aggregates dual-tier metrics."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from src.eval.deterministic import DeterministicEvaluator
from src.eval.models import (
    CategoryMetricSummary,
    EvaluationCategory,
    EvaluationResult,
    EvaluationSample,
    EvaluationSummary,
    RagasScore,
)
from src.eval.ragas_judge import RagasJudge
from src.pipeline.pipeline import GraphRAGPipeline

logger = logging.getLogger(__name__)


class EvaluationOrchestrator:
    """Coordinates running test samples through GraphRAG pipeline and evaluating dual-tier metrics."""

    def __init__(
        self,
        pipeline: GraphRAGPipeline | None = None,
        deterministic_evaluator: DeterministicEvaluator | None = None,
        ragas_judge: RagasJudge | None = None,
        tier: str = "full",
    ) -> None:
        self.pipeline = pipeline
        self.deterministic_evaluator = (
            deterministic_evaluator or DeterministicEvaluator()
        )
        self.ragas_judge = ragas_judge if tier == "full" else None
        self.tier = tier

    def evaluate_sample(
        self,
        sample: EvaluationSample,
        mock_answer: str | None = None,
        mock_citations: list[str] | None = None,
        mock_contexts: list[str] | None = None,
        mock_unit_ids: list[str] | None = None,
    ) -> EvaluationResult:
        """Executes the pipeline for a single sample and evaluates results."""
        start_time = time.perf_counter()

        if mock_answer is not None:
            # Use provided mock data (for dry runs or tests)
            answer = mock_answer
            citations = mock_citations or []
            contexts = mock_contexts or []
            unit_ids = mock_unit_ids or []
            evidence_warning = None
            latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        else:
            if self.pipeline is None:
                self.pipeline = GraphRAGPipeline()

            res = self.pipeline.run(sample.question)
            answer = res.answer
            citations = res.citations
            contexts = [item.original_chunk_text for item in res.evidence_package.items]
            unit_ids = [item.chunk_id for item in res.evidence_package.items]
            warning_flags = [
                item.warning_flag
                for item in res.evidence_package.items
                if item.warning_flag
            ]
            evidence_warning = " | ".join(warning_flags) if warning_flags else None
            latency_ms = res.execution_time_ms

        # 1. Tier 1: Deterministic evaluation
        det_score = self.deterministic_evaluator.evaluate(
            sample=sample,
            generated_answer=answer,
            citations=citations,
            retrieved_unit_ids=unit_ids,
            evidence_warning=evidence_warning,
        )

        # 2. Tier 2: RAGAS LLM-as-a-Judge evaluation (if tier == 'full')
        rag_score: RagasScore | None = None
        if self.tier == "full":
            if self.ragas_judge is None:
                self.ragas_judge = RagasJudge()
            rag_score = self.ragas_judge.evaluate(
                sample=sample,
                generated_answer=answer,
                retrieved_contexts=contexts,
            )

        # 3. Overall pass determination
        if self.tier == "deterministic":
            overall_passed = det_score.deterministic_passed
        else:
            overall_passed = bool(
                det_score.deterministic_passed
                and rag_score is not None
                and rag_score.ragas_passed
            )

        return EvaluationResult(
            sample=sample,
            generated_answer=answer,
            citations=citations,
            retrieved_contexts=contexts,
            retrieved_unit_ids=unit_ids,
            deterministic_score=det_score,
            ragas_score=rag_score,
            latency_ms=latency_ms,
            overall_passed=overall_passed,
        )

    def evaluate_dataset(self, samples: list[EvaluationSample]) -> EvaluationSummary:
        """Evaluates an entire dataset of test cases and computes aggregate metrics."""
        results: list[EvaluationResult] = []
        total = len(samples)
        logger.info(
            "Starting evaluation benchmark for %d samples (Tier: %s)...",
            total,
            self.tier,
        )

        for idx, sample in enumerate(samples, start=1):
            logger.info(
                "[%d/%d] Evaluating %s: '%s'...", idx, total, sample.id, sample.question
            )
            res = self.evaluate_sample(sample)
            results.append(res)

        # Calculate Aggregates
        passed_samples = sum(1 for r in results if r.overall_passed)
        overall_pass_rate = passed_samples / total if total > 0 else 0.0

        avg_recall = (
            sum(r.deterministic_score.provision_recall for r in results) / total
            if total > 0
            else 0.0
        )
        avg_precision = (
            sum(r.deterministic_score.provision_precision for r in results) / total
            if total > 0
            else 0.0
        )
        avg_f1 = (
            sum(r.deterministic_score.provision_f1 for r in results) / total
            if total > 0
            else 0.0
        )

        # Fine accuracy: fraction of applicable samples where fine matched
        fine_applicable = [
            r for r in results if r.deterministic_score.fine_exact_match is not None
        ]
        fine_acc = (
            sum(
                1
                for r in fine_applicable
                if r.deterministic_score.fine_exact_match is True
            )
            / len(fine_applicable)
            if fine_applicable
            else 1.0
        )

        # Warning accuracy: fraction of amendment cases where warning was properly handled
        warn_applicable = [
            r for r in results if r.deterministic_score.warning_match is not None
        ]
        warn_acc = (
            sum(
                1
                for r in warn_applicable
                if r.deterministic_score.warning_match is True
            )
            / len(warn_applicable)
            if warn_applicable
            else 1.0
        )

        # RAGAS metrics averages
        avg_faithfulness: float | None = None
        avg_relevancy: float | None = None
        avg_ctx_precision: float | None = None
        avg_ctx_recall: float | None = None

        if self.tier == "full":
            rag_results = [r.ragas_score for r in results if r.ragas_score is not None]
            valid_faith = [
                rg.faithfulness for rg in rag_results if rg.faithfulness is not None
            ]
            valid_rel = [
                rg.answer_relevancy
                for rg in rag_results
                if rg.answer_relevancy is not None
            ]
            valid_prec = [
                rg.context_precision
                for rg in rag_results
                if rg.context_precision is not None
            ]
            valid_rec = [
                rg.context_recall for rg in rag_results if rg.context_recall is not None
            ]

            if valid_faith:
                avg_faithfulness = round(sum(valid_faith) / len(valid_faith), 4)
            if valid_rel:
                avg_relevancy = round(sum(valid_rel) / len(valid_rel), 4)
            if valid_prec:
                avg_ctx_precision = round(sum(valid_prec) / len(valid_prec), 4)
            if valid_rec:
                avg_ctx_recall = round(sum(valid_rec) / len(valid_rec), 4)

        avg_latency = sum(r.latency_ms for r in results) / total if total > 0 else 0.0

        # Category breakdown
        category_breakdown: dict[str, CategoryMetricSummary] = {}
        for cat in EvaluationCategory:
            cat_samples = [r for r in results if r.sample.category == cat]
            if not cat_samples:
                continue

            cat_total = len(cat_samples)
            cat_passed = sum(1 for r in cat_samples if r.overall_passed)
            cat_rec = (
                sum(r.deterministic_score.provision_recall for r in cat_samples)
                / cat_total
            )
            cat_prec = (
                sum(r.deterministic_score.provision_precision for r in cat_samples)
                / cat_total
            )

            cat_faith_vals = [
                r.ragas_score.faithfulness
                for r in cat_samples
                if r.ragas_score and r.ragas_score.faithfulness is not None
            ]
            cat_rel_vals = [
                r.ragas_score.answer_relevancy
                for r in cat_samples
                if r.ragas_score and r.ragas_score.answer_relevancy is not None
            ]

            category_breakdown[cat.value] = CategoryMetricSummary(
                total_samples=cat_total,
                passed_samples=cat_passed,
                pass_rate=round(cat_passed / cat_total, 4),
                avg_provision_recall=round(cat_rec, 4),
                avg_provision_precision=round(cat_prec, 4),
                avg_faithfulness=round(sum(cat_faith_vals) / len(cat_faith_vals), 4)
                if cat_faith_vals
                else None,
                avg_answer_relevancy=round(sum(cat_rel_vals) / len(cat_rel_vals), 4)
                if cat_rel_vals
                else None,
            )

        return EvaluationSummary(
            timestamp=datetime.now(timezone.utc).isoformat(),
            tier=self.tier,
            total_samples=total,
            passed_samples=passed_samples,
            overall_pass_rate=round(overall_pass_rate, 4),
            avg_provision_recall=round(avg_recall, 4),
            avg_provision_precision=round(avg_precision, 4),
            avg_provision_f1=round(avg_f1, 4),
            fine_accuracy=round(fine_acc, 4),
            warning_accuracy=round(warn_acc, 4),
            avg_faithfulness=avg_faithfulness,
            avg_answer_relevancy=avg_relevancy,
            avg_context_precision=avg_ctx_precision,
            avg_context_recall=avg_ctx_recall,
            avg_latency_ms=round(avg_latency, 2),
            category_breakdown=category_breakdown,
            results=results,
        )
