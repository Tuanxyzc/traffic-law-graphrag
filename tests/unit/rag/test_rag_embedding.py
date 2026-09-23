"""Tests for SentenceTransformer EmbeddingManager."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from src.rag.config import RAGConfig
from src.rag.embedding import EmbeddingManager


def test_embedding_manager_init() -> None:
    config = RAGConfig(embedding_model="BAAI/bge-m3", embedding_dim=1024)
    manager = EmbeddingManager(config=config)
    assert manager.model_name == "BAAI/bge-m3"
    assert manager.device == "cpu"
    assert manager._model is None


def test_embed_empty_list() -> None:
    manager = EmbeddingManager()
    assert manager.embed_texts([]) == []


def test_embed_empty_query() -> None:
    config = RAGConfig(embedding_dim=1024)
    manager = EmbeddingManager(config=config)
    query_vec = manager.embed_query("   ")
    assert len(query_vec) == 1024
    assert all(v == 0.0 for v in query_vec)


def test_embed_texts_mocked() -> None:
    mock_model = MagicMock()
    mock_vec1 = np.ones(1024, dtype=np.float32)
    mock_vec2 = np.zeros(1024, dtype=np.float32)
    mock_model.encode.return_value = np.array([mock_vec1, mock_vec2])

    manager = EmbeddingManager()
    manager._model = mock_model

    texts = ["Điều 5 khoản 1", "Phạt tiền 18 triệu đồng"]
    results = manager.embed_texts(texts, batch_size=2)

    assert len(results) == 2
    assert len(results[0]) == 1024
    assert len(results[1]) == 1024
    assert results[0][0] == 1.0
    assert results[1][0] == 0.0
    mock_model.encode.assert_called_once_with(
        texts,
        batch_size=2,
        show_progress_bar=False,
        normalize_embeddings=True,
    )


def test_embed_query_mocked() -> None:
    mock_model = MagicMock()
    mock_vec = np.array([0.5] * 1024, dtype=np.float32)
    mock_model.encode.return_value = mock_vec

    manager = EmbeddingManager()
    manager._model = mock_model

    query_vec = manager.embed_query("vượt đèn đỏ")
    assert len(query_vec) == 1024
    assert query_vec[0] == pytest.approx(0.5)
    mock_model.encode.assert_called_once_with(
        "vượt đèn đỏ",
        show_progress_bar=False,
        normalize_embeddings=True,
    )
