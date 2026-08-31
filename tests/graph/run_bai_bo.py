import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import os

from src.graph.amendment.amendment_mapper import map_bai_bo
from src.graph.loader import load_json
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

current_dir = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(current_dir, "samples", "test_baibo.json")


data = load_json(FILE_PATH)
actions = data["item"]["actions"]
resolver = CanonicalIDResolver()
nodes, relationships = map_bai_bo(data["item"], actions[0], None, 1, resolver)

print(f"Nodes: {len(nodes)}")
print(f"Relationships: {len(relationships)}")

for node in nodes:
    print(node)

for relationship in relationships:
    print(relationship)
