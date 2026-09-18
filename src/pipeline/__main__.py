"""CLI entrypoint for executing End-to-End GraphRAG queries."""

from __future__ import annotations

import argparse
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


def _clean_snippet(text: str | None, max_len: int = 110) -> str:
    """Cleans multiline text into a compact single-line preview."""
    if not text:
        return ""
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned


def format_graph_traversal_tree(result) -> list[str]:
    """Renders the Knowledge Graph traversal paths as an intuitive visual tree."""
    lines: list[str] = [
        "-" * 80,
        "🕸️  KNOWLEDGE GRAPH TRAVERSAL (CÁC NODES & QUAN HỆ ĐÃ DUYỆT):",
    ]

    items = getattr(result.evidence_package, "items", [])
    if not items:
        lines.append("  (Không có dữ liệu đồ thị)")
        return lines

    for idx, item in enumerate(items, start=1):
        prov = item.validated_provision

        # Hierarchy summary
        hierarchy_parts = []
        if prov.parent_article_title:
            hierarchy_parts.append(prov.parent_article_title)
        elif prov.parent_article_id:
            hierarchy_parts.append(prov.parent_article_id)
        if prov.parent_clause_number:
            hierarchy_parts.append(f"Khoản {prov.parent_clause_number}")

        hierarchy_str = (
            f" | Phạm vi: {' - '.join(hierarchy_parts)}" if hierarchy_parts else ""
        )
        status_val = (
            prov.status.value if hasattr(prov.status, "value") else str(prov.status)
        )

        lines.append(f"\n[{idx}] ANCHOR (Gốc trích xuất RAG): {prov.provision_id}")
        lines.append(
            f"  │ Cấp bậc: {prov.level} | Trạng thái: {status_val}{hierarchy_str}"
        )

        # Build list of traversed branches
        branches: list[tuple[str, str | None]] = []

        # 1. Direct amendments (amends / amended by)
        for am in prov.amendments:
            dir_icon = "◄──" if am.direction == "INCOMING" else "──►"
            op_label = f"[AMENDS : {am.operation}]"
            source_target = (
                f"từ {am.source_provision_id or am.by_document or 'Văn bản sửa đổi'}"
                if am.direction == "INCOMING"
                else f"tới {am.target_provision_id or 'Quy định gốc'}"
            )
            label = f"{dir_icon} {op_label} {source_target}"
            detail = _clean_snippet(am.replacement_text or am.instruction)
            branches.append((label, detail))

        # 2. Cross-references (Hop 1 & Hop 2)
        # Prioritize Hop 1 sanctions (TRU_DIEM_GPLX, TUOC_QUYEN_GPLX, TICH_THU) first
        sorted_refs = sorted(
            prov.cross_references,
            key=lambda r: (
                r.hop_level,
                0 if any(s in r.relation_type for s in ("GPLX", "TICH_THU", "BO_SUNG")) else 1,
                r.relation_type,
            ),
        )
        for ref in sorted_refs:
            dir_icon = "◄──" if ref.direction == "INCOMING" else "──►"
            hop_label = f"[Hop {ref.hop_level} : {ref.relation_type}]"
            target_str = ref.target_id
            if ref.title:
                target_str += f" ({ref.title})"
            label = f"{dir_icon} {hop_label} {target_str}"
            detail = _clean_snippet(ref.content)
            branches.append((label, detail))

        if not branches:
            lines.append("  └── (Không có quan hệ dẫn chiếu mở rộng)")
        else:
            for b_idx, (branch_label, branch_detail) in enumerate(branches):
                is_last = b_idx == len(branches) - 1
                tree_fork = "└── " if is_last else "├── "
                indent_pipe = "    " if is_last else "│   "
                lines.append(f"  {tree_fork}{branch_label}")
                if branch_detail:
                    lines.append(f"  {indent_pipe}  ↳ Nội dung: \"{branch_detail}\"")

    # Subgraph metrics summary
    subgraph = getattr(result, "subgraph", None) or getattr(
        result.evidence_package, "subgraph", None
    )
    if subgraph and (subgraph.nodes or subgraph.relationships):
        lines.append("\n" + "." * 80)
        node_counts: dict[str, int] = {}
        for n in subgraph.nodes:
            node_counts[n.label] = node_counts.get(n.label, 0) + 1
        node_summary = ", ".join(f"{k}: {v}" for k, v in sorted(node_counts.items()))

        rel_counts: dict[str, int] = {}
        for r in subgraph.relationships:
            rel_counts[r.type] = rel_counts.get(r.type, 0) + 1
        rel_summary = ", ".join(f"{k}: {v}" for k, v in sorted(rel_counts.items()))

        lines.append(
            f"📈 TỔNG KẾT KNOWLEDGE SUBGRAPH:\n"
            f"  • Nodes ({len(subgraph.nodes)}): {node_summary}\n"
            f"  • Quan hệ ({len(subgraph.relationships)}): {rel_summary}"
        )

    # Document-level amendments if present
    doc_ams = getattr(result.evidence_package, "document_amendments", [])
    if doc_ams:
        lines.append("\n📜 VĂN BẢN SỬA ĐỔI / THAY THẾ (DOCUMENT AMENDMENTS):")
        for da in doc_ams:
            lines.append(
                f"  • [{da.operation}] Mục tiêu: {da.target_id} | Chỉ dẫn: {da.instruction}"
            )

    return lines


