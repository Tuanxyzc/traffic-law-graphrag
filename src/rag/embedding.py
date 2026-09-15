"""Embedding Manager: wraps SentenceTransformer for BAAI/bge-m3 dense vector inference."""

from __future__ import annotations

import logging
from typing import Any

from src.rag.config import RAGConfig

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """Manages text embedding generation using SentenceTransformer with lazy initialization and batching."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        config: RAGConfig | None = None,
    ) -> None:
        self.config = config or RAGConfig()
        self.model_name = model_name or self.config.embedding_model
        self.device = device or "cpu"
        self._model: Any = None

    @property
    def model(self) -> Any:
        """Lazily instantiates the SentenceTransformer model on the target device."""
        if self._model is None:
            logger.info(
                "Initializing SentenceTransformer model: %s on device: %s",
                self.model_name,
                self.device,
            )
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed_texts(
        self,
        texts: list[str],
        batch_size: int | None = None,
    ) -> list[list[float]]:
        """Generates dense vector embeddings for a list of text strings.

        Returns a list of float vectors of length `embedding_dim` (1024 for BAAI/bge-m3).
        """
        if not texts:
            return []

        bs = batch_size or self.config.embedding_batch_size
        embeddings = self.model.encode(
            texts,
            batch_size=bs,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [emb.tolist() for emb in embeddings]

    def embed_query(self, query: str) -> list[float]:
        """Embeds a single query string for vector retrieval."""
        if not query or not query.strip():
            return [0.0] * self.config.embedding_dim

        embedding = self.model.encode(
            query,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embedding.tolist()
