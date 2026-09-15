"""CLI Entrypoint for Traditional RAG: Indexing and Querying."""

from __future__ import annotations

import argparse
import logging
import sys

from tabulate import tabulate

from src.rag.config import RAGConfig
from src.rag.indexer import CorpusIndexer
from src.rag.retriever import HybridRetriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("src.rag")


def handle_index(args: argparse.Namespace, config: RAGConfig) -> int:
    """Handles corpus indexing subcommand."""
    indexer = CorpusIndexer(config=config)
    doc_id = None if args.all else args.doc

    print("\n=======================================================")
    print("           TRAFFIC LAW RAG CORPUS INDEXER             ")
    print("=======================================================")
    print(f"Target:       {'ALL DOCUMENTS' if args.all else f'Document: {doc_id}'}")
    print(f"Batch size:   {args.batch_size or config.ingest_batch_size}")
    print(f"Dry run:      {args.dry_run}")
    print("-------------------------------------------------------\n")

    stats = indexer.index_corpus(
        doc_id=doc_id,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    print("\n================= INDEXING SUMMARY ====================")
    print(f"Documents found:        {stats.total_documents}")
    print(f"Total semantic units:   {stats.total_units}")
    print(f"Indexed units:          {stats.indexed_units}")
    print(f"Failed units:           {stats.failed_units}")
    print(f"Vector Index status:    {stats.vector_index_status}")
    print(f"Fulltext Index status:  {stats.fulltext_index_status}")
    print(f"Elapsed time:           {stats.elapsed_seconds}s")
    print("=======================================================\n")
    return 0 if stats.failed_units == 0 else 1


def handle_query(args: argparse.Namespace, config: RAGConfig) -> int:
    """Handles hybrid query retrieval subcommand."""
    retriever = HybridRetriever(config=config)
    result = retriever.retrieve(
        query=args.query,
        top_k=args.top_k,
        document_id=args.doc,
    )

    if args.format == "json":
        print(result.model_dump_json(indent=2))
        return 0

    # Format as pretty table
    table_data = []
    for rank, chunk in enumerate(result.chunks, start=1):
        meta = chunk.metadata
        loc_parts = []
        if meta.dieu:
            loc_parts.append(f"Điều {meta.dieu}")
        if meta.khoan:
            loc_parts.append(f"K{meta.khoan}")
        if meta.diem:
            loc_parts.append(f"Đ{meta.diem}")
        location = " ".join(loc_parts)

        # Truncate text for terminal readability
        clean_text = chunk.text.replace("\n", " ")
        text_preview = (clean_text[:75] + "...") if len(clean_text) > 75 else clean_text

        dense_display = (
            f"{chunk.dense_score:.3f} (#{chunk.dense_rank})"
            if chunk.dense_score is not None
            else "-"
        )
        sparse_display = (
            f"{chunk.sparse_score:.1f} (#{chunk.sparse_rank})"
            if chunk.sparse_score is not None
            else "-"
        )

        table_data.append(
            [
                rank,
                chunk.id,
                f"{chunk.score:.5f}",
                dense_display,
                sparse_display,
                location,
                text_preview,
            ]
        )

    headers = ["#", "Unit ID", "RRF Score", "Dense", "BM25", "Location", "Text Preview"]
    print(
        f"\nQuery: '{result.query}' (Latency: {result.execution_time_ms}ms, Top-{len(result.chunks)})"
    )
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.rag",
        description="Traditional RAG module for Traffic Law GraphRAG.",
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Subcommands: index or query"
    )

    # 1. Index command
    index_parser = subparsers.add_parser(
        "index", help="Index parsed semantic units into Neo4j"
    )
    index_group = index_parser.add_mutually_exclusive_group(required=True)
    index_group.add_argument(
        "--all", action="store_true", help="Index all documents in data/parsed"
    )
    index_group.add_argument(
        "--doc", type=str, help="Document ID to index (e.g., 168_2024_ND-CP)"
    )
    index_parser.add_argument(
        "--batch-size", type=int, default=None, help="Batch size for ingestion"
    )
    index_parser.add_argument(
        "--dry-run", action="store_true", help="Parse files without writing to Neo4j"
    )

    # 2. Query command
    query_parser = subparsers.add_parser(
        "query", help="Retrieve top-k candidate chunks for a query"
    )
    query_parser.add_argument("query", type=str, help="Search query string")
    query_parser.add_argument(
        "--top-k", type=int, default=5, help="Number of chunks to return (default: 5)"
    )
    query_parser.add_argument(
        "--doc", type=str, default=None, help="Optional document ID filter"
    )
    query_parser.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format"
    )

    # Fallback / Top-level arguments for convenience
    parser.add_argument(
        "--query", type=str, dest="top_query", help="Direct query shortcut"
    )
    parser.add_argument(
        "--index-all", action="store_true", help="Direct index-all shortcut"
    )

    args = parser.parse_args()
    config = RAGConfig.from_env()

    if args.command == "index":
        sys.exit(handle_index(args, config))
    elif args.command == "query":
        sys.exit(handle_query(args, config))
    elif args.top_query:
        args.query = args.top_query
        args.top_k = 5
        args.doc = None
        args.format = "table"
        sys.exit(handle_query(args, config))
    elif args.index_all:
        args.all = True
        args.doc = None
        args.batch_size = None
        args.dry_run = False
        sys.exit(handle_index(args, config))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
