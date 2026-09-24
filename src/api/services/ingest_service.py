"""Ingest Service executing batch corpus indexing in background tasks."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from src.api.schemas.ingest import IngestTaskStatusResponse
from src.graph.neo4j.connection import Neo4jClient
from src.rag.indexer import CorpusIndexer

logger = logging.getLogger(__name__)


class IngestService:
    """Manages asynchronous background corpus indexing tasks."""

    def __init__(self, indexer: CorpusIndexer | None = None) -> None:
        self.indexer = indexer or CorpusIndexer()
        self._tasks: dict[str, IngestTaskStatusResponse] = {}

    def _execute_indexing_worker(
        self, task_id: str, file_path_str: str, batch_size: int, recreate_index: bool
    ) -> None:
        """Worker executing indexing synchronously in background thread."""
        start_time = time.perf_counter()
        target_path = Path(file_path_str)

        if not target_path.exists():
            self._tasks[task_id] = IngestTaskStatusResponse(
                task_id=task_id,
                status="failed",
                file_path=file_path_str,
                error_message=f"Tệp không tồn tại: {file_path_str}",
                elapsed_seconds=round(time.perf_counter() - start_time, 2),
            )
            return

        try:
            self._tasks[task_id].status = "processing"
            logger.info("Starting background indexing task %s for file %s", task_id, file_path_str)

            units = self.indexer.parse_file(target_path)
            if not units:
                self._tasks[task_id] = IngestTaskStatusResponse(
                    task_id=task_id,
                    status="completed",
                    file_path=file_path_str,
                    total_units=0,
                    processed_units=0,
                    successful_units=0,
                    failed_units=0,
                    elapsed_seconds=round(time.perf_counter() - start_time, 2),
                )
                return

            client = self.indexer.client or Neo4jClient()
            if recreate_index:
                with client.session() as session:
                    self.indexer.schema_manager.ensure_schema(session)

            cypher_query = self.indexer.build_cypher_statement()
            successful_units = 0
            failed_units = 0
            bs = batch_size or self.indexer.config.ingest_batch_size

            with client.session() as session:
                for i in range(0, len(units), bs):
                    chunk_units = units[i : i + bs]
                    texts = [u["text"] for u in chunk_units]
                    try:
                        embeddings = self.indexer.embedding_manager.embed_texts(texts)
                        batch_payload = []
                        for u, emb in zip(chunk_units, embeddings, strict=True):
                            payload = dict(u)
                            payload["embedding"] = emb
                            batch_payload.append(payload)

                        session.run(cypher_query, batch=batch_payload)
                        successful_units += len(batch_payload)
                    except Exception as exc:
                        logger.error("Failed indexing batch %d-%d: %s", i, i + len(chunk_units), exc)
                        failed_units += len(chunk_units)

            elapsed = round(time.perf_counter() - start_time, 2)
            self._tasks[task_id] = IngestTaskStatusResponse(
                task_id=task_id,
                status="completed",
                file_path=file_path_str,
                total_units=len(units),
                processed_units=successful_units + failed_units,
                successful_units=successful_units,
                failed_units=failed_units,
                elapsed_seconds=elapsed,
            )
            logger.info(
                "Completed background indexing task %s in %.2fs: %d success, %d failed",
                task_id,
                elapsed,
                successful_units,
                failed_units,
            )
        except Exception as exc:
            elapsed = round(time.perf_counter() - start_time, 2)
            logger.exception(
                "Background indexing task %s failed after %.2fs",
                task_id,
                elapsed,
            )
            self._tasks[task_id] = IngestTaskStatusResponse(
                task_id=task_id,
                status="failed",
                file_path=file_path_str,
                elapsed_seconds=elapsed,
                error_message=str(exc),
            )

    async def start_ingest_task(
        self, file_path: str, batch_size: int = 50, recreate_index: bool = False
    ) -> IngestTaskStatusResponse:
        """Schedules background task and returns initial tracking response."""
        task_id = str(uuid.uuid4())
        initial_status = IngestTaskStatusResponse(
            task_id=task_id,
            status="pending",
            file_path=file_path,
        )
        self._tasks[task_id] = initial_status

        asyncio.create_task(
            asyncio.to_thread(
                self._execute_indexing_worker,
                task_id=task_id,
                file_path_str=file_path,
                batch_size=batch_size,
                recreate_index=recreate_index,
            )
        )

        return initial_status

    def get_task_status(self, task_id: str) -> IngestTaskStatusResponse | None:
        """Retrieves current status of a background ingestion task."""
        return self._tasks.get(task_id)
