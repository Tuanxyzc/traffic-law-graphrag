"""CLI Entrypoint for Traffic Law GraphRAG Evaluation & Benchmarking."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from tabulate import tabulate

from src.eval.evaluator import EvaluationOrchestrator
from src.eval.exporter import EvaluationExporter
from src.eval.models import EvaluationSample

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("src.eval")

DEFAULT_DATASET_PATH = Path("data/eval/golden_dataset.json")
DEFAULT_OUTPUT_DIR = Path("reports/eval")


def load_dataset_from_json(path: Path) -> list[EvaluationSample]:
    """Loads evaluation dataset from JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Evaluation dataset file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [EvaluationSample.model_validate(item) for item in data]


def handle_run(args: argparse.Namespace) -> int:
    """Executes evaluation run on the target dataset."""
    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET_PATH
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n=======================================================")
    print("      TRAFFIC LAW GRAPHRAG EVALUATION BENCHMARK        ")
    print("=======================================================")
    print(f"Dataset:       {dataset_path}")
    print(f"Tier:          {args.tier.upper()}")
    print(f"Output dir:    {output_dir}")
    print("-------------------------------------------------------\n")

    samples = load_dataset_from_json(dataset_path)
    if args.limit and args.limit > 0:
        samples = samples[: args.limit]
        print(f"Evaluating subset limited to {len(samples)} samples.\n")

    orchestrator = EvaluationOrchestrator(tier=args.tier)
    summary = orchestrator.evaluate_dataset(samples)

    # 1. Export Excel Report
    excel_path = output_dir / "eval_results_latest.xlsx"
    EvaluationExporter.export_to_excel(summary, excel_path)

    # 2. Export CSV Report
    csv_path = output_dir / "eval_results_latest.csv"
    EvaluationExporter.export_to_csv(summary, csv_path)

    # 3. Export JSON Summary
    summary_path = output_dir / "eval_summary_latest.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary.model_dump_json(indent=2))

    # 4. Print Summary Terminal Table
    print("\n================== BENCHMARK SUMMARY ===================")
    kpi_table: list[list[Any]] = [
        ["Total Samples Evaluated", summary.total_samples],
        ["Overall Passed Samples", f"{summary.passed_samples} ({summary.overall_pass_rate * 100:.1f}%)"],
        ["Average Provision Recall", f"{summary.avg_provision_recall * 100:.1f}%"],
        ["Average Provision Precision", f"{summary.avg_provision_precision * 100:.1f}%"],
        ["Fine Amount Accuracy", f"{summary.fine_accuracy * 100:.1f}%"],
        ["Warning/Amendment Accuracy", f"{summary.warning_accuracy * 100:.1f}%"],
    ]

    if summary.tier == "full":
        kpi_table.extend([
            ["RAGAS Faithfulness", f"{summary.avg_faithfulness * 100:.1f}%" if summary.avg_faithfulness is not None else "N/A"],
            ["RAGAS Answer Relevancy", f"{summary.avg_answer_relevancy * 100:.1f}%" if summary.avg_answer_relevancy is not None else "N/A"],
            ["RAGAS Context Precision", f"{summary.avg_context_precision * 100:.1f}%" if summary.avg_context_precision is not None else "N/A"],
            ["RAGAS Context Recall", f"{summary.avg_context_recall * 100:.1f}%" if summary.avg_context_recall is not None else "N/A"],
        ])

    kpi_table.append(["Average Pipeline Latency", f"{summary.avg_latency_ms:.1f} ms"])
    print(tabulate(kpi_table, headers=["Metric", "Result"], tablefmt="grid"))

    print("\nReports generated:")
    print(f" - Excel:   {excel_path.resolve()}")
    print(f" - CSV:     {csv_path.resolve()}")
    print(f" - Summary: {summary_path.resolve()}")
    print("=======================================================\n")

    return 0 if summary.overall_pass_rate >= 0.70 else 1


def handle_export_excel(args: argparse.Namespace) -> int:
    """Exports dataset JSON to Excel for spreadsheet editing."""
    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET_PATH
    output_path = (
        Path(args.output) if args.output else dataset_path.with_suffix(".xlsx")
    )

    samples = load_dataset_from_json(dataset_path)
    EvaluationExporter.export_dataset_to_excel(samples, output_path)
    print(f"Exported {len(samples)} samples to Excel: {output_path.resolve()}")
    return 0


def handle_import_excel(args: argparse.Namespace) -> int:
    """Imports modified test cases from Excel back into JSON dataset."""
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else DEFAULT_DATASET_PATH

    samples = EvaluationExporter.import_dataset_from_excel(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json_data = [s.model_dump(mode="json") for s in samples]
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    print(
        f"Imported and validated {len(samples)} samples from Excel to JSON: {output_path.resolve()}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.eval",
        description="Evaluation & Benchmarking CLI for Traffic Law GraphRAG.",
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Subcommands: run, export-excel, import-excel"
    )

    # 1. Run command
    run_parser = subparsers.add_parser(
        "run", help="Run evaluation benchmark on golden dataset"
    )
    run_parser.add_argument(
        "--dataset", type=str, default=None, help="Path to golden dataset JSON"
    )
    run_parser.add_argument(
        "--tier",
        choices=["deterministic", "full"],
        default="deterministic",
        help="Evaluation tier: 'deterministic' (fast, 0 tokens) or 'full' (+ RAGAS LLM-as-a-judge)",
    )
    run_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for reports (default: reports/eval)",
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of test samples to evaluate",
    )

    # 2. Export Excel command
    export_parser = subparsers.add_parser(
        "export-excel", help="Export JSON dataset to Excel for editing"
    )
    export_parser.add_argument(
        "--dataset", type=str, default=None, help="Path to source dataset JSON"
    )
    export_parser.add_argument(
        "--output", type=str, default=None, help="Path to output Excel file"
    )

    # 3. Import Excel command
    import_parser = subparsers.add_parser(
        "import-excel", help="Import modified Excel test cases into JSON"
    )
    import_parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to input edited Excel file",
    )
    import_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to output JSON file (default: data/eval/golden_dataset.json)",
    )

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(handle_run(args))
    elif args.command == "export-excel":
        sys.exit(handle_export_excel(args))
    elif args.command == "import-excel":
        sys.exit(handle_import_excel(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