def format_text_output(result) -> str:
    """Formats PipelineResult as a rich readable terminal output."""
    lines: list[str] = [
        "=" * 80,
        "🏛️  HỆ THỐNG TRẢ LỜI PHÁP LUẬT GIAO THÔNG",
        "=" * 80,
        f"❓ Câu hỏi của người dân: {result.user_query}",
    ]

    if result.rewritten_query and result.rewritten_query != result.user_query:
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

    # Visual Knowledge Graph Traversal paths
    lines.extend(format_graph_traversal_tree(result))

    if result.evidence_package.items:
        lines.append("-" * 80)
        lines.append("📊 ĐIỂM SỐ RETRIEVAL CÁC CHUNKS (RRF / DENSE / SPARSE):")
        for idx, item in enumerate(result.evidence_package.items, start=1):
            dense_str = (
                f"{item.dense_score:.4f} (#{item.dense_rank})"
                if item.dense_score is not None
                else "N/A"
            )
            sparse_str = (
                f"{item.sparse_score:.4f} (#{item.sparse_rank})"
                if item.sparse_score is not None
                else "N/A"
            )
            rrf_str = f"{item.score:.6f}" if item.score is not None else "N/A"
            lines.append(
                f"  [{idx}] {item.chunk_id}\n"
                f"      • RRF Score: {rrf_str} | Cosine (Dense): {dense_str} | BM25 (Sparse): {sparse_str}"
            )

    if result.evidence_package.has_superseded_provisions:
        lines.append(
            "\n⚠️  LƯU Ý HIỆU LỰC: Gói bằng chứng chứa quy định đã bị sửa đổi / thay thế hoặc hết hiệu lực."
        )

    lines.append("-" * 80)
    lines.extend(
        [
            f"⏱️ Thời gian xử lý: {result.execution_time_ms:.1f}ms | Bằng chứng: {len(result.evidence_package.items)} điều khoản",
            "=" * 80,
        ]
    )
    return "\n".join(lines)


def format_table_output(result) -> str:
    """Formats PipelineResult with tabulate grids of evidence items and graph traversal."""
    lines: list[str] = [
        format_text_output(result),
        "\n📋 CHI TIẾT BẰNG CHỨNG PHÁP LÝ (EVIDENCE PACKAGE):",
    ]

    table_data = []
    for idx, item in enumerate(result.evidence_package.items, start=1):
        prov = item.validated_provision
        status_disp = item.warning_flag or prov.status.value
        content = (prov.content_text or item.original_chunk_text).replace("\n", " ")
        preview = (content[:50] + "...") if len(content) > 50 else content
        rrf_disp = f"{item.score:.6f}" if item.score is not None else "N/A"
        dense_disp = (
            f"{item.dense_score:.4f} (#{item.dense_rank})"
            if item.dense_score is not None
            else "N/A"
        )
        sparse_disp = (
            f"{item.sparse_score:.4f} (#{item.sparse_rank})"
            if item.sparse_score is not None
            else "N/A"
        )

        table_data.append(
            [
                idx,
                prov.provision_id,
                rrf_disp,
                dense_disp,
                sparse_disp,
                prov.level,
                prov.parent_article_title or "-",
                status_disp,
                preview,
            ]
        )

    headers = [
        "#",
        "Provision ID",
        "RRF Score",
        "Cosine (Dense)",
        "BM25 (Sparse)",
        "Level",
        "Điều luật",
        "Trạng thái",
        "Nội dung trích dẫn",
    ]
    lines.append(tabulate(table_data, headers=headers, tablefmt="grid"))

    # Traversed Relationships Table
    traversal_rows = []
    t_idx = 1
    for item in result.evidence_package.items:
        prov = item.validated_provision
        for am in prov.amendments:
            dir_str = "◄── INCOMING" if am.direction == "INCOMING" else "──► OUTGOING"
            conn_node = (
                am.source_provision_id or am.by_document
                if am.direction == "INCOMING"
                else (am.target_provision_id or "-")
            )
            detail = _clean_snippet(am.replacement_text or am.instruction, 60)
            traversal_rows.append(
                [
                    t_idx,
                    prov.provision_id,
                    dir_str,
                    f"AMENDS ({am.operation})",
                    1,
                    conn_node or "-",
                    detail,
                ]
            )
            t_idx += 1
        for ref in prov.cross_references:
            dir_str = "◄── INCOMING" if ref.direction == "INCOMING" else "──► OUTGOING"
            detail = _clean_snippet(ref.content, 60)
            traversal_rows.append(
                [
                    t_idx,
                    prov.provision_id,
                    dir_str,
                    ref.relation_type,
                    ref.hop_level,
                    ref.target_id,
                    detail,
                ]
            )
            t_idx += 1

    if traversal_rows:
        lines.append("\n🕸️ CÁC QUAN HỆ GRAPH TRAVERSAL MỞ RỘNG (1-HOP & 2-HOP):")
        trav_headers = [
            "#",
            "Anchor Node",
            "Hướng",
            "Quan hệ",
            "Hop",
            "Node liên kết",
            "Nội dung trích đoạn",
        ]
        lines.append(tabulate(traversal_rows, headers=trav_headers, tablefmt="grid"))

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
