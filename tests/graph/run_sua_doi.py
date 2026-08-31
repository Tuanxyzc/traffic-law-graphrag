import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.graph.amendment.amendment_mapper import map_sua_doi
from src.graph.loader import load_json
from src.graph.validators.amendment_validator import validate_amendment_graph
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(current_dir,"samples","test_suadoi.json")

data = load_json(FILE_PATH)
resolver = CanonicalIDResolver()
nodes, relationships = map_sua_doi(data["item"],data["item"]["actions"][0], None, 1, resolver)

print(f"Nodes: {len(nodes)}")
print(f"Relationships: {len(relationships)}")

res = validate_amendment_graph(data["item"],data["item"]["actions"][0],nodes, relationships)
print(res)