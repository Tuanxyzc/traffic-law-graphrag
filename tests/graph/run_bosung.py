import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.graph.amendment.amendment_mapper import map_amendment_document
from src.graph.loader import load_json
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

import os

current_dir = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(current_dir, "samples", "test_bosung.json")

data = load_json(FILE_PATH)
resolver = CanonicalIDResolver()
node,rel = map_amendment_document(data, resolver)
print(f"Nodes: {len(node)}")
print(node) 
print("======================================\n")
print(f"Relationships: {len(rel)}")
print(rel)
