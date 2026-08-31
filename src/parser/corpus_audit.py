"""Audit định lượng các yêu cầu chất lượng nêu trong báo cáo dữ liệu."""

import json
from collections import Counter
from pathlib import Path


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run(parsed_dir="data/parsed"):
    root = Path(parsed_dir)
    amendment_edges = _read(root / "amendment_relations.json")
    external_nodes = _read(root / "external_nodes.json")
    support_nodes = _read(root / "effective_support_nodes.json")
    id_repairs = _read(root / "duplicate_id_repairs.json")

    duplicate_references = []
    wrong_184_target = []
    correct_184_target = False
    external_edges = 0
    for path in root.glob("*_reference_index.json"):
        edges = _read(path)
        counts = Counter((x["source"], x["target"], x["relation"]) for x in edges)
        duplicate_references.extend(k for k, count in counts.items() if count > 1)
        external_edges += sum(bool(x.get("external")) for x in edges)
        for edge in edges:
            if edge["source"] != "184_2025_ND-CP_D27_K4":
                continue
            if edge["target"] == "151_2024_ND-CP_D12_K1_Dđ":
                correct_184_target = True
            if edge["target"] == "184_2025_ND-CP_D27_K1_Dđ":
                wrong_184_target.append(edge)

    unresolved_amendment_targets = []
    semantic_target_mismatches = []
    event_targets = {}
    for path in root.glob("*/amendment_index.json"):
        for event in _read(path):
            for item in event.get("items", []):
                for action in item.get("actions", []):
                    for target in action.get("targets", []):
                        target_id = target.get("target_unit")
                        if target_id:
                            event_targets.setdefault(item.get("source_unit"), set()).add(target_id)
    for doc in ("118_2025_QH15", "184_2025_ND-CP", "236_2026_ND-CP", "238_2026_ND-CP"):
        for unit in _read(root / f"{doc}_semantic_units.json"):
            unresolved_amendment_targets.extend(
                (unit["id"], target) for target in unit.get("doi_tuong", [])
                if not target.get("so_hieu_van_ban")
            )
            expected = set()
            for source_id, targets in event_targets.items():
                if source_id == unit["id"] or source_id.startswith(unit["id"] + "_D"):
                    expected.update(targets)
            actual = set()
            for target in unit.get("doi_tuong", []):
                if target.get("dieu") and target.get("so_hieu_van_ban"):
                    target_id = target["so_hieu_van_ban"].replace("/", "_") + "_D" + target["dieu"]
                    if target.get("khoan"):
                        target_id += "_K" + target["khoan"]
                    if target.get("diem"):
                        target_id += "_D" + target["diem"]
                    actual.add(target_id)
            if expected and expected != actual:
                semantic_target_mismatches.append({
                    "unit": unit["id"], "missing": sorted(expected - actual),
                    "unexpected": sorted(actual - expected),
                })

    backfilled_units = 0
    for doc in ("35_2024_QH15", "36_2024_QH15", "151_2024_ND-CP", "168_2024_ND-CP", "184_2025_ND-CP"):
        backfilled_units += sum(
            bool(x.get("sua_doi_boi_van_ban"))
            for x in _read(root / f"{doc}_semantic_units.json")
        )

    cross_document_counts = {}
    for doc in ("151_2024_ND-CP", "156_2024_ND-CP", "160_2024_ND-CP", "168_2024_ND-CP"):
        edges = _read(root / f"{doc}_reference_index.json")
        cross_document_counts[doc] = sum(
            edge["target"].startswith(("35_2024_QH15", "36_2024_QH15"))
            for edge in edges
        )

    report = {
        "issue_1_backfill_originals": {"pass": backfilled_units > 0, "marked_units": backfilled_units},
        "issue_2_amendment_edges": {"pass": bool(amendment_edges), "edge_count": len(amendment_edges)},
        "issue_3_target_documents": {
            "pass": not unresolved_amendment_targets and not semantic_target_mismatches,
            "unresolved": unresolved_amendment_targets,
            "semantic_target_mismatches": semantic_target_mismatches,
        },
        "issue_4_quoted_context": {"pass": correct_184_target and not wrong_184_target, "correct_edge_present": correct_184_target, "wrong_edges": wrong_184_target},
        "issue_5_deduplication": {"pass": not duplicate_references, "duplicates": duplicate_references},
        "issue_6_effective_support": {"pass": bool(support_nodes), "support_node_count": len(support_nodes)},
        "issue_7_duplicate_ids": {"pass": len(id_repairs) >= 2, "repairs": id_repairs},
        "issue_8_external_references": {"pass": external_edges > 0 and bool(external_nodes), "external_edges": external_edges, "external_nodes": len(external_nodes)},
        "issue_9_cross_document": {
            "pass": all(count > 0 for count in cross_document_counts.values()),
            "edge_counts": cross_document_counts,
        },
    }
    report["all_pass"] = all(item["pass"] for key, item in report.items() if key.startswith("issue_"))
    (root / "corpus_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
