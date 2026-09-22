"""CLI entrypoint for executing End-to-End GraphRAG queries."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from tabulate import tabulate

from src.pipeline.config import PipelineConfig
from src.pipeline.pipeline import GraphRAGPipeline

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    """Builds argument parser for the GraphRAG pipeline CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline",
        description="End-to-End Vietnamese Traffic Law GraphRAG Query Engine",
    )
    parser.add_argument(
        "query",
        type=str,
        help="Citizen query in natural Vietnamese (e.g. 'vượt đèn đỏ xe máy phạt bao nhiêu?')",
    )
    parser.add_argument(
        "-d",
        "--doc",
        type=str,
        default=None,
        help="Filter statutory search to specific legal document ID (e.g. '168_2024_ND-CP')",
    )
    parser.add_argument(
        "-k",
        "--top-k",
        type=int,
        default=None,
        help="Number of candidate chunks to retrieve from RAG (default: from config, usually 5)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["text", "table", "json"],
        default="text",
        help="Output format: 'text' (default), 'table' (evidence table + answer), or 'json'",
    )
    parser.add_argument(
        "--no-rewrite",
        action="store_true",
        help="Disable colloquial query rewriting step and use original query directly",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed diagnostic and debug logging",
    )
    return parser


def format_text_output(result) -> str:
    """Formats PipelineResult as a rich readable terminal output."""
    lines: list[str] = [
        "=" * 80,
        "🏛️  HỆ THỐNG TRẢ LỜI PHÁP LUẬT GIAO THÔNG",
        "=" * 80,
        f"❓ Câu hỏi của người dân: {result.user_query}",
    ]

    if result.rewritten_query and result.rewritten_query != result.user_query:
        if hasattr(result.rewritten_query, "to_json_dict"):
            rw_json = json.dumps(
                result.rewritten_query.to_json_dict(),
                ensure_ascii=False,
                indent=2,
            )
            lines.append(f"🔍 Phân tích & Chuẩn hóa truy vấn (Query Rewrite JSON):\n{rw_json}")
        elif isinstance(result.rewritten_query, dict):
            rw_json = json.dumps(
                result.rewritten_query,
                ensure_ascii=False,
                indent=2,
            )
            lines.append(f"🔍 Phân tích & Chuẩn hóa truy vấn (Query Rewrite JSON):\n{rw_json}")
        else:
            lines.append(f"🔍 Thuật ngữ tra cứu chuẩn hóa: {result.rewritten_query}")

    lines.extend(
        [
            "-" * 80,
            "📝 CÂU TRẢ LỜI CĂN CỨ PHÁP LUẬT:",
            result.answer,
            "-" * 80,
        ]
    )

    if result.citations:
        lines.append("📚 Căn cứ pháp lý dẫn chiếu:")
        for c in result.citations:
            lines.append(f"  • {c}")

    if result.evidence_package.has_superseded_provisions:
        lines.append(
            "\n⚠️  LƯU Ý HIỆU LỰC: Gói bằng chứng chứa quy định đã bị sửa đổi / thay thế hoặc hết hiệu lực."
        )

    if result.citations or result.evidence_package.has_superseded_provisions:
        lines.append("-" * 80)

    lines.extend(
        [
            f"⏱️ Thời gian xử lý: {result.execution_time_ms:.1f}ms | Bằng chứng: {len(result.evidence_package.items)} điều khoản",
            "=" * 80,
        ]
    )
    return "\n".join(lines)


def format_table_output(result) -> str:
    """Formats PipelineResult with a tabulate grid of evidence items."""
    lines: list[str] = [
        format_text_output(result),
        "\n📋 CHI TIẾT BẰNG CHỨNG PHÁP LÝ (EVIDENCE PACKAGE):",
    ]

    table_data = []
    for idx, item in enumerate(result.evidence_package.items, start=1):
        prov = item.validated_provision
        status_disp = item.warning_flag or prov.status.value
        content = (prov.content_text or item.original_chunk_text).replace("\n", " ")
        preview = (content[:60] + "...") if len(content) > 60 else content

        table_data.append(
            [
                idx,
                prov.provision_id,
                prov.level,
                prov.parent_article_title or "-",
                status_disp,
                preview,
            ]
        )

    headers = [
        "#",
        "Provision ID",
        "Level",
        "Điều luật",
        "Trạng thái hiệu lực",
        "Nội dung trích dẫn",
    ]
    lines.append(tabulate(table_data, headers=headers, tablefmt="grid"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Main CLI execution handler."""
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    config = PipelineConfig.from_env()
    if args.no_rewrite:
        # Override rewrite behavior
        config = PipelineConfig(
            model_name=config.model_name,
            rewrite_model_name=config.rewrite_model_name,
            temperature_rewrite=config.temperature_rewrite,
            temperature_generate=config.temperature_generate,
            max_retries=config.max_retries,
            timeout_seconds=config.timeout_seconds,
            enable_query_rewrite=False,
            top_k=args.top_k or config.top_k,
            max_reference_hops=config.max_reference_hops,
            include_superseded_warning=config.include_superseded_warning,
            neo4j_uri=config.neo4j_uri,
            neo4j_user=config.neo4j_user,
            neo4j_password=config.neo4j_password,
        )

    pipeline = GraphRAGPipeline(config=config)

    try:
        result = pipeline.query(
            user_query=args.query,
            document_id=args.doc,
            top_k=args.top_k,
        )
    except Exception as exc:
        logger.error("Pipeline execution failed: %s", exc, exc_info=args.verbose)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(result.model_dump_json(indent=2))
    elif args.format == "table":
        print(format_table_output(result))
    else:
        print(format_text_output(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
