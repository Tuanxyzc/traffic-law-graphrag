"""Data contracts and Pydantic models for the GraphRAG pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LegalValidityStatus(str, Enum):
    """Statutory validity status of a legal provision."""

    DANG_CO_HIEU_LUC = "DANG_CO_HIEU_LUC"
    CHUA_CO_HIEU_LUC = "CHUA_CO_HIEU_LUC"
    HET_HIEU_LUC = "HET_HIEU_LUC"
    DA_BI_THAY_THE = "DA_BI_THAY_THE"
    DA_BI_BAI_BO = "DA_BI_BAI_BO"
    KHONG_XAC_DINH = "KHONG_XAC_DINH"


class RewrittenQuery(BaseModel):
    """Citizen query rewritten into formal statutory nomenclature."""

    model_config = ConfigDict(frozen=True)

    original_query: str = Field(..., description="Raw colloquial citizen query")
    search_query: str = Field(
        ..., description="Query translated into formal legal statutory terminology"
    )
    rule_query: str | None = Field(
        default=None,
        description="Query targeted at rules & prohibitions (Luật 36/2024/QH15)",
    )
    sanction_query: str | None = Field(
        default=None,
        description="Query targeted at administrative sanctions, fines, and point deductions (Nghị định 168/2024/NĐ-CP)",
    )
    identified_keywords: list[str] = Field(
        default_factory=list, description="Extracted legal concepts/terms"
    )
    intent: Literal[
        "violation_sanction", "document_amendment", "general_rule", "system_meta_query"
    ] = Field(
        default="violation_sanction",
        description="Classified query intent: violation_sanction, document_amendment, general_rule, or system_meta_query",
    )
    source_doc: str | None = Field(
        default=None,
        description="Source/amending document ID or number if identified (e.g. '238_2026_ND-CP' or '238')",
    )
    target_doc: str | None = Field(
        default=None,
        description="Target/amended document ID or number if identified (e.g. '168_2024_ND-CP' or '168')",
    )


class DocumentAmendmentItem(BaseModel):
    """A specific statutory provision amended between documents."""

    model_config = ConfigDict(frozen=True)

    target_id: str = Field(
        ..., description="Target provision ID (Point/Clause/Article) being amended"
    )
    target_title: str | None = Field(
        default=None, description="Target provision title/name if available"
    )
    article_id: str | None = Field(
        default=None, description="Parent article ID containing this provision"
    )
    article_title: str | None = Field(default=None, description="Parent article title")
    operation: str = Field(
        ..., description="Amendment operation: SUA_DOI, THAY_THE, BAI_BO, THEM_MOI"
    )
    instruction: str = Field(
        ..., description="Statutory instruction detailing the amendment"
    )
    replacement_content: str | None = Field(
        default=None, description="New replacement text payload"
    )
    old_phrase: str | None = Field(
        default=None, description="Original phrase being replaced"
    )
    new_phrase: str | None = Field(
        default=None, description="New phrase replacing the old phrase"
    )


class AmendmentRecord(BaseModel):
    """Historical or active legal amendment affecting a provision."""

    model_config = ConfigDict(frozen=True)

    operation: str = Field(
        ..., description="Amendment operation: SUA_DOI, THAY_THE, BAI_BO, THEM_MOI"
    )
    instruction: str = Field(
        ..., description="Raw statutory instruction describing the amendment"
    )
    by_document: str | None = Field(
        default=None, description="Modifying legal document ID/number"
    )
    effective_from: str | None = Field(
        default=None, description="Effective date of the amendment"
    )
    replacement_text: str | None = Field(
        default=None,
        description="The actual replacement text/statutory wording resulting from this amendment",
    )
    source_provision_id: str | None = Field(
        default=None,
        description="ID of the amending clause/point where the amendment instruction originates",
    )
    target_provision_id: str | None = Field(
        default=None,
        description="ID of the original provision being amended (if known)",
    )
    direction: str = Field(
        default="INCOMING",
        description="Direction of amendment: INCOMING (target is amended) or OUTGOING (target amends another provision)",
    )


class ReferencedProvision(BaseModel):
    """1-hop statutory cross-reference linked via [:THAM_CHIEU] etc."""

    model_config = ConfigDict(frozen=True)

    target_id: str = Field(..., description="Target provision node ID in Neo4j")
    relation_type: str = Field(
        default="THAM_CHIEU", description="Relation type (THAM_CHIEU, CAN_CU_VAO, etc.)"
    )
    document_id: str | None = Field(
        default=None, description="Parent document identifier"
    )
    title: str | None = Field(
        default=None, description="Title/number of referenced provision"
    )
    content: str | None = Field(
        default=None, description="Authoritative statutory text of referenced provision"
    )
    direction: str = Field(
        default="OUTGOING", description="Direction of reference: OUTGOING or INCOMING"
    )


class ValidatedProvision(BaseModel):
    """Statutory provision validated via Neo4j graph traversal with temporal status."""

    model_config = ConfigDict(frozen=True)

    provision_id: str = Field(
        ..., description="Target node ID in Neo4j (Point, Clause, or Article)"
    )
    level: str = Field(..., description="Hierarchy level: POINT, CLAUSE, ARTICLE")
    status: LegalValidityStatus = Field(default=LegalValidityStatus.KHONG_XAC_DINH)
    is_current: bool = Field(
        default=True, description="True if provision version is currently active"
    )
    version_id: str | None = Field(
        default=None, description="ProvisionVersion node ID if present"
    )
    valid_from: str | None = Field(
        default=None, description="Date from which version is effective"
    )
    valid_to: str | None = Field(
        default=None, description="Date when version expired or was superseded"
    )
    content_text: str = Field(..., description="Authoritative statutory text")
    parent_article_id: str | None = Field(default=None, description="Parent Article ID")
    parent_article_title: str | None = Field(
        default=None, description="Parent Article Title"
    )
    parent_clause_id: str | None = Field(default=None, description="Parent Clause ID")
    parent_clause_number: str | None = Field(
        default=None, description="Parent Clause Number"
    )
    parent_clause_content: str | None = Field(
        default=None,
        description="Authoritative statutory preamble of parent clause containing fine amounts",
    )
    document_id: str | None = Field(default=None, description="Document ID")
    document_title: str | None = Field(default=None, description="Document Title")
    amendments: list[AmendmentRecord] = Field(
        default_factory=list, description="Direct amendments"
    )
    cross_references: list[ReferencedProvision] = Field(
        default_factory=list, description="1-hop references"
    )


class SubGraphNode(BaseModel):
    """Node in the validated and expanded knowledge subgraph for visualization."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique node ID in the graph")
    label: str = Field(
        ...,
        description="Primary label of the node (Document, Article, Clause, Point, ProvisionVersion, SemanticUnit, AmendmentAction)",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Key-value attributes of the node"
    )


