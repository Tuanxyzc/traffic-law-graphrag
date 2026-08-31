from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphNode:
    label: str
    id: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphRelationship:
    start_id: str
    relationship_type: str
    end_id: str
    properties: dict[str, Any] = field(default_factory=dict)
