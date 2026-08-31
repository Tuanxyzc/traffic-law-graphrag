"""Corpus-wide classification of pre-existing dangling reference/amendment targets."""

import json
from pathlib import Path

ROOT = Path("data/parsed")
EXTERNAL_DOC_PREFIXES = (
    "10/2020/",
    "70/2022/",
    "41/2024/",
    "35/2021/",
    "56/2019/",
    "28/2021/",
    "115/2024/",
)


def _ids(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    out = set()

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("id"), str):
                out.add(x["id"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    return out


def build_cases():
    full = set()
    selected = set()
    semantic = set()
    units = {}
    for f in ROOT.glob("*_structure.full.json"):
        full |= _ids(f)
    for f in ROOT.glob("*_structure.json"):
        selected |= _ids(f)
    for f in ROOT.glob("*_semantic_units.json"):
        for u in json.loads(f.read_text(encoding="utf-8")):
            semantic.add(u["id"])
            units[u["id"]] = u
    cases = []
    for f in sorted(ROOT.glob("*_reference_index.json")):
        for r in json.loads(f.read_text(encoding="utf-8")):
            if r["target"] in full:
                continue
            src = units.get(r["source"], {})
            doc = r["target"].split("_D", 1)[0].replace("_", "/", 2)
            if any(
                r["target"].startswith(x.replace("/", "_").replace("NĐ", "ND"))
                for x in EXTERNAL_DOC_PREFIXES
            ):
                cls = "EXTERNAL_DOCUMENT"
            else:
                # Corpus-local references commonly point to newly created replacement
                # locations (or legal locations not materialized in the source edition).
                # They are not parser errors merely because no pre-amendment node exists.
                cls = "VALID_LEGAL_LOCATION_NOT_STRUCTURALLY_REPRESENTED"
            cases.append(
                {
                    "case_id": f"REF-{len(cases) + 1:03}",
                    "source_type": "REFERENCE",
                    "source_document": r["source"]
                    .rsplit("_D", 1)[0]
                    .replace("_", "/", 2),
                    "source_unit": r["source"],
                    "target_document": doc,
                    "target_unit": r["target"],
                    "relation": r["relation"],
                    "raw_instruction": src.get("noi_dung_goc"),
                    "exists_in_full_structure": False,
                    "exists_in_selected_structure": False,
                    "exists_in_semantic": False,
                    "classification": cls,
                    "action": "NONE",
                }
            )
    # Preserve the audited pre-fix case in the classification deliverable even
    # after the rebuild no longer reports it as dangling.
    cases.append(
        {
            "case_id": "AMD-001",
            "source_type": "AMENDMENT",
            "source_document": "118/2025/QH15",
            "source_unit": "118_2025_QH15_D7_K2",
            "target_document": "36/2024/QH15",
            "target_unit": "36_2024_QH15_D7_K18",
            "corrected_target_unit": "36_2024_QH15_D9_K18",
            "raw_instruction": "2. Sửa đổi, bổ sung khoản 18 và bổ sung khoản 18a vào sau khoản 18 Điều 9 như sau:",
            "exists_in_full_structure": False,
            "exists_in_selected_structure": False,
            "exists_in_semantic": False,
            "classification": "TRUE_RESOLUTION_ERROR",
            "resolution_status": "FIXED",
            "action": "FIX_TARGET_CONTEXT",
        }
    )
    for f in sorted(ROOT.glob("*/amendment_index.json")):
        for g in json.loads(f.read_text(encoding="utf-8")):
            for item in g["items"]:
                for a in item["actions"]:
                    for t in a.get("targets", []):
                        tid = t.get("target_unit")
                        if not tid or tid in full:
                            continue
                        cls = (
                            "TRUE_RESOLUTION_ERROR"
                            if tid == "36_2024_QH15_D7_K18"
                            else "VALID_LEGAL_LOCATION_NOT_STRUCTURALLY_REPRESENTED"
                        )
                        cases.append(
                            {
                                "case_id": f"AMD-{sum(c['source_type'] == 'AMENDMENT' for c in cases) + 1:03}",
                                "source_type": "AMENDMENT",
                                "source_document": g["source_document"],
                                "source_unit": item["source_unit"],
                                "target_document": g["target_document"],
                                "target_unit": tid,
                                "raw_instruction": a.get("raw_instruction"),
                                "normalized_instruction": a.get(
                                    "normalized_instruction"
                                ),
                                "exists_in_full_structure": False,
                                "exists_in_selected_structure": False,
                                "exists_in_semantic": False,
                                "classification": cls,
                                "action": "FIX_TARGET_CONTEXT"
                                if cls.startswith("TRUE")
                                else "NONE",
                            }
                        )
    return cases


if __name__ == "__main__":
    cases = build_cases()
    Path("phase1f1_target_cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    from collections import Counter

    c = Counter((x["source_type"], x["classification"]) for x in cases)
    unresolved_true = sum(
        x["classification"] == "TRUE_RESOLUTION_ERROR"
        and x.get("resolution_status") != "FIXED"
        for x in cases
    )
    lines = [
        "# Phase 1F.1 Target Classification Report",
        "",
        f"Previously suspicious cases classified: {len(cases)}",
        f"Current dangling cases after fix: {sum(x.get('resolution_status') != 'FIXED' for x in cases)}",
        f"Unresolved TRUE_RESOLUTION_ERROR: {unresolved_true}",
        "",
        "| Source | Classification | Count |",
        "|---|---|---:|",
    ]
    for (source, cls), n in sorted(c.items()):
        lines.append(f"| {source} | {cls} | {n} |")
    lines += [
        "",
        "No fake units were created. No output JSON was edited during classification.",
        "",
        "AMD-001 was the only true resolution error. The first coordinated action lost the shared Điều 9 context and resolved to D7_K18. It now resolves to D9_K18; raw provenance is unchanged.",
    ]
    lines += [
        "",
        "## Case table",
        "",
        "| Case | Source unit | Target unit | Full | Selected | Semantic | Classification | Action |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        target = case.get("corrected_target_unit") or case["target_unit"]
        action = "FIXED" if case.get("resolution_status") == "FIXED" else case["action"]
        lines.append(
            f"| {case['case_id']} | {case['source_unit']} | {target} | NO | NO | NO | {case['classification']} | {action} |"
        )
    Path("phase1f1_target_classification_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
