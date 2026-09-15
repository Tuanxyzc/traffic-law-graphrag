"""
sync.py — Unified 1-Click Synchronization Orchestrator for Vietnamese Traffic Law GraphRAG.

Executes the entire data integration pipeline in sequence:
  1. Neo4j connectivity check & auto-start via Docker Compose (if needed).
  2. Document Parsing & Semantic Unit extraction (src.parser).
  3. Knowledge Graph & Provision Timeline Ingestion (src.graph.neo4j.importer).
  4. Hybrid Vector (BAAI/bge-m3) & BM25 Indexing (src.rag.indexer).

Usage:
  python -m src.sync              # Sync full corpus
  python -m src.sync --doc 168_2024_ND-CP # Sync single document
  python -m src.sync --dry-run    # Dry-run validation without database writes
  python -m src.sync --skip-docker # Skip docker checks (use existing Neo4j Desktop)
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("src.sync")


def check_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Checks if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


def get_neo4j_host_port() -> tuple[str, int]:
    """Extracts host and port from NEO4J_URI."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 7687
    return host, port


def ensure_neo4j_running(skip_docker: bool = False, max_wait_sec: int = 30) -> bool:
    """Checks Neo4j connectivity. If unreachable, attempts docker compose up -d."""
    host, port = get_neo4j_host_port()
    if check_port_open(host, port, timeout=2.0):
        logger.info("Neo4j database is reachable at %s:%d", host, port)
        return True

    if skip_docker:
        logger.warning(
            "Neo4j is not reachable at %s:%d and --skip-docker was specified.",
            host,
            port,
        )
        return False

    docker_bin = shutil.which("docker")
    if not docker_bin:
        logger.warning(
            "Neo4j is not reachable at %s:%d, and 'docker' was not found in PATH.\n"
            "  - If using Neo4j Desktop: Please click 'Start' on your database project.\n"
            "  - If using Docker: Please install Docker Desktop and start it.",
            host,
            port,
        )
        return False

    logger.info(
        "Neo4j not reachable at %s:%d. Attempting to start container via docker compose...",
        host,
        port,
    )
    try:
        subprocess.run(["docker", "compose", "up", "-d"], check=True)
    except subprocess.CalledProcessError as e:
        logger.error("Failed to execute 'docker compose up -d': %s", e)
        return False

    logger.info("Waiting for Neo4j to accept connections (up to %ds)...", max_wait_sec)
    start_time = time.time()
    while time.time() - start_time < max_wait_sec:
        if check_port_open(host, port, timeout=1.5):
            logger.info("Neo4j container is up and listening at %s:%d!", host, port)
            return True
        time.sleep(2)

    logger.error("Neo4j did not become reachable within %ds.", max_wait_sec)
    return False


def run_stage_parser(dry_run: bool = False) -> tuple[bool, float, str]:
    """Runs Stage 1: Document parser."""
    start = time.time()
    logger.info(">>> [STAGE 1/3] Parsing documents and updating semantic units...")
    cmd = [sys.executable, "-m", "src.parser"]
    res = subprocess.run(cmd, check=False)
    elapsed = round(time.time() - start, 2)
    success = res.returncode == 0
    status_str = "SUCCESS" if success else f"FAILED (code {res.returncode})"
    return success, elapsed, status_str


def run_stage_neo4j(
    doc_id: str | None, dry_run: bool = False
) -> tuple[bool, float, str]:
    """Runs Stage 2: Neo4j batch importer."""
    start = time.time()
    logger.info(">>> [STAGE 2/3] Ingesting knowledge graph & versions into Neo4j...")
    cmd = [sys.executable, "-m", "src.graph.neo4j.importer"]
    if dry_run:
        cmd.append("--dry-run")
    elif doc_id:
        cmd.extend(["--doc", doc_id])
    else:
        cmd.append("--all")

    res = subprocess.run(cmd, check=False)
    elapsed = round(time.time() - start, 2)
    success = res.returncode == 0
    status_str = "SUCCESS" if success else f"FAILED (code {res.returncode})"
    return success, elapsed, status_str


def run_stage_rag(doc_id: str | None, dry_run: bool = False) -> tuple[bool, float, str]:
    """Runs Stage 3: Traditional RAG hybrid indexing."""
    start = time.time()
    logger.info(">>> [STAGE 3/3] Building Hybrid Vector & BM25 indexes...")
    cmd = [sys.executable, "-m", "src.rag", "index"]
    if doc_id:
        cmd.extend(["--doc", doc_id])
    else:
        cmd.append("--all")

    if dry_run:
        cmd.append("--dry-run")

    res = subprocess.run(cmd, check=False)
    elapsed = round(time.time() - start, 2)
    success = res.returncode == 0
    status_str = "SUCCESS" if success else f"FAILED (code {res.returncode})"
    return success, elapsed, status_str


