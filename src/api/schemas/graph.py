"""Pydantic schemas for Knowledge Graph inspection endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentMetaResponse(BaseModel):
    """Metadata of a legal document in Neo4j."""

    id: str = Field(..., description="Canonical document ID (e.g. '168_2024_ND-CP')")
    so_hieu: str | None = Field(default=None, description="Official statutory number (e.g. '168/2024/NĐ-CP')")
    ten: str | None = Field(default=None, description="Official statutory title")
    loai: str | None = Field(default=None, description="Type of document (Nghị định, Luật, Thông tư)")
    ngay_ban_hanh: str | None = Field(default=None, description="Date of issuance (YYYY-MM-DD)")
    ngay_hieu_luc: str | None = Field(default=None, description="Effective date (YYYY-MM-DD)")
    ngay_het_hieu_luc: str | None = Field(default=None, description="Expiry date if applicable")
    status: str | None = Field(default=None, description="General legal status")
    total_articles: int = Field(default=0, description="Total article count in document")


class ProvisionVersionSchema(BaseModel):
    """Temporal version status of a statutory provision."""

    version_id: str | None = None
    is_current: bool = True
    valid_from: str | None = None
    valid_to: str | None = None
    statutory_status: str | None = None


class CrossReferenceSchema(BaseModel):
    """1-hop statutory cross-reference."""

    target_id: str
    target_title: str | None = None
    relation_type: str = "THAM_CHIEU"
    content: str | None = None
    direction: str = "OUTGOING"


class AmendmentRecordSchema(BaseModel):
    """Direct amendment action affecting a provision."""

    operation: str
    by_document: str | None = None
    instruction: str | None = None
    replacement_text: str | None = None
    effective_from: str | None = None
    direction: str = "INCOMING"


class ProvisionDetailResponse(BaseModel):
    """Comprehensive detail and temporal status of a statutory provision."""

    provision_id: str = Field(..., description="Canonical ID of provision (e.g. '168_2024_ND-CP_D5_K1_Da')")
    level: str = Field(..., description="Hierarchy level (Point, Clause, Article, Document)")
    document_id: str | None = None
    document_title: str | None = None
    parent_article_id: str | None = None
    parent_article_title: str | None = None
    parent_clause_id: str | None = None
    parent_clause_number: str | None = None
    content: str | None = None
    current_version: ProvisionVersionSchema | None = None
    cross_references: list[CrossReferenceSchema] = Field(default_factory=list)
    amendments: list[AmendmentRecordSchema] = Field(default_factory=list)
