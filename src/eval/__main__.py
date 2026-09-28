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
from src.eval.models import (
    DeterministicBenchmarkItem,
    EvaluationSample,
    TestCategory,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("src.eval")

DEFAULT_DATASET_PATH = Path("data/eval/golden_dataset.json")
DEFAULT_OUTPUT_DIR = Path("reports/eval")


def load_deterministic_dataset(path: Path) -> list[DeterministicBenchmarkItem]:
    """Loads and validates deterministic golden dataset from JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Evaluation dataset file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [DeterministicBenchmarkItem.model_validate(item) for item in data]


def load_legacy_dataset(path: Path) -> list[EvaluationSample]:
    """Loads evaluation dataset using legacy schema for backward compatibility."""
    if not path.exists():
        raise FileNotFoundError(f"Evaluation dataset file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [EvaluationSample.model_validate(item) for item in data]


def handle_validate(args: argparse.Namespace) -> int:
    """Validates target dataset JSON file against DeterministicBenchmarkItem schema."""
    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET_PATH
    print("\n=======================================================")
    print("      DATASET VALIDATION: DETERMINISTIC BENCHMARK      ")
    print("=======================================================")
    print(f"Target: {dataset_path.resolve()}\n")

    try:
        items = load_deterministic_dataset(dataset_path)
    except Exception as exc:
        print(f"[FAILED] VALIDATION FAILED: {exc}")
        return 1

    cat_counts: dict[str, int] = {}
    for it in items:
        cat_counts[it.category.value] = cat_counts.get(it.category.value, 0) + 1

    table = [[cat, cat_counts.get(cat, 0)] for cat in [c.value for c in TestCategory]]
    table.append(["--- TOTAL ---", len(items)])

    print(tabulate(table, headers=["Category", "Count"], tablefmt="grid"))
    print(
        "\n[PASSED] DATASET INTEGRITY VERIFIED: 100% compliant with DeterministicBenchmarkItem schema.\n"
    )
    return 0


def handle_run(args: argparse.Namespace) -> int:
    """Executes evaluation run on the target dataset."""
    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET_PATH
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    mode = args.mode or ("e2e" if args.tier == "full" else "retrieval")

    print("\n=======================================================")
    print("      TRAFFIC LAW GRAPHRAG DETERMINISTIC BENCHMARK     ")
    print("=======================================================")
    print(f"Dataset:       {dataset_path}")
    print(
        f"Mode:          {mode.upper()} ({'Retrieval-Only (0 tokens)' if mode == 'retrieval' else 'End-to-End with LLM Generate'})"
    )
    print(f"Output dir:    {output_dir}")
    print("-------------------------------------------------------\n")

    try:
        items = load_deterministic_dataset(dataset_path)
    except Exception as err:
        logger.warning(
            "Could not load deterministic items directly (%s), falling back to legacy.",
            err,
        )
        samples = load_legacy_dataset(dataset_path)
        orchestrator = EvaluationOrchestrator(tier=args.tier or "deterministic")
        summary = orchestrator.evaluate_dataset(samples)
        summary_path = output_dir / "eval_summary_latest.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary.model_dump_json(indent=2))
        return 0 if summary.overall_pass_rate >= 0.70 else 1

    if args.limit and args.limit > 0:
        items = items[: args.limit]
        print(f"Evaluating subset limited to {len(items)} items.\n")

    orchestrator = EvaluationOrchestrator()
    summary_det = orchestrator.evaluate_deterministic_dataset(items, mode=mode)

    # 1. Export JSON Summary & Excel Report
    summary_path = output_dir / f"benchmark_{mode}_summary_latest.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_det.model_dump_json(indent=2))

    excel_path = output_dir / f"benchmark_{mode}_summary_latest.xlsx"
    EvaluationExporter.export_deterministic_benchmark_to_excel(summary_det, excel_path)

    # 2. Print Summary Terminal Table
    print("\n================== BENCHMARK SUMMARY ===================")
    kpi_table: list[list[Any]] = [
        ["Benchmark Mode", summary_det.mode.upper()],
        ["Total Test Cases", summary_det.total_samples],
        [
            "Overall Passed",
            f"{summary_det.passed_samples} ({summary_det.overall_pass_rate * 100:.1f}%)",
        ],
        [
            "Retrieval Pass Rate (Set Theory)",
            f"{summary_det.retrieval_pass_rate * 100:.1f}%",
        ],
    ]

    if summary_det.generation_pass_rate is not None:
        kpi_table.append(
            [
                "Generation Pass Rate (Slot/Regex)",
                f"{summary_det.generation_pass_rate * 100:.1f}%",
            ]
        )

    print(tabulate(kpi_table, headers=["Metric", "Result"], tablefmt="grid"))

    # 3. Print Root-Cause Attribution Table if failures exist
    failures = [r for r in summary_det.results if not r.overall_passed]
    if failures:
        print("\n============= FAILURE ROOT-CAUSE ATTRIBUTION ============")
        rc_table: list[list[Any]] = [
            [rc, count]
            for rc, count in summary_det.root_cause_counts.items()
            if rc != "NONE"
        ]
        print(
            tabulate(rc_table, headers=["Failure Root Cause", "Count"], tablefmt="grid")
        )

        print("\nFailed Test Cases Details:")
        fail_details: list[list[Any]] = []
        for f_item in failures[:10]:  # Show up to 10
            fail_details.append(
                [
                    f_item.test_id,
                    f_item.category.value,
                    f_item.root_cause.value,
                    f"{f_item.execution_time_ms:.1f}ms",
                ]
            )
        print(
            tabulate(
                fail_details,
                headers=["ID", "Category", "Root Cause", "Latency"],
                tablefmt="grid",
            )
        )
        if len(failures) > 10:
            print(
                f"... and {len(failures) - 10} more failures (see {summary_path.resolve()})"
            )

    print("\nReport saved to:")
    print(f" - JSON:  {summary_path.resolve()}")
    print(f" - Excel: {excel_path.resolve()}")
    print("=======================================================\n")

    return 0 if summary_det.overall_pass_rate >= 0.70 else 1


def handle_export_excel(args: argparse.Namespace) -> int:
    """Exports dataset JSON to Excel for spreadsheet editing."""
    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET_PATH
    output_path = (
        Path(args.output) if args.output else dataset_path.with_suffix(".xlsx")
    )

    samples = load_legacy_dataset(dataset_path)
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
        dest="command",
        help="Subcommands: run, validate-dataset, export-excel, import-excel",
    )

    # 1. Run command
    run_parser = subparsers.add_parser(
        "run", help="Run evaluation benchmark on golden dataset"
    )
    run_parser.add_argument(
        "--dataset", type=str, default=None, help="Path to golden dataset JSON"
    )
    run_parser.add_argument(
        "--mode",
        choices=["retrieval", "e2e"],
        default="retrieval",
        help="Benchmark mode: 'retrieval' (Retrieval-Only, 0 tokens) or 'e2e' (Full End-to-End with Generator)",
    )
    run_parser.add_argument(
        "--tier",
        choices=["deterministic", "full"],
        default=None,
        help="Legacy tier alias: 'deterministic' -> mode=retrieval, 'full' -> mode=e2e",
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

    # 2. Validate Dataset command
    val_parser = subparsers.add_parser(
        "validate-dataset", help="Validate golden dataset JSON against Pydantic schema"
    )
    val_parser.add_argument(
        "--dataset", type=str, default=None, help="Path to golden dataset JSON"
    )

    # 3. Export Excel command
    export_parser = subparsers.add_parser(
        "export-excel", help="Export JSON dataset to Excel for editing"
    )
    export_parser.add_argument(
        "--dataset", type=str, default=None, help="Path to source dataset JSON"
    )
    export_parser.add_argument(
        "--output", type=str, default=None, help="Path to output Excel file"
    )

    # 4. Import Excel command
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
    elif args.command == "validate-dataset":
        sys.exit(handle_validate(args))
    elif args.command == "export-excel":
        sys.exit(handle_export_excel(args))
    elif args.command == "import-excel":
        sys.exit(handle_import_excel(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
