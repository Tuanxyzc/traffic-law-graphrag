"""Tests for RAG CLI dispatcher."""

from unittest.mock import MagicMock, patch

from src.rag.__main__ import handle_index, handle_query
from src.rag.config import RAGConfig
from src.rag.models import (
    ChunkMetadata,
    IngestionStats,
    RetrievalResult,
    RetrievedChunk,
)


def test_handle_index_success() -> None:
    args = MagicMock()
    args.all = False
    args.doc = "168_2024_ND-CP"
    args.batch_size = 50
    args.dry_run = True

    config = RAGConfig()
    with patch("src.rag.__main__.CorpusIndexer") as mock_indexer_cls:
        mock_indexer = MagicMock()
        mock_indexer.index_corpus.return_value = IngestionStats(
            total_documents=1,
            total_units=100,
            indexed_units=0,
            failed_units=0,
            vector_index_status="DRY_RUN",
            fulltext_index_status="DRY_RUN",
        )
        mock_indexer_cls.return_value = mock_indexer

        ret_code = handle_index(args, config)
        assert ret_code == 0
        mock_indexer.index_corpus.assert_called_once_with(
            doc_id="168_2024_ND-CP",
            batch_size=50,
            dry_run=True,
        )


def test_handle_query_table_and_json(capsys) -> None:
    args = MagicMock()
    args.query = "vượt đèn đỏ"
    args.top_k = 1
    args.doc = None
    args.format = "table"

    config = RAGConfig()
    mock_chunk = RetrievedChunk(
        id="168_2024_ND-CP_D5_K1_Da",
        text="Điều 5 Khoản 1: a) Không chấp hành hiệu lệnh",
        score=0.032,
        dense_score=0.88,
        dense_rank=1,
        sparse_score=12.5,
        sparse_rank=1,
        metadata=ChunkMetadata(
            document_id="168_2024_ND-CP", dieu="5", khoan="1", diem="a"
        ),
    )
    mock_result = RetrievalResult(
        query="vượt đèn đỏ",
        top_k=1,
        chunks=[mock_chunk],
        execution_time_ms=15.0,
    )

    with patch("src.rag.__main__.HybridRetriever") as mock_retriever_cls:
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = mock_result
        mock_retriever_cls.return_value = mock_retriever

        ret_code = handle_query(args, config)
        assert ret_code == 0
        captured = capsys.readouterr()
        assert "168_2024_ND-CP_D5_K1_Da" in captured.out
        assert "Điều 5 K1 Đa" in captured.out

        # Test json format
        args.format = "json"
        ret_code_json = handle_query(args, config)
        assert ret_code_json == 0
        captured_json = capsys.readouterr()
        assert '"id": "168_2024_ND-CP_D5_K1_Da"' in captured_json.out
