"""Các phép chuẩn hóa cần quan sát toàn bộ corpus sau khi parse từng văn bản."""

import json
from collections import defaultdict
from pathlib import Path

from src.parser.canonical_id_resolver import normalize_so_hieu


AMENDMENT_OPERATIONS = {
    "SUA_DOI", "BO_SUNG", "THAY_THE", "BAI_BO", "THEM_MOI",
    "BO_SUNG_TEXT", "THAY_THE_TEXT", "BAI_BO_TEXT", "THAY_THE_PHU_LUC",
}
OPERATION_PRIORITY = {
    "BAI_BO": 0, "BAI_BO_TEXT": 1, "THAY_THE": 2, "THAY_THE_TEXT": 3,
    "SUA_DOI": 4, "BO_SUNG": 5, "BO_SUNG_TEXT": 6, "THEM_MOI": 7,
    "THAY_THE_PHU_LUC": 8,
}


def _read(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _doc_prefix(unit_id: str) -> str:
    return unit_id.split("_D", 1)[0]


def collect_amendment_edges(root: Path) -> list[dict]:
    edges, seen = [], set()
    for path in sorted(root.glob("*/amendment_index.json")):
        for event in _read(path, []):
            source_doc = normalize_so_hieu(event.get("source_document"))
            target_doc = normalize_so_hieu(event.get("target_document"))
            for item in event.get("items", []):
                source = item.get("source_unit")
                for action in item.get("actions", []):
                    relation = action.get("operation")
                    if relation not in AMENDMENT_OPERATIONS:
                        continue
                    for target in action.get("targets", []):
                        target_id = target.get("target_unit")
                        if not source or not target_id:
                            continue
                        key = (source, target_id, relation)
                        if key in seen:
                            continue
                        seen.add(key)
                        edges.append({
                            "source": source, "target": target_id,
                            "relation": relation,
                            "source_document": source_doc,
                            "target_document": target_doc,
                            "resolution_status": action.get("resolution_status", "RESOLVED"),
                            "raw_instruction": action.get("raw_instruction"),
                        })
                    for created in action.get("created_units", []):
                        target_id = created.get("unit_id")
                        if source and target_id:
                            key = (source, target_id, "THEM_MOI")
                            if key not in seen:
                                seen.add(key)
                                edges.append({
                                    "source": source, "target": target_id,
                                    "relation": "THEM_MOI",
                                    "source_document": source_doc,
                                    "target_document": target_doc,
                                    "resolution_status": "RESOLVED",
                                    "raw_instruction": action.get("raw_instruction"),
                                })
    return edges


def _semantic_owns_event(semantic_id: str, event_source_id: str) -> bool:
    """Semantic unit cấp Khoản sở hữu các event cấp Điểm ngay bên dưới nó."""
    return event_source_id == semantic_id or event_source_id.startswith(semantic_id + "_D")


def sync_semantic_amendments(root: Path):
    """Dùng amendment workflow làm nguồn chuẩn cho hành động/đích semantic unit."""
    by_document = defaultdict(list)
    for path in sorted(root.glob("*/amendment_index.json")):
        for event in _read(path, []):
            source_document = normalize_so_hieu(event.get("source_document"))
            for item in event.get("items", []):
                source_unit = item.get("source_unit")
                if not source_unit:
                    continue
                for action in item.get("actions", []):
                    targets = [
                        target.get("target_context")
                        for target in action.get("targets", [])
                        if target.get("target_context")
                    ]
                    by_document[source_document].append({
                        "source_unit": source_unit,
                        "operation": action.get("operation"),
                        "targets": targets,
                    })

    for document, events in by_document.items():
        path = root / f"{document.replace('/', '_')}_semantic_units.json"
        units = _read(path, [])
        for unit in units:
            owned = [e for e in events if _semantic_owns_event(unit["id"], e["source_unit"])]
            if not owned:
                continue
            operations = sorted(
                {e["operation"] for e in owned if e.get("operation")},
                key=lambda value: OPERATION_PRIORITY.get(value, 99),
            )
            targets, seen = [], set()
            for event in owned:
                for context in event["targets"]:
                    article = context.get("article") or {}
                    clause = context.get("clause") or {}
                    point = context.get("point") or {}
                    target = {
                        "dieu": article.get("number"),
                        "khoan": clause.get("number"),
                        "diem": point.get("number"),
                        "so_hieu_van_ban": normalize_so_hieu(context.get("document")),
                    }
                    key = tuple(target.values())
                    if not target["dieu"] or key in seen:
                        continue
                    seen.add(key)
                    targets.append(target)
            unit["hanh_dong"] = operations[0] if operations else unit.get("hanh_dong", "GIU_NGUYEN")
            unit["hanh_dong_chi_tiet"] = operations
            unit["doi_tuong"] = targets
            unit["amendment_event_sources"] = sorted({e["source_unit"] for e in owned})
        _write(path, units)


def _mark_tree(node, affected: dict[str, list[dict]]):
    if isinstance(node, dict):
        unit_id = node.get("id")
        if unit_id in affected:
            changes = affected[unit_id]
            docs = sorted({x["source_document"] for x in changes})
            node["sua_doi_boi_van_ban"] = docs[-1] if len(docs) == 1 else docs
            node["amendment_history"] = changes
            if any(x["relation"] == "BAI_BO" for x in changes):
                node["trang_thai"] = "bai_bo"
            else:
                node["trang_thai"] = "da_sua_doi"
            node["phien_ban"] = "da_sua_doi"
        for value in node.values():
            _mark_tree(value, affected)
    elif isinstance(node, list):
        for value in node:
            _mark_tree(value, affected)


def backfill_original_documents(root: Path, edges: list[dict]):
    affected = defaultdict(list)
    for edge in edges:
        change = {
            "source_document": edge["source_document"],
            "source_unit": edge["source"],
            "relation": edge["relation"],
            "target_unit": edge["target"],
        }
        affected[edge["target"]].append(change)
        # Điều cha cũng phải biết một Khoản/Điểm bên trong đã bị tác động.
        article_id = edge["target"].split("_K", 1)[0]
        if article_id != edge["target"]:
            parent_change = dict(change)
            parent_change["relation"] = "CO_NOI_DUNG_BI_SUA_DOI"
            affected[article_id].append(parent_change)
    for path in sorted(root.glob("*_structure.json")):
        data = _read(path)
        _mark_tree(data, affected)
        _write(path, data)
    for path in sorted(root.glob("*_semantic_units.json")):
        units = _read(path, [])
        for unit in units:
            changes = affected.get(unit.get("id"), [])
            if changes:
                docs = sorted({x["source_document"] for x in changes})
                unit["sua_doi_boi_van_ban"] = docs[-1] if len(docs) == 1 else docs
                unit["amendment_history"] = changes
                unit["trang_thai"] = "bai_bo" if any(x["relation"] == "BAI_BO" for x in changes) else "da_sua_doi"
                unit["phien_ban"] = "da_sua_doi"
        _write(path, units)


def mark_external_references(root: Path):
    corpus_prefixes = {_doc_prefix(p.name.removesuffix("_structure.json")) for p in root.glob("*_structure.json")}
    external_nodes = {}
    for path in sorted(root.glob("*_reference_index.json")):
        edges = _read(path, [])
        for edge in edges:
            prefix = _doc_prefix(edge["target"])
            edge["external"] = prefix not in corpus_prefixes
            if edge["external"]:
                external_nodes.setdefault(edge["target"], {
                    "id": edge["target"], "external": True,
                    "node_type": "EXTERNAL_LEGAL_LOCATION",
                    "document_id": prefix,
                })
        _write(path, edges)
    _write(root / "external_nodes.json", sorted(external_nodes.values(), key=lambda x: x["id"]))


def materialize_effective_support(root: Path):
    selected_ids = set()
    for path in root.glob("*_structure.json"):
        def walk(value):
            if isinstance(value, dict):
                if value.get("id"): selected_ids.add(value["id"])
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(_read(path))
    support = {}
    for path in root.glob("*_effective_rules.json"):
        payload = _read(path, {})
        doc_id = payload.get("document_id")
        for rule in payload.get("rules", []):
            source_id = f"{doc_id}_D{rule['source_article']}"
            if rule.get("source_clause"):
                source_id += f"_K{rule['source_clause']}"
            if source_id not in selected_ids:
                support[source_id] = {
                    "id": source_id, "node_type": "EFFECTIVE_RULE_SUPPORT",
                    "document": payload.get("document"), "external": False,
                    "source_article": rule.get("source_article"),
                    "source_clause": rule.get("source_clause"),
                    "raw_text": rule.get("raw_text"),
                }
            rule["source_unit"] = source_id
            rule["source_unit_materialized_as_support"] = source_id not in selected_ids
            for target in rule.get("targets", []):
                target_id = target.get("unit_id")
                if target_id and target_id not in selected_ids:
                    support.setdefault(target_id, {
                        "id": target_id, "node_type": "EFFECTIVE_RULE_TARGET_SUPPORT",
                        "document": rule.get("target_document") or payload.get("document"),
                        "external": False,
                    })
        _write(path, payload)
    _write(root / "effective_support_nodes.json", sorted(support.values(), key=lambda x: x["id"]))


def disambiguate_full_structure_ids(root: Path):
    report = []
    for path in root.glob("*_structure.full.json"):
        data = _read(path)
        counts = defaultdict(int)
        def walk(value, parent_id=None):
            if isinstance(value, dict):
                old = value.get("id")
                if old:
                    counts[old] += 1
                    if counts[old] > 1:
                        new = f"{old}__occ{counts[old]}"
                        value["id"] = new
                        value["id_goc_trung"] = old
                        report.append({"file": path.name, "original_id": old, "new_id": new})
                    if parent_id and "id_cha" in value:
                        value["id_cha"] = parent_id
                    parent_id = value["id"]
                for child in value.values(): walk(child, parent_id)
            elif isinstance(value, list):
                for child in value: walk(child, parent_id)
        walk(data)
        _write(path, data)
    _write(root / "duplicate_id_repairs.json", report)


def run(parsed_dir="data/parsed"):
    root = Path(parsed_dir)
    sync_semantic_amendments(root)
    edges = collect_amendment_edges(root)
    _write(root / "amendment_relations.json", edges)
    backfill_original_documents(root, edges)
    mark_external_references(root)
    materialize_effective_support(root)
    disambiguate_full_structure_ids(root)
    return {"amendment_edges": len(edges)}
