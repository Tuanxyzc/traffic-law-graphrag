import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import os

from src.graph.loader import load_json
from src.graph.mapper import (
    map_document_structure,
)
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver
from src.graph.validators.structure_validator import (
    validate_node_ids,
    validate_relationship,
)

current_dir = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(
    current_dir, "..", "..", "data", "parsed", "35_2024_QH15_structure.json"
)


data = load_json(FILE_PATH)

resolver = CanonicalIDResolver()
nodes, relationships = map_document_structure(data, resolver)

validate_node_ids(data, nodes)
validate_relationship(data, relationships)
