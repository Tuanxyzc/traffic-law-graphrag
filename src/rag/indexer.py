"""Corpus Batch Indexer: ingests semantic units from JSON files into Neo4j with vector embeddings."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from src.graph.neo4j.connection import Neo4jClient
from src.rag.config import RAGConfig
from src.rag.embedding import EmbeddingManager
from src.rag.models import IngestionStats
from src.rag.schema import RAGSchemaManager

logger = logging.getLogger(__name__)


def build_enriched_text(
    raw_text: str,
    doc_id: str,
    so_hieu: str | None = None,
    chuong: str | None = None,
    tieu_de_chuong: str | None = None,
    dieu: str | None = None,
    tieu_de_dieu: str | None = None,
    khoan: str | None = None,
    diem: str | None = None,
) -> str:
    """Builds a metadata-enriched contextual string for vector embedding and fulltext retrieval."""
    header_lines: list[str] = []

    # 1. Document identifier
    display_doc = so_hieu or doc_id
    if so_hieu and so_hieu != doc_id:
        header_lines.append(f"Văn bản: {so_hieu} ({doc_id})")
    else:
        header_lines.append(f"Văn bản: {display_doc}")

    # 2. Chapter information
    if chuong and tieu_de_chuong:
        header_lines.append(f"Chương: Chương {chuong} - {tieu_de_chuong}")
    elif chuong:
        header_lines.append(f"Chương: Chương {chuong}")
    elif tieu_de_chuong:
        header_lines.append(f"Chương: {tieu_de_chuong}")

    # 3. Article title
    if dieu and tieu_de_dieu:
        header_lines.append(f"Điều: Điều {dieu} - {tieu_de_dieu}")
    elif dieu:
        header_lines.append(f"Điều: Điều {dieu}")

    # 4. Clause & Point location
    loc_parts: list[str] = []
    if khoan:
        loc_parts.append(f"Khoản {khoan}")
    if diem:
        loc_parts.append(f"Điểm {diem}")
    if loc_parts:
        header_lines.append(f"Vị trí: {', '.join(loc_parts)}")

    header = "\n".join(header_lines)
    return f"{header}\nNội dung:\n{raw_text}"


class CorpusIndexer:
    """Orchestrates parsing of legal semantic units, embedding generation, and Neo4j batch insertion."""

    def __init__(
        self,
        client: Neo4jClient | None = None,
        embedding_manager: EmbeddingManager | None = None,
        schema_manager: RAGSchemaManager | None = None,
        config: RAGConfig | None = None,
    ) -> None:
        self.config = config or RAGConfig()
        self.client = client
        self.embedding_manager = embedding_manager or EmbeddingManager(
            config=self.config
        )
        self.schema_manager = schema_manager or RAGSchemaManager(config=self.config)

    def find_semantic_unit_files(self, doc_id: str | None = None) -> list[Path]:
        """Locates semantic_units.json files in parsed directory matching criteria."""
        parsed_path = Path(self.config.parsed_dir)
        if not parsed_path.exists():
            logger.warning("Parsed directory does not exist: %s", parsed_path)
            return []

        if doc_id:
            exact_target = parsed_path / f"{doc_id}_semantic_units.json"
            if exact_target.exists():
                return [exact_target]
            # Fallback: search by prefix
            matches = list(parsed_path.glob(f"*{doc_id}*_semantic_units.json"))
            return sorted(matches)

        return sorted(parsed_path.glob("*_semantic_units.json"))

    def parse_file(self, file_path: Path) -> list[dict[str, Any]]:
        """Parses a semantic_units.json file and returns a list of normalized raw unit dicts."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.error("Failed to read %s: %s", file_path, exc)
            return []

        if not isinstance(data, list):
            logger.warning("File %s does not contain a list of units.", file_path)
            return []

        # Derive document_id from filename (e.g. 168_2024_ND-CP_semantic_units.json -> 168_2024_ND-CP)
        filename_doc_id = file_path.name.replace("_semantic_units.json", "")

        units: list[dict[str, Any]] = []
        for item in data:
            unit_id = item.get("id")
            if not unit_id:
                continue

            raw_text = (
                item.get("noi_dung_chuan_hoa")
                or item.get("noi_dung")
                or item.get("noi_dung_goc")
                or ""
            ).strip()
            if not raw_text:
                continue

            vi_tri = item.get("vi_tri", {})
            doc_id = (
                vi_tri.get("so_hieu_van_ban", "").replace("/", "_") or filename_doc_id
            )
            so_hieu = vi_tri.get("so_hieu_van_ban")
            dieu_str = str(vi_tri.get("dieu") or "")
            khoan_str = str(vi_tri["khoan"]) if vi_tri.get("khoan") else None
            diem_str = str(vi_tri["diem"]) if vi_tri.get("diem") else None
            tieu_de_dieu = item.get("tieu_de_dieu")
            chuong_str = item.get("chuong")
            tieu_de_chuong = item.get("tieu_de_chuong")

            enriched_text = build_enriched_text(
                raw_text=raw_text,
                doc_id=doc_id,
                so_hieu=so_hieu,
                chuong=chuong_str,
                tieu_de_chuong=tieu_de_chuong,
                dieu=dieu_str,
                tieu_de_dieu=tieu_de_dieu,
                khoan=khoan_str,
                diem=diem_str,
            )

            units.append(
                {
                    "id": unit_id,
                    "text": enriched_text,
                    "raw_text": raw_text,
                    "document_id": doc_id,
                    "dieu": dieu_str,
                    "khoan": khoan_str,
                    "diem": diem_str,
                    "tieu_de_dieu": tieu_de_dieu,
                    "chuong": chuong_str,
                    "tieu_de_chuong": tieu_de_chuong,
                    "level": int(item.get("level", 4)),
                    "hieu_luc_tu": item.get("hieu_luc_tu"),
                }
            )
        return units

    def build_cypher_statement(self) -> str:
        """Returns the Cypher UNWIND query for batch merging SemanticUnit nodes and relations."""
        return """
        UNWIND $batch AS row
        MERGE (su:SemanticUnit {id: row.id})
        SET su.text = row.text,
            su.raw_text = row.raw_text,
            su.embedding = row.embedding,
            su.document_id = row.document_id,
            su.dieu = row.dieu,
            su.khoan = row.khoan,
            su.diem = row.diem,
            su.tieu_de_dieu = row.tieu_de_dieu,
            su.chuong = row.chuong,
            su.tieu_de_chuong = row.tieu_de_chuong,
            su.level = row.level,
            su.hieu_luc_tu = row.hieu_luc_tu
        WITH su, row
        CALL {
            WITH su, row
            WITH su, row WHERE row.level = 4
            MATCH (p:Point {id: row.id})
            MERGE (su)-[:EXTRACTED_FROM]->(p)
        }
        CALL {
            WITH su, row
            WITH su, row WHERE row.level = 3
            MATCH (c:Clause {id: row.id})
            MERGE (su)-[:EXTRACTED_FROM]->(c)
        }
        CALL {
            WITH su, row
            WITH su, row WHERE row.level = 2
            MATCH (a:Article {id: row.id})
            MERGE (su)-[:EXTRACTED_FROM]->(a)
        }
        """

    def index_corpus(
        self,
        doc_id: str | None = None,
        batch_size: int | None = None,
        dry_run: bool = False,
    ) -> IngestionStats:
        """Executes full indexing pipeline: parse -> embed -> ingest into Neo4j."""
        start_time = time.perf_counter()
        bs = batch_size or self.config.ingest_batch_size
        files = self.find_semantic_unit_files(doc_id)

        stats = IngestionStats(
            total_documents=len(files),
            total_units=0,
            indexed_units=0,
            failed_units=0,
        )

        all_units: list[dict[str, Any]] = []
        for file_path in files:
            units = self.parse_file(file_path)
            all_units.extend(units)

        stats.total_units = len(all_units)
        logger.info(
            "Found %d semantic units across %d documents.", len(all_units), len(files)
        )

        if dry_run or not all_units:
            stats.elapsed_seconds = round(time.perf_counter() - start_time, 2)
            stats.vector_index_status = "DRY_RUN"
            stats.fulltext_index_status = "DRY_RUN"
            return stats

        client = self.client or Neo4jClient()

        # 1. Ensure Schema
        with client.session() as session:
            self.schema_manager.ensure_schema(session)

        # 2. Embed and Ingest in Batches
        cypher_query = self.build_cypher_statement()
        cache_path = Path("data/parsed/embedding_cache.json")
        embedding_cache: dict[str, list[float]] = {}
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    embedding_cache = json.load(f)
                logger.info(
                    "Loaded %d cached embeddings from %s",
                    len(embedding_cache),
                    cache_path,
                )
            except Exception as e:
                logger.warning("Could not read embedding cache: %s", e)

        with client.session() as session:
            for i in range(0, len(all_units), bs):
                chunk_units = all_units[i : i + bs]
                texts = [u["text"] for u in chunk_units]

                try:
                    cached_batch = [embedding_cache.get(u["id"]) for u in chunk_units]
                    embeddings: list[list[float]]
                    if all(emb is not None for emb in cached_batch):
                        embeddings = [emb for emb in cached_batch if emb is not None]
                    else:
                        embeddings = self.embedding_manager.embed_texts(texts)

                    batch_payload = []
                    for u, emb in zip(chunk_units, embeddings, strict=True):
                        payload = dict(u)
                        payload["embedding"] = emb
                        batch_payload.append(payload)

                    session.run(cypher_query, batch=batch_payload)
                    stats.indexed_units += len(batch_payload)
                    logger.info(
                        "Indexed %d/%d units...", stats.indexed_units, stats.total_units
                    )
                except Exception as exc:
                    logger.error("Failed batch %d-%d: %s", i, i + len(chunk_units), exc)
                    stats.failed_units += len(chunk_units)

        # 3. Check Index States
        with client.session() as session:
            status_map = self.schema_manager.check_indexes_status(session)
            stats.vector_index_status = status_map.get(
                self.config.vector_index_name, "UNKNOWN"
            )
            stats.fulltext_index_status = status_map.get(
                self.config.fulltext_index_name, "UNKNOWN"
            )

        stats.elapsed_seconds = round(time.perf_counter() - start_time, 2)
        return stats
