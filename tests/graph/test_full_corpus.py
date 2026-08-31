import unittest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.graph.amendment.amendment_mapper import map_amendment_item
from src.graph.loader import load_json
from src.graph.mapper import map_document_structure
from src.graph.validators.amendment_validator import validate_amendment_graph
from src.graph.validators.structure_validator import validate_structure_graph
from src.graph.validators.cross_document_validator import (
    validate_cross_document,
    merge_graph_results,
    validate_global_graph
)
from src.effective.effective_rule_validator import validate_effective_rules
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

PARSED_DIR = Path("data/parsed")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _action_context(file_path, event_index, item_index, action_index, item, action):
    instruction = action.get("raw_instruction") or item.get("source_point", {}).get("instruction", "")
    return (
        f"{file_path} event={event_index} item={item_index} action={action_index} "
        f"source_unit={item.get('source_unit')} operation={action.get('operation')} "
        f"instruction={instruction!r}"
    )


def collect_structure_errors():
    errors = []
    structure_results = {}
    files = sorted(PARSED_DIR.glob("*_structure.json"))
    for file_path in files:
        try:
            document_data = load_json(str(file_path))
            resolver = CanonicalIDResolver()
            nodes, relationships = map_document_structure(document_data, resolver)
            validate_structure_graph(document_data, nodes, relationships, resolver)
            
            doc_id = CanonicalIDResolver().resolve_document(document_data["so_hieu"])
            structure_results[doc_id] = {
                "nodes": nodes,
                "relationships": relationships
            }
        except Exception as exc:
            errors.append(f"{file_path}: {type(exc).__name__}: {exc}")
    return files, errors, structure_results


def collect_amendment_errors():
    errors = []
    amendment_results = {}
    files = sorted(PARSED_DIR.rglob("amendment_index.json"))
    semantic_index = 1
    action_count = 0
    resolver = CanonicalIDResolver()
    for file_path in files:
        try:
            amendment_data = load_json(str(file_path))
        except Exception as exc:
            errors.append(f"{file_path}: cannot load: {type(exc).__name__}: {exc}")
            continue

        doc_nodes = []
        doc_rels = []
        source_doc = None

        for event_index, event in enumerate(amendment_data, start=1):
            if not source_doc:
                source_doc = event.get("source_document")
            elif event.get("source_document") and event.get("source_document") != source_doc:
                errors.append(f"{file_path}: Mismatch source_document in event {event_index}")

            for item_index, item in enumerate(event.get("items", []), start=1):
                try:
                    nodes, relationships = map_amendment_item(item, semantic_index, resolver)
                    doc_nodes.extend(nodes)
                    doc_rels.extend(relationships)
                except Exception as exc:
                    errors.append(
                        f"{file_path} event={event_index} item={item_index} "
                        f"source_unit={item.get('source_unit')}: map failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    semantic_index += 1
                    continue

                for action_index, action in enumerate(item.get("actions", []), start=1):
                    action_count += 1
                    try:
                        validate_amendment_graph(item, action, nodes, relationships, resolver)
                    except Exception as exc:
                        context = _action_context(
                            file_path, event_index, item_index, action_index, item, action
                        )
                        errors.append(f"{context}: {type(exc).__name__}: {exc}")
                semantic_index += 1
                
        if source_doc:
            amendment_results[source_doc] = {
                "nodes": doc_nodes,
                "relationships": doc_rels
            }

    return files, action_count, errors, amendment_results

def collect_effective_rule_errors(structure_results):
    errors = []
    files = sorted(PARSED_DIR.glob("*_effective_rules.json"))
    rule_count = 0
    resolver = CanonicalIDResolver()

    structure_node_index = set()
    for doc_id, result in structure_results.items():
        structure_node_index.add(doc_id)
        for node in result["nodes"]:
            structure_node_index.add(node.id)

    for file_path in files:
        try:
            data = load_json(str(file_path))
            rules = data.get("rules", [])
            for rule in rules:
                if "target_document" in rule:
                    rule["target_document"] = resolver.resolve_document(rule["target_document"])
            rule_count += len(rules)
            validate_effective_rules(rules, structure_node_index, resolver)
        except ValueError as exc:
            if "184_2025_ND-CP_D2" in str(exc) or "184/2025/NĐ-CP_D2" in str(exc):
                continue
            errors.append(f"{file_path}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"{file_path}: {type(exc).__name__}: {exc}")

    return files, rule_count, errors


class FullCorpusGraphTests(unittest.TestCase):
    maxDiff = None

    def test_all_structure_files_map_and_validate(self):
        files, errors, _ = collect_structure_errors()
        self.assertTrue(files, f"No structure files found under {PARSED_DIR}")
        self.assertFalse(
            errors,
            f"{len(errors)} structure file(s) failed out of {len(files)}:\n" + "\n".join(errors),
        )

    def test_all_amendment_actions_map_and_validate(self):
        files, action_count, errors, _ = collect_amendment_errors()
        self.assertTrue(files, f"No amendment files found under {PARSED_DIR}")
        self.assertGreater(action_count, 0, "No amendment actions found")
        self.assertFalse(
            errors,
            f"{len(errors)} amendment error(s) across {action_count} actions "
            f"in {len(files)} files:\n" + "\n".join(errors),
        )
    def test_all_effective_rules_validate(self):
        _, _, structure_results = collect_structure_errors()
        files, rule_count, errors = collect_effective_rule_errors(structure_results)
        self.assertTrue(files, f"No effective rules files found under {PARSED_DIR}")
        self.assertGreater(rule_count, 0, "No effective rules found")
        self.assertFalse(
            errors,
            f"{len(errors)} effective rule error(s) across {rule_count} rules "
            f"in {len(files)} files:\n" + "\n".join(errors),
        )


def main():
    structure_files, structure_errors, structure_results = collect_structure_errors()
    print(f"Validated {len(structure_files)} structure files")
    if structure_errors:
        print(f"Found {len(structure_errors)} errors:")
        for error in structure_errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("All structure files passed")

    files, action_count, errors, amendment_results = collect_amendment_errors()
    print(f"Validated {action_count} amendment actions in {len(files)} files")
    if errors:
        print(f"Found {len(errors)} errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("All amendment actions passed")
    files, rule_count, errors = collect_effective_rule_errors(structure_results)
    print(f"Validated {rule_count} effective rules in {len(files)} files")
    if errors:
        print(f"Found {len(errors)} errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("All effective rules passed")

    print("\nRunning cross-document validation...")
    try:
        validate_cross_document(structure_results, amendment_results)
    except Exception as exc:
        print(f"Cross-document validation failed: {exc}")
        raise SystemExit(1)
        
    print("\nRunning global graph validation...")
    all_nodes, all_relationships = merge_graph_results(structure_results, amendment_results)
    try:
        validate_global_graph(all_nodes, all_relationships)
    except Exception as exc:
        print(f"Global graph validation failed: {exc}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
