"""CLI Entrypoint for Information Extraction & Neo4j Ingestion."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.extraction.extractor import IEOrchestrator
from src.extraction.storage import ExtractionStorage
from src.graph.neo4j.connection import Neo4jClient
from src.graph.neo4j.ie_importer import Neo4jIEImporter

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Extract legal entities and relationships using LLMs and import into Neo4j."
    )
    parser.add_argument(
        "--doc",
        type=str,
        default="168_2024_ND-CP",
        help="Target document ID to extract (e.g. 168_2024_ND-CP)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all documents found in data/parsed/",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Limit extraction to first N clauses (for testing and quota saving)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Gemini model name (default: from GEMINI_MODEL env or gemini-3.6-flash)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract clauses even if already completed in checkpoint",
    )
    parser.add_argument(
        "--import-neo4j",
        action="store_true",
        help="Import extracted JSON records into Neo4j",
    )
    parser.add_argument(
        "--only-import",
        action="store_true",
        help="Skip LLM extraction and only import existing JSON records into Neo4j",
    )

    args = parser.parse_args()

    parsed_dir = Path("data/parsed")
    storage = ExtractionStorage()

    if args.all:
        su_files = sorted(parsed_dir.glob("*_semantic_units.json"))
        target_docs = [f.name.replace("_semantic_units.json", "") for f in su_files]
    else:
        target_docs = [args.doc]

    # 1. Extraction Phase
    if not args.only_import:
        orchestrator = IEOrchestrator(
            model=args.model, storage=storage, parsed_dir=parsed_dir
        )
        for doc_id in target_docs:
            logger.info("=== Starting Extraction for: %s ===", doc_id)
            try:
                orchestrator.extract_document(
                    document_id=doc_id,
                    sample_limit=args.sample,
                    force_refresh=args.force,
                )
            except Exception as exc:
                logger.error("Failed extraction for %s: %s", doc_id, exc)

    # 2. Neo4j Ingestion Phase
    if args.import_neo4j or args.only_import:
        logger.info("=== Connecting to Neo4j to import extracted entities ===")
        try:
            client = Neo4jClient()
            client.verify_connectivity()
            importer = Neo4jIEImporter(client=client, storage=storage)
            total_stats = {
                "subjects": 0,
                "violations": 0,
                "sanctions": 0,
                "relationships": 0,
            }

            for doc_id in target_docs:
                stats = importer.import_document_extractions(doc_id)
                for k, v in stats.items():
                    total_stats[k] += v

            print("\n=== NEO4J IE INGESTION SUMMARY ===")
            for k, v in total_stats.items():
                print(f"  {k}: {v}")
            print("==================================\n")
        except Exception as exc:
            logger.error("Neo4j import failed: %s", exc)


if __name__ == "__main__":
    main()
