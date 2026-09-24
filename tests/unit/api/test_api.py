"""Comprehensive unit and integration tests for FastAPI service layer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from src.api.dependencies import get_neo4j_client, get_pipeline
from src.api.main import app
from src.pipeline.models import (
    EvidencePackage,
    LegalValidityStatus,
    PipelineResult,
    RewrittenQuery,
    SubGraph,
    SubGraphNode,
    SubGraphRelationship,
    ValidatedProvision,
)


@pytest.fixture
def mock_pipeline_result() -> PipelineResult:
    """Creates a mock PipelineResult fixture for query testing."""
    rewritten = RewrittenQuery(
        original_query="vượt đèn đỏ xe máy phạt bao nhiêu",
        search_query="không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        intent="violation_sanction",
        target_entities=["xe_mo_to"],
    )
    subgraph = SubGraph(
        nodes=[
            SubGraphNode(
                id="168_2024_ND-CP_D6_K9_Dc",
                label="Point",
                properties={"tieu_de": "Phạt người điều khiển xe mô tô vượt đèn đỏ"},
            )
        ],
        relationships=[
            SubGraphRelationship(
                source="168_2024_ND-CP_D6_K9_Dc",
                target="168_2024_ND-CP_D6",
                type="CONTAINS_POINT",
            )
        ],
    )
    evidence = EvidencePackage(
        user_query="vượt đèn đỏ xe máy phạt bao nhiêu",
        rewritten_query=rewritten,
        subgraph=subgraph,
    )
    return PipelineResult(
        user_query="vượt đèn đỏ xe máy phạt bao nhiêu",
        rewritten_query=rewritten,
        answer="Hành vi vượt đèn đỏ xe máy bị phạt tiền từ 800.000 đến 1.000.000 đồng theo Điểm c Khoản 9 Điều 6 Nghị định 168/2024/NĐ-CP.",
        citations=["Điểm c Khoản 9 Điều 6 Nghị định 168/2024/NĐ-CP"],
        evidence_package=evidence,
        subgraph=subgraph,
        execution_time_ms=125.4,
        grounding_verified=True,
        verification_warnings=[],
    )


@pytest.fixture
def client() -> TestClient:
    """Returns FastAPI TestClient."""
    return TestClient(app, raise_server_exceptions=False)


# --- 1. Health & Metrics Tests ---


def test_liveness_probe(client: TestClient) -> None:
    """Verifies lightweight /health liveness probe."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Process-Time-Ms" in response.headers
    assert "X-Request-ID" in response.headers


def test_readiness_probe_success(client: TestClient) -> None:
    """Verifies /api/v1/health readiness probe when Neo4j is available."""
    mock_neo4j = MagicMock()
    mock_neo4j.verify_connectivity.return_value = True
    mock_neo4j.uri = "bolt://localhost:7687"

    app.dependency_overrides[get_neo4j_client] = lambda: mock_neo4j
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["neo4j_connected"] is True
        assert data["neo4j_uri"] == "bolt://localhost:7687"
        assert "uptime_seconds" in data
    finally:
        app.dependency_overrides.pop(get_neo4j_client, None)


def test_readiness_probe_degraded(client: TestClient) -> None:
    """Verifies /api/v1/health readiness probe returns 503 when Neo4j is down."""
    mock_neo4j = MagicMock()
    mock_neo4j.verify_connectivity.return_value = False
    mock_neo4j.uri = "bolt://localhost:7687"

    app.dependency_overrides[get_neo4j_client] = lambda: mock_neo4j
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["neo4j_connected"] is False
    finally:
        app.dependency_overrides.pop(get_neo4j_client, None)


def test_metrics_endpoint(client: TestClient) -> None:
    """Verifies /api/v1/metrics returns runtime metrics."""
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "traffic-law-graphrag-api"
    assert "uptime_seconds" in data


# --- 2. Query Endpoints Tests ---


