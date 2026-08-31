import os
from collections import Counter

from src.graph.loader import load_json

OPERATIONS_TO_INSPECT = [
    "SUA_DOI",
    "BAI_BO",
    "BO_SUNG",
    "BO_SUNG_TEXT",
    "BAI_BO_TEXT",
    "THAY_THE_TEXT",
    "THAY_THE_PHU_LUC",
]
ALL_OPERATIONS = [
    "SUA_DOI",
    "BAI_BO",
    "BO_SUNG",
    "BO_SUNG_TEXT",
    "BAI_BO_TEXT",
    "THAY_THE_TEXT",
    "THAY_THE_PHU_LUC",
]
DOCUMENTS = ["118_2025_QH15", "184_2025_ND-CP", "236_2026_ND-CP", "238_2026_ND-CP"]
current_dir = os.path.dirname(os.path.abspath(__file__))
PARSED_DIR = os.path.join(current_dir, "..", "..", "data", "parsed")


def get_amendment_path(document_dir):
    return os.path.join(PARSED_DIR, document_dir, "amendment_index.json")


def load_amendment_file(document_dir):
    file_path = get_amendment_path(document_dir)

    if not os.path.exists(file_path):
        print(f"Không tìm thấy: {file_path}")
        return None

    return load_json(file_path)


def collect_stats(data):

    stats = {
        "events": len(data),
        "items": 0,
        "actions": 0,
        "operations": Counter(),
        "resolution_status": Counter(),
    }

    for event in data:
        items = event.get("items", [])

        stats["items"] += len(items)

        for item in items:
            actions = item.get("actions", [])

            stats["actions"] += len(actions)

            for action in actions:
                operation = action.get("operation")

                status = action.get("resolution_status")

                stats["operations"][operation] += 1
                stats["resolution_status"][status] += 1

    return stats


def find_first_action(data, operation):

    for event in data:
        for item in event.get("items", []):
            for action in item.get("actions", []):
                if action.get("operation") == operation:
                    return {"event": event, "item": item, "action": action}

    return None


def print_action_sample(sample):

    if sample is None:
        print("  Sample: None")
        return

    event = sample["event"]
    item = sample["item"]
    action = sample["action"]

    print("  source_document:", event.get("source_document"))

    print("  target_document:", event.get("target_document"))

    print("  source_unit:", item.get("source_unit"))

    print("  operation:", action.get("operation"))

    print("  targets:", len(action.get("targets", [])))

    print("  created_units:", len(action.get("created_units", [])))

    print("  anchor:", action.get("anchor"))

    print("  text_amendment:", action.get("text_amendment"))

    print("  appendix_amendment:", action.get("appendix_amendment"))

    print("  resolution_status:", action.get("resolution_status"))

    print("  raw_instruction:", action.get("raw_instruction"))


def inspect_document(document_dir):

    print("\n" + "=" * 80)
    print(f"DOCUMENT: {document_dir}")

    data = load_amendment_file(document_dir)

    if data is None:
        print("STATUS: MISSING")
        return None

    print("Events:", len(data))

    stats = collect_stats(data)

    print("Items:", stats["items"])

    print("Actions:", stats["actions"])

    print("\nOPERATIONS:")

    for operation, count in sorted(stats["operations"].items()):
        print(f"  {operation}: {count}")

    print("\nRESOLUTION:")

    for status, count in sorted(stats["resolution_status"].items()):
        print(f"  {status}: {count}")

    print("\nSAMPLES:")

    for operation in OPERATIONS_TO_INSPECT:
        count = stats["operations"].get(operation, 0)

        if count == 0:
            continue

        print(f"\n[{operation}] count={count}")

        sample = find_first_action(data, operation)

        print_action_sample(sample)

    return stats


def main():

    all_stats = {}

    for document_dir in DOCUMENTS:
        stats = inspect_document(document_dir)

        if stats is not None:
            all_stats[document_dir] = stats

    print("\n" + "=" * 80)
    print("CORPUS SUMMARY")

    for document_dir, stats in all_stats.items():
        print(
            f"{document_dir}: "
            f"events={stats['events']}, "
            f"items={stats['items']}, "
            f"actions={stats['actions']}"
        )
    print("\n" + "=" * 100)
    print("OPERATION MATRIX")

    header = f"{'Document':25}" + "".join(f"{op:18}" for op in ALL_OPERATIONS)

    print(header)
    print("-" * len(header))

    for document_dir, stats in all_stats.items():
        row = f"{document_dir:25}"

        for op in ALL_OPERATIONS:
            row += f"{stats['operations'].get(op, 0):18}"

        print(row)


if __name__ == "__main__":
    main()
