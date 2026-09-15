"""GraphRAG Pipeline public API."""

from __future__ import annotations

from src.pipeline.config import PipelineConfig
from src.pipeline.evidence_builder import EvidenceBuilder
from src.pipeline.generator import AnswerGenerator
from src.pipeline.graph_validator import GraphValidator
from src.pipeline.models import (
    AmendmentRecord,
    DocumentAmendmentItem,
    EvidenceItem,
    EvidencePackage,
    GenerationResult,
    LegalValidityStatus,
    PipelineResult,
    ReferencedProvision,
    RewrittenQuery,
    SubGraph,
    SubGraphNode,
    SubGraphRelationship,
    ValidatedProvision,
)
from src.pipeline.pipeline import GraphRAGPipeline
from src.pipeline.rewriter import QueryRewriter

__all__ = [
    "AmendmentRecord",
    "AnswerGenerator",
    "DocumentAmendmentItem",
    "EvidenceBuilder",
    "EvidenceItem",
    "EvidencePackage",
    "GenerationResult",
    "GraphRAGPipeline",
    "GraphValidator",
    "LegalValidityStatus",
    "PipelineConfig",
    "PipelineResult",
    "QueryRewriter",
    "ReferencedProvision",
    "RewrittenQuery",
    "SubGraph",
    "SubGraphNode",
    "SubGraphRelationship",
    "ValidatedProvision",
]