def test_query_sync_success(client: TestClient, mock_pipeline_result: PipelineResult) -> None:
    """Verifies POST /api/v1/query returns 200 with complete structured answer."""
    mock_pipe = MagicMock()
    mock_pipe.run.return_value = mock_pipeline_result

    app.dependency_overrides[get_pipeline] = lambda: mock_pipe
    try:
        payload = {
            "query": "vượt đèn đỏ xe máy phạt bao nhiêu",
            "top_k": 5,
            "include_subgraph": True,
        }
        response = client.post("/api/v1/query", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "vượt đèn đỏ" in data["user_query"]
        assert data["intent"] == "violation_sanction"
        assert "800.000" in data["answer"]
        assert len(data["citations"]) > 0
        assert data["subgraph"] is not None
        assert len(data["subgraph"]["nodes"]) == 1
        assert len(data["subgraph"]["relationships"]) == 1
        assert data["grounding_verified"] is True
    finally:
        app.dependency_overrides.pop(get_pipeline, None)


def test_query_validation_error_empty_query(client: TestClient) -> None:
    """Verifies POST /api/v1/query returns 422 with structured details on invalid input."""
    payload = {"query": "a"}  # min_length is 2
    response = client.post("/api/v1/query", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["code"] == "UNPROCESSABLE_ENTITY"
    assert len(data["details"]) > 0


def test_query_out_of_scope(client: TestClient) -> None:
    """Verifies query classified as out_of_scope returns polite status."""
    rewritten = RewrittenQuery(
        original_query="Xin chào",
        search_query="Xin chào",
        intent="out_of_scope",
    )
    result = PipelineResult(
        user_query="Xin chào",
        rewritten_query=rewritten,
        answer="Chào bạn, tôi là trợ lý tư vấn luật giao thông đường bộ Việt Nam. Bạn cần tìm hiểu quy định hay mức xử phạt nào?",
        citations=[],
        evidence_package=EvidencePackage(user_query="Xin chào", rewritten_query=rewritten),
        execution_time_ms=5.0,
        grounding_verified=True,
    )
    mock_pipe = MagicMock()
    mock_pipe.run.return_value = result

    app.dependency_overrides[get_pipeline] = lambda: mock_pipe
    try:
        response = client.post("/api/v1/query", json={"query": "Xin chào"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "out_of_scope"
        assert data["intent"] == "out_of_scope"
        assert len(data["citations"]) == 0
    finally:
        app.dependency_overrides.pop(get_pipeline, None)


def test_query_streaming_sse(client: TestClient, mock_pipeline_result: PipelineResult) -> None:
    """Verifies POST /api/v1/query/stream emits Server-Sent Events."""
    mock_pipe = MagicMock()
    mock_pipe.run.return_value = mock_pipeline_result

    app.dependency_overrides[get_pipeline] = lambda: mock_pipe
    try:
        payload = {"query": "vượt đèn đỏ xe máy phạt bao nhiêu", "top_k": 3}
        response = client.post("/api/v1/query/stream", json=payload)
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        text_content = response.text
        assert "event: stage" in text_content
        assert "event: token" in text_content
        assert "event: done" in text_content
    finally:
        app.dependency_overrides.pop(get_pipeline, None)


# --- 3. Knowledge Graph Endpoints Tests ---


def test_list_documents(client: TestClient) -> None:
    """Verifies GET /api/v1/graph/documents retrieves document list."""
    mock_neo4j = MagicMock()
    mock_session = MagicMock()
    mock_neo4j.session.return_value.__enter__.return_value = mock_session
    mock_session.run.return_value = [
        {
            "id": "168_2024_ND-CP",
            "so_hieu": "168/2024/NĐ-CP",
            "ten": "Nghị định quy định xử phạt vi phạm hành chính trong lĩnh vực giao thông",
            "loai": "Nghị định",
            "ngay_ban_hanh": "2024-12-26",
            "ngay_hieu_luc": "2025-01-01",
            "ngay_het_hieu_luc": None,
            "status": "DANG_CO_HIEU_LUC",
            "article_count": 52,
        }
    ]

    app.dependency_overrides[get_neo4j_client] = lambda: mock_neo4j
    try:
        response = client.get("/api/v1/graph/documents?skip=0&limit=10")
        assert response.status_code == 200
        docs = response.json()
        assert len(docs) == 1
        assert docs[0]["id"] == "168_2024_ND-CP"
        assert docs[0]["total_articles"] == 52
    finally:
        app.dependency_overrides.pop(get_neo4j_client, None)


def test_get_provision_detail_found(client: TestClient) -> None:
    """Verifies GET /api/v1/graph/provisions/{id} returns details for existing provision."""
    mock_prov = ValidatedProvision(
        provision_id="168_2024_ND-CP_D6_K9_Dc",
        level="Point",
        status=LegalValidityStatus.DANG_CO_HIEU_LUC,
        is_current=True,
        valid_from="2025-01-01",
        content_text="Vượt đèn đỏ",
        document_id="168_2024_ND-CP",
        parent_article_id="168_2024_ND-CP_D6",
    )

    with patch("src.api.services.graph_service.GraphValidator") as mock_val_cls:
        mock_val_inst = MagicMock()
        mock_val_inst.validate_provisions.return_value = [mock_prov]
        mock_val_cls.return_value = mock_val_inst

        # Pass custom service with mocked validator
        mock_neo4j = MagicMock()
        from src.api.dependencies import get_graph_service
        from src.api.services.graph_service import GraphService

        test_graph_svc = GraphService(neo4j_client=mock_neo4j, validator=mock_val_inst)
        app.dependency_overrides[get_graph_service] = lambda: test_graph_svc
        try:
            response = client.get("/api/v1/graph/provisions/168_2024_ND-CP_D6_K9_Dc")
            assert response.status_code == 200
            data = response.json()
            assert data["provision_id"] == "168_2024_ND-CP_D6_K9_Dc"
            assert data["document_id"] == "168_2024_ND-CP"
            assert data["current_version"]["is_current"] is True
        finally:
            app.dependency_overrides.pop(get_graph_service, None)


def test_get_provision_detail_not_found(client: TestClient) -> None:
    """Verifies GET /api/v1/graph/provisions/{id} returns 404 when provision is absent."""
    with patch("src.api.services.graph_service.GraphValidator") as mock_val_cls:
        mock_val_inst = MagicMock()
        mock_val_inst.validate_provisions.return_value = []
        mock_val_cls.return_value = mock_val_inst

        mock_neo4j = MagicMock()
        from src.api.dependencies import get_graph_service
        from src.api.services.graph_service import GraphService

        test_graph_svc = GraphService(neo4j_client=mock_neo4j, validator=mock_val_inst)
        app.dependency_overrides[get_graph_service] = lambda: test_graph_svc
        try:
            response = client.get("/api/v1/graph/provisions/non_existent_id")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_graph_service, None)


def test_get_subgraph(client: TestClient) -> None:
    """Verifies GET /api/v1/graph/subgraph retrieves nodes and edges."""
    mock_neo4j = MagicMock()
    mock_session = MagicMock()
    mock_neo4j.session.return_value.__enter__.return_value = mock_session

    node_mock1 = {"id": "node_1"}
    node_mock2 = {"id": "node_2"}
    rel_mock = MagicMock()
    rel_mock.type = "REFERENCES"
    rel_mock.__iter__.return_value = []

    mock_session.run.return_value = [
        {"n": node_mock1, "r": rel_mock, "m": node_mock2}
    ]

    app.dependency_overrides[get_neo4j_client] = lambda: mock_neo4j
    try:
        response = client.get("/api/v1/graph/subgraph?unit_ids=node_1&unit_ids=node_2")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "relationships" in data
    finally:
        app.dependency_overrides.pop(get_neo4j_client, None)


# --- 4. Corpus Ingestion Endpoints Tests ---


def test_corpus_ingestion_lifecycle(client: TestClient, tmp_path) -> None:
    """Verifies POST /api/v1/ingest/corpus and GET /api/v1/ingest/status/{task_id}."""
    test_json = tmp_path / "test_units.json"
    test_json.write_text(json.dumps([]), encoding="utf-8")

    payload = {
        "json_file_path": str(test_json),
        "batch_size": 10,
        "recreate_index": False,
    }
    response = client.post("/api/v1/ingest/corpus", json=payload)
    assert response.status_code == 202
    data = response.json()
    task_id = data["task_id"]
    assert data["status"] in ("pending", "processing", "completed")

    # Check status endpoint
    status_resp = client.get(f"/api/v1/ingest/status/{task_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["task_id"] == task_id


def test_corpus_ingest_status_not_found(client: TestClient) -> None:
    """Verifies GET /api/v1/ingest/status/{task_id} returns 404 for unknown task."""
    response = client.get("/api/v1/ingest/status/unknown-uuid-123")
    assert response.status_code == 404


# --- 5. Exception Handler Tests ---


def test_neo4j_service_unavailable_handled(client: TestClient) -> None:
    """Verifies Neo4j ServiceUnavailable exception is caught and returns 503."""
    mock_neo4j = MagicMock()
    mock_neo4j.session.side_effect = ServiceUnavailable("Database connection refused")

    app.dependency_overrides[get_neo4j_client] = lambda: mock_neo4j
    try:
        response = client.get("/api/v1/graph/documents")
        assert response.status_code == 503
        data = response.json()
        assert data["success"] is False
        assert data["code"] == "DATABASE_UNAVAILABLE"
    finally:
        app.dependency_overrides.pop(get_neo4j_client, None)


# --- 6. UI Static Files & Index Tests ---


def test_ui_index_served(client: TestClient) -> None:
    """Verifies GET / returns 200 and serves HTML index file."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Tra cứu Tư vấn Pháp luật Giao thông" in response.text
    assert "Perplexity" in response.text or "Warm research terminal" in response.text or "app-sidebar" in response.text


def test_ui_static_css_served(client: TestClient) -> None:
    """Verifies GET /static/css/tokens.css serves design tokens."""
    response = client.get("/static/css/tokens.css")
    assert response.status_code == 200
    assert "--color-aged-paper" in response.text
    assert "--color-deep-teal" in response.text