class SubGraphRelationship(BaseModel):
    """Directed relationship between nodes in the knowledge subgraph."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")
    type: str = Field(
        ...,
        description="Relationship type (CONTAINS_ARTICLE, CONTAINS_CLAUSE, CONTAINS_POINT, HAS_VERSION, EXTRACTED_FROM, REFERENCES, AMENDS, etc.)",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Attributes of the relationship"
    )


class SubGraph(BaseModel):
    """Complete validated and expanded subgraph structure for visualization."""

    model_config = ConfigDict(frozen=True)

    nodes: list[SubGraphNode] = Field(
        default_factory=list, description="List of validated and expanded graph nodes"
    )
    relationships: list[SubGraphRelationship] = Field(
        default_factory=list,
        description="List of validated and expanded graph relationships",
    )


class EvidenceItem(BaseModel):
    """Pairing of a retrieved chunk with its validated graph provision and warning flag."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(..., description="Source SemanticUnit chunk ID")
    original_chunk_text: str = Field(
        ..., description="Text from the retrieved semantic chunk"
    )
    validated_provision: ValidatedProvision = Field(
        ..., description="Graph-validated provision data"
    )
    warning_flag: str | None = Field(
        default=None, description="Warning if expired or superseded"
    )
    superseding_text: str | None = Field(
        default=None, description="Replacement provision text if superseded"
    )


class EvidencePackage(BaseModel):
    """Consolidated evidence bundle ready for LLM generation."""

    model_config = ConfigDict(frozen=True)

    user_query: str = Field(..., description="Original citizen query")
    rewritten_query: str = Field(..., description="Statutory search query")
    items: list[EvidenceItem] = Field(
        default_factory=list, description="List of validated evidence items"
    )
    total_chunks_retrieved: int = Field(
        default=0, description="Total chunks from vector/BM25 retrieval"
    )
    total_valid_provisions: int = Field(
        default=0, description="Total provisions confirmed in graph"
    )
    has_superseded_provisions: bool = Field(
        default=False, description="True if any provision is superseded/expired"
    )
    subgraph: SubGraph = Field(
        default_factory=SubGraph,
        description="Validated and expanded knowledge subgraph",
    )
    document_amendments: list[DocumentAmendmentItem] = Field(
        default_factory=list,
        description="Direct document amendments traversed from knowledge graph",
    )
    system_documents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full catalog of legal documents in the system database (for system_meta_query)",
    )


class GenerationResult(BaseModel):
    """Intermediate generation result from AnswerGenerator."""

    model_config = ConfigDict(frozen=True)

    answer: str = Field(..., description="Grounded answer text")
    citations: list[str] = Field(
        default_factory=list, description="Extracted statutory citations"
    )
    raw_response: str | None = Field(
        default=None, description="Raw LLM response string"
    )


class PipelineResult(BaseModel):
    """Complete end-to-end result returned by GraphRAGPipeline."""

    model_config = ConfigDict(frozen=True)

    user_query: str = Field(..., description="Initial citizen question")
    rewritten_query: str = Field(..., description="Formal legal search query")
    answer: str = Field(..., description="Grounded final legal answer generated by LLM")
    citations: list[str] = Field(
        default_factory=list, description="List of cited Articles/Clauses"
    )
    evidence_package: EvidencePackage = Field(
        ..., description="Supporting evidence package"
    )
    subgraph: SubGraph = Field(
        default_factory=SubGraph,
        description="Validated and expanded knowledge subgraph",
    )
    execution_time_ms: float = Field(
        ..., description="Total pipeline execution latency in milliseconds"
    )
