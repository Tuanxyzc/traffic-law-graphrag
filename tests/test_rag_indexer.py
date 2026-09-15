"""Tests for CorpusIndexer."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.rag.config import RAGConfig
from src.rag.indexer import CorpusIndexer


@pytest.fixture
def temp_parsed_dir(tmp_path: Path) -> Path:
    doc1 = tmp_path / "168_2024_ND-CP_semantic_units.json"
    data1 = [
        {
            "id": "168_2024_ND-CP_D5_K1_Da",
            "vi_tri": {
                "dieu": "5",
                "khoan": "1",
                "diem": "a",
                "so_hieu_van_ban": "168/2024/ND-CP",
            },
            "noi_dung_chuan_hoa": "Điều 5. Khoản 1: a) Không chấp hành hiệu lệnh",
            "tieu_de_dieu": "Xử phạt người điều khiển xe ô tô",
            "chuong": "II",
            "level": 4,
            "hieu_luc_tu": "2025-01-01",
        },
        {
            "id": "168_2024_ND-CP_D1_K2",
            "vi_tri": {
                "dieu": "1",
                "khoan": "2",
                "diem": None,
                "so_hieu_van_ban": "168/2024/ND-CP",
            },
            "noi_dung_chuan_hoa": "Điều 1. Khoản 2: Đối tượng áp dụng",
            "tieu_de_dieu": "Phạm vi điều chỉnh",
            "chuong": "I",
            "level": 3,
            "hieu_luc_tu": None,
        },
    ]
    with open(doc1, "w", encoding="utf-8") as f:
        json.dump(data1, f)

    doc2 = tmp_path / "151_2024_ND-CP_semantic_units.json"
    data2 = [
        {
            "id": "151_2024_ND-CP_D2_K1",
            "vi_tri": {"dieu": "2", "khoan": "1", "diem": None},
            "noi_dung_chuan_hoa": "Điều 2. Khoản 1: Nội dung",
            "level": 3,
        }
    ]
    with open(doc2, "w", encoding="utf-8") as f:
        json.dump(data2, f)

    return tmp_path


def test_find_semantic_unit_files(temp_parsed_dir: Path) -> None:
    config = RAGConfig(parsed_dir=str(temp_parsed_dir))
    indexer = CorpusIndexer(config=config)

    all_files = indexer.find_semantic_unit_files()
    assert len(all_files) == 2

    single_file = indexer.find_semantic_unit_files("168_2024_ND-CP")
    assert len(single_file) == 1
    assert "168_2024_ND-CP" in single_file[0].name


def test_parse_file(temp_parsed_dir: Path) -> None:
    config = RAGConfig(parsed_dir=str(temp_parsed_dir))
    indexer = CorpusIndexer(config=config)
    target_file = temp_parsed_dir / "168_2024_ND-CP_semantic_units.json"

    units = indexer.parse_file(target_file)
    assert len(units) == 2

    u1 = units[0]
    assert u1["id"] == "168_2024_ND-CP_D5_K1_Da"
    assert u1["dieu"] == "5"
    assert u1["khoan"] == "1"
    assert u1["diem"] == "a"
    assert u1["level"] == 4
    assert "Điều 5. Khoản 1: a) Không chấp hành hiệu lệnh" in u1["text"]
    assert "Văn bản: 168/2024/ND-CP" in u1["text"]
    assert u1["raw_text"] == "Điều 5. Khoản 1: a) Không chấp hành hiệu lệnh"
    assert u1["hieu_luc_tu"] == "2025-01-01"

    u2 = units[1]
    assert u2["id"] == "168_2024_ND-CP_D1_K2"
    assert u2["diem"] is None
    assert u2["level"] == 3


def test_build_cypher_statement() -> None:
    indexer = CorpusIndexer()
    query = indexer.build_cypher_statement()
    assert "MERGE (su:SemanticUnit {id: row.id})" in query
    assert "su.raw_text = row.raw_text" in query
    assert "MERGE (su)-[:EXTRACTED_FROM]->(p)" in query
    assert "MERGE (su)-[:EXTRACTED_FROM]->(c)" in query


def test_index_corpus_dry_run(temp_parsed_dir: Path) -> None:
    config = RAGConfig(parsed_dir=str(temp_parsed_dir))
    indexer = CorpusIndexer(config=config)

    stats = indexer.index_corpus(dry_run=True)
    assert stats.total_documents == 2
    assert stats.total_units == 3
    assert stats.indexed_units == 0
    assert stats.vector_index_status == "DRY_RUN"


def test_index_corpus_mocked_execution(temp_parsed_dir: Path) -> None:
    config = RAGConfig(parsed_dir=str(temp_parsed_dir))

    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    mock_emb = MagicMock()
    mock_emb.embed_texts.side_effect = lambda texts: [[0.1] * 1024 for _ in texts]

    mock_schema = MagicMock()
    mock_schema.check_indexes_status.return_value = {
        config.vector_index_name: "ONLINE",
        config.fulltext_index_name: "ONLINE",
    }

    indexer = CorpusIndexer(
        client=mock_client,
        embedding_manager=mock_emb,
        schema_manager=mock_schema,
        config=config,
    )

    stats = indexer.index_corpus(doc_id="168_2024_ND-CP", batch_size=10)
    assert stats.total_documents == 1
    assert stats.total_units == 2
    assert stats.indexed_units == 2
    assert stats.failed_units == 0
    assert stats.vector_index_status == "ONLINE"
    assert stats.fulltext_index_status == "ONLINE"

    # Schema ensured and Cypher batch executed
    mock_schema.ensure_schema.assert_called_once_with(mock_session)
    assert mock_session.run.call_count >= 1