def sync(
    doc_id: str | None = None,
    dry_run: bool = False,
    skip_docker: bool = False,
    skip_parser: bool = False,
    skip_rag: bool = False,
) -> int:
    """Orchestrates the entire synchronization workflow."""
    print("\n" + "=" * 64)
    print("      TRAFFIC LAW GRAPHRAG — 1-CLICK DATA SYNCHRONIZATION      ")
    print("=" * 64)
    print(f"Target:       {'ALL DOCUMENTS' if not doc_id else f'Document: {doc_id}'}")
    print(
        f"Mode:         {'DRY-RUN (Validation only)' if dry_run else 'LIVE INGESTION'}"
    )
    print(f"Docker check: {'SKIPPED' if skip_docker else 'ACTIVE'}")
    print("-" * 64 + "\n")

    stages_report: list[list[str | float]] = []
    total_start = time.time()

    # Pre-flight check: Neo4j connection (unless dry-run)
    if not dry_run:
        is_ready = ensure_neo4j_running(skip_docker=skip_docker)
        if not is_ready:
            print("\n[ERROR] Neo4j is not ready. Aborting sync pipeline.")
            return 1

    # Stage 1: Parser
    if not skip_parser:
        p_ok, p_time, p_status = run_stage_parser(dry_run=dry_run)
        stages_report.append(["1. Document Parser", f"{p_time}s", p_status])
        if not p_ok:
            print("\n[ERROR] Stage 1 (Parser) failed. Aborting downstream ingestion.")
            _print_summary(stages_report, round(time.time() - total_start, 2))
            return 1
    else:
        stages_report.append(["1. Document Parser", "0.0s", "SKIPPED"])

    # Stage 2: Neo4j Ingestion
    n_ok, n_time, n_status = run_stage_neo4j(doc_id=doc_id, dry_run=dry_run)
    stages_report.append(["2. Neo4j Graph Ingestion", f"{n_time}s", n_status])
    if not n_ok:
        print("\n[ERROR] Stage 2 (Neo4j Ingestion) failed.")
        _print_summary(stages_report, round(time.time() - total_start, 2))
        return 1

    # Stage 3: RAG Indexing
    if not skip_rag:
        r_ok, r_time, r_status = run_stage_rag(doc_id=doc_id, dry_run=dry_run)
        stages_report.append(["3. RAG Vector & BM25 Index", f"{r_time}s", r_status])
        if not r_ok:
            print("\n[ERROR] Stage 3 (RAG Indexing) failed.")
            _print_summary(stages_report, round(time.time() - total_start, 2))
            return 1
    else:
        stages_report.append(["3. RAG Vector & BM25 Index", "0.0s", "SKIPPED"])

    total_elapsed = round(time.time() - total_start, 2)
    _print_summary(stages_report, total_elapsed)
    print("SUCCESS: Data synchronization completed successfully!\n")
    return 0


def _print_summary(report: list[list[str | float]], total_elapsed: float) -> None:
    headers = ["Stage", "Duration", "Status"]
    print("\n" + "=" * 64)
    print("                     SYNCHRONIZATION REPORT                     ")
    print("=" * 64)
    print(tabulate(report, headers=headers, tablefmt="grid"))
    print(f"Total pipeline time: {total_elapsed}s")
    print("=" * 64 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="1-Click Data Synchronization Pipeline for Traffic Law GraphRAG"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all",
        action="store_true",
        default=True,
        help="Sync all documents in the corpus (default)",
    )
    group.add_argument(
        "--doc",
        type=str,
        default=None,
        help="Target a specific document ID (e.g. 168_2024_ND-CP)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate parsing and dry-run ingestion without database writes",
    )
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip Docker startup check (assumes Neo4j is already running)",
    )
    parser.add_argument(
        "--skip-parser",
        action="store_true",
        help="Skip Stage 1 parser execution",
    )
    parser.add_argument(
        "--skip-rag",
        action="store_true",
        help="Skip Stage 3 RAG indexer execution",
    )

    args = parser.parse_args()
    doc_id = None if args.all and not args.doc else args.doc

    exit_code = sync(
        doc_id=doc_id,
        dry_run=args.dry_run,
        skip_docker=args.skip_docker,
        skip_parser=args.skip_parser,
        skip_rag=args.skip_rag,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
