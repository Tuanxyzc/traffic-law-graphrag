"""Unit tests for pipeline configuration and data models."""

from __future__ import annotations

import os
from unittest.mock import patch

from src.pipeline.config import PipelineConfig
from src.pipeline.models import (
    AmendmentRecord,
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


def test_pipeline_config_defaults() -> None:
    """Test default values of PipelineConfig."""
    config = PipelineConfig()
    assert config.model_name == "gemini-2.5-flash"
    assert config.rewrite_model_name == "gemini-2.5-flash"
    assert config.temperature_rewrite == 0.1
    assert config.temperature_generate == 0.2
    assert config.max_retries == 5
    assert config.top_k == 4
    assert config.max_reference_hops == 2
    assert config.include_superseded_warning is True


def test_pipeline_config_from_env() -> None:
    """Test PipelineConfig overrides from environment variables."""
    env_vars = {
        "GEMINI_MODEL": "gemini-1.5-pro",
        "PIPELINE_REWRITE_MODEL": "gemini-1.5-flash",
        "PIPELINE_TEMP_REWRITE": "0.05",
        "PIPELINE_TEMP_GENERATE": "0.3",
        "PIPELINE_MAX_RETRIES": "3",
        "PIPELINE_TOP_K": "10",
        "PIPELINE_MAX_REF_HOPS": "2",
        "PIPELINE_SUPERSEDED_WARNING": "false",
        "NEO4J_URI": "bolt://custom:7687",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        config = PipelineConfig.from_env()
        assert config.model_name == "gemini-1.5-pro"
        assert config.rewrite_model_name == "gemini-1.5-flash"
        assert config.temperature_rewrite == 0.05
        assert config.temperature_generate == 0.3
        assert config.max_retries == 3
        assert config.top_k == 10
        assert config.max_reference_hops == 2
        assert config.include_superseded_warning is False
        assert config.neo4j_uri == "bolt://custom:7687"


def test_legal_validity_status_enum() -> None:
    """Test LegalValidityStatus enum values."""
    assert LegalValidityStatus.DANG_CO_HIEU_LUC.value == "DANG_CO_HIEU_LUC"
    assert LegalValidityStatus.HET_HIEU_LUC.value == "HET_HIEU_LUC"
    assert LegalValidityStatus.DA_BI_THAY_THE.value == "DA_BI_THAY_THE"
    assert LegalValidityStatus.DA_BI_BAI_BO.value == "DA_BI_BAI_BO"
    assert LegalValidityStatus.KHONG_XAC_DINH.value == "KHONG_XAC_DINH"


def test_rewritten_query_model() -> None:
    """Test RewrittenQuery construction and serialization."""
    rq = RewrittenQuery(
        original_query="vượt đèn đỏ xe máy",
        search_query="không chấp hành hiệu lệnh của đèn tín hiệu giao thông xe mô tô",
        rule_query="quy tắc giao thông đèn tín hiệu giao thông",
        sanction_query="mức phạt tiền trừ điểm giấy phép lái xe vượt đèn đỏ xe mô tô",
        identified_keywords=["đèn tín hiệu giao thông", "xe mô tô"],
    )
    assert rq.original_query == "vượt đèn đỏ xe máy"
    assert rq.rule_query == "quy tắc giao thông đèn tín hiệu giao thông"
    assert (
        rq.sanction_query
        == "mức phạt tiền trừ điểm giấy phép lái xe vượt đèn đỏ xe mô tô"
    )
    assert len(rq.identified_keywords) == 2
    data = rq.model_dump()
    assert (
        data["search_query"]
        == "không chấp hành hiệu lệnh của đèn tín hiệu giao thông xe mô tô"
    )
    assert data["rule_query"] == "quy tắc giao thông đèn tín hiệu giao thông"
    assert (
        data["sanction_query"]
        == "mức phạt tiền trừ điểm giấy phép lái xe vượt đèn đỏ xe mô tô"
    )


def test_validated_provision_model() -> None:
    """Test ValidatedProvision construction and relations."""
    amendment = AmendmentRecord(
        operation="SUA_DOI",
        instruction="Sửa đổi Điểm a Khoản 1",
        by_document="168/2024/ND-CP",
        effective_from="2025-01-01",
    )
    reference = ReferencedProvision(
        target_id="168_2024_ND-CP_D6_K1",
        relation_type="THAM_CHIEU",
        content="Nội dung điều khoản tham chiếu",
    )
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D5_K1_Da",
        level="POINT",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        valid_from="2025-01-01",
        content_text="Phạt tiền từ 200.000 đến 400.000 đồng...",
        parent_article_id="168_2024_ND-CP_D5",
        parent_article_title="Điều 5. Xử phạt người điều khiển xe ô tô",
        amendments=[amendment],
        cross_references=[reference],
    )
    assert vp.provision_id == "168_2024_ND-CP_D5_K1_Da"
    assert vp.status == LegalValidityStatus.DANG_CO_HIEU_LUC
    assert len(vp.amendments) == 1
    assert len(vp.cross_references) == 1
    assert vp.amendments[0].operation == "SUA_DOI"
    assert vp.cross_references[0].target_id == "168_2024_ND-CP_D6_K1"


def test_evidence_package_and_pipeline_result() -> None:
    """Test EvidencePackage and PipelineResult serialization."""
    vp = ValidatedProvision(
        provision_id="168_2024_ND-CP_D5_K1_Da",
        level="POINT",
        status=LegalValidityStatus.DA_BI_THAY_THE,
        is_current=False,
        content_text="Quy định cũ...",
    )
    item = EvidenceItem(
        chunk_id="chunk-1",
        original_chunk_text="Nội dung chunk gốc",
        validated_provision=vp,
        warning_flag="[CẢNH BÁO: ĐÃ BỊ THAY THẾ]",
        superseding_text="Quy định mới thay thế...",
    )
    pkg = EvidencePackage(
        user_query="Vượt đèn đỏ",
        rewritten_query="Không chấp hành tín hiệu",
        items=[item],
        total_chunks_retrieved=1,
        total_valid_provisions=1,
        has_superseded_provisions=True,
    )
    assert pkg.has_superseded_provisions is True
    assert len(pkg.items) == 1
    assert pkg.items[0].warning_flag is not None

    gen_res = GenerationResult(
        answer="Mức phạt là từ 800.000 đến 1.000.000 đồng.",
        citations=["Điểm a Khoản 1 Điều 5"],
    )

    pipeline_res = PipelineResult(
        user_query=pkg.user_query,
        rewritten_query=pkg.rewritten_query,
        answer=gen_res.answer,
        citations=gen_res.citations,
        evidence_package=pkg,
        execution_time_ms=250.5,
    )
    assert pipeline_res.execution_time_ms == 250.5
    assert pipeline_res.citations == ["Điểm a Khoản 1 Điều 5"]
    json_str = pipeline_res.model_dump_json()
    assert "Mức phạt" in json_str
    assert "subgraph" in json_str


def test_subgraph_models() -> None:
    """Test SubGraphNode, SubGraphRelationship, and SubGraph models serialization."""
    node1 = SubGraphNode(
        id="168_2024_ND-CP_D6_K1",
        label="Clause",
        properties={"number": "1", "title": "Xử phạt xe mô tô"},
    )
    node2 = SubGraphNode(
        id="168_2024_ND-CP_D6_K1_Da",
        label="Point",
        properties={"level": "POINT", "status": "DANG_CO_HIEU_LUC"},
    )
    rel = SubGraphRelationship(
        source="168_2024_ND-CP_D6_K1",
        target="168_2024_ND-CP_D6_K1_Da",
        type="CONTAINS_POINT",
        properties={},
    )
    subgraph = SubGraph(
        nodes=[node1, node2],
        relationships=[rel],
    )
    assert len(subgraph.nodes) == 2
    assert len(subgraph.relationships) == 1
    assert subgraph.relationships[0].type == "CONTAINS_POINT"

    data = subgraph.model_dump()
    assert len(data["nodes"]) == 2
    assert len(data["relationships"]) == 1
    assert data["nodes"][0]["id"] == "168_2024_ND-CP_D6_K1"
    assert data["relationships"][0]["source"] == "168_2024_ND-CP_D6_K1"
