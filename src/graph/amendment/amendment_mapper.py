import json

from src.graph.identity import make_article_id, make_clause_id, make_point_id
from src.graph.models import GraphNode, GraphRelationship


# CORE FUNCTIONS
def get_source_unit(item):
    return item["source_unit"]


def map_semantic_unit(item, index):
    semantic_unit_id = f"{get_source_unit(item)}_SU{index}"
    source_point = item["source_point"]
    node = GraphNode(
        label="SemanticUnit",
        id=semantic_unit_id,
        properties={
            "source_point": source_point.get("id"),
            "number": source_point.get("number"),
            "implicit": source_point.get("implicit", False),
            "instruction": source_point.get("instruction", ""),
        },
    )
    semantic_relationship = GraphRelationship(
        start_id=semantic_unit_id,
        relationship_type="LOCATED_AT",
        end_id=get_source_unit(item),
    )
    return node, semantic_relationship


def map_amendment_action(semantic_unit: str, action: dict, index_action: int):
    action_id = f"{semantic_unit}_A{index_action}"

    node = GraphNode(
        label="AmendmentAction",
        id=action_id,
        properties={
            "operation": action.get("operation"),
            "raw_instruction": action.get("raw_instruction", ""),
            "normalized_instruction": action.get("normalized_instruction", ""),
            "resolution_status": action.get("resolution_status"),
        },
    )
    return node


def map_amendment_item(item: dict, semantic_index: int, resolver):
    nodes = []
    relationships = []

    # 1. Một item → một SemanticUnit
    semantic_node, semantic_rel = map_semantic_unit(item, semantic_index)

    nodes.append(semantic_node)
    relationships.append(semantic_rel)

    # 2. Một item → nhiều Action
    for action_index, action in enumerate(item.get("actions", []), start=1):
        operation = action.get("operation")

        if operation == "SUA_DOI":
            action_nodes, action_relationships = map_sua_doi(
                item, action, semantic_node, action_index, resolver
            )

        elif operation == "BAI_BO":
            action_nodes, action_relationships = map_bai_bo(
                item, action, semantic_node, action_index, resolver
            )

        elif operation == "BO_SUNG":
            action_nodes, action_relationships = map_bo_sung(
                item, action, semantic_node, action_index, resolver
            )
        elif operation in ("THAY_THE_TEXT", "BAI_BO_TEXT", "BO_SUNG_TEXT"):
            action_nodes, action_relationships = map_text_amendment_operation(
                item, action, semantic_node, action_index, resolver
            )
        elif operation == "THAY_THE_PHU_LUC":
            action_nodes, action_relationships = map_thay_the_phu_luc(
                item, action, semantic_node, action_index
            )
        else:
            raise ValueError(f"Unsupported operation: {operation}")

        nodes.extend(action_nodes)
        relationships.extend(action_relationships)

    return nodes, relationships


def map_amendment_document(amendment_data, resolver):

    nodes = []
    relationships = []

    semantic_index = 1

    for event in amendment_data:
        for item in event.get("items", []):
            item_nodes, item_relationships = map_amendment_item(
                item, semantic_index, resolver
            )

            nodes.extend(item_nodes)
            relationships.extend(item_relationships)

            semantic_index += 1

    return nodes, relationships


# UTILITIES
def map_target_relationship(
    action_node_id: str, action: dict, relationship_type: str, resolver
):
    relationships = []

    for target in action.get("targets", []):
        target_unit = resolver.resolve_unit(target.get("target_unit"))
        if target_unit:
            rel = GraphRelationship(
                start_id=action_node_id,
                relationship_type=relationship_type,
                end_id=target_unit,
            )
            relationships.append(rel)
    return relationships


def get_by_path(data, path):
    current = data
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            current = current[key]
        else:
            return None
    return current


# ========================================SỬA ĐỔI============================================================================================
def map_amendment_replacement(
    action_id: str, replacement_index: int, replacement_info: dict
):

    replacement_id = f"{action_id}_R{replacement_index}"

    payload_json = json.dumps(replacement_info["replacement"], ensure_ascii=False)

    node = GraphNode(
        label="AmendmentReplacement",
        id=replacement_id,
        properties={
            "target_unit": replacement_info["target_unit"],
            "replacement_level": replacement_info["replacement_level"],
            "replacement_path": replacement_info["replacement_path"],
            "payload_json": payload_json,
        },
    )

    return node


def get_sua_doi_replacement(item: dict, action: dict, resolver):

    replacement_tree = item.get("replacement_tree")
    if not replacement_tree:
        return None
    targets = action.get("targets", [])
    if not targets:
        raise ValueError("SUA_DOI không có target")

    replacements = []
    for target in targets:
        path = target.get("replacement_path")
        if not path:
            raise ValueError("SUA_DOI không có replacement_path")
        replacement = get_by_path(replacement_tree, path)
        if not replacement:
            raise ValueError("SUA_DOI không có replacement")
        replacements.append(
            {
                "target_unit": resolver.resolve_unit(target.get("target_unit")),
                "replacement": replacement,
                "replacement_level": target.get("replacement_level"),
                "replacement_path": path,
            }
        )

    return replacements


def map_sua_doi(item, action, semantic_node, action_index, resolver):

    nodes = []
    relationships = []

    action_node = map_amendment_action(semantic_node.id, action, action_index)
    nodes.append(action_node)

    action_rel = GraphRelationship(
        start_id=semantic_node.id, relationship_type="HAS_ACTION", end_id=action_node.id
    )
    relationships.append(action_rel)

    replacements = get_sua_doi_replacement(item, action, resolver)

    for index, replacement_info in enumerate(replacements, start=1):
        replacement_node = map_amendment_replacement(
            action_node.id, index, replacement_info
        )
        nodes.append(replacement_node)

        replacement_rel = GraphRelationship(
            start_id=action_node.id,
            relationship_type="HAS_REPLACEMENT",
            end_id=replacement_node.id,
        )
        relationships.append(replacement_rel)

        target_relationship = GraphRelationship(
            start_id=action_node.id,
            relationship_type="AMENDS",
            end_id=replacement_info.get("target_unit"),
        )
        relationships.append(target_relationship)
    return nodes, relationships


# ========================================BÃI BỎ============================================================================================
def map_bai_bo(item, action, semantic_node, action_index, resolver):

    nodes = []
    relationships = []
    action_node = map_amendment_action(semantic_node.id, action, action_index)
    nodes.append(action_node)

    action_rel = GraphRelationship(
        start_id=semantic_node.id, relationship_type="HAS_ACTION", end_id=action_node.id
    )
    relationships.append(action_rel)

    target_relationship = map_target_relationship(
        action_node.id, action, "REPEALS", resolver
    )
    relationships.extend(target_relationship)
    return nodes, relationships


# ==BỔ SUNG============================================================================================
def map_created_unit(item: dict, created_unit: dict, resolver):

    created_unit_id = resolver.resolve_unit(created_unit.get("unit_id"))

    if not created_unit_id:
        return None, [], []

    replacement = map_replacement_unit(item, created_unit)

    if replacement is None:
        return None, [], []

    unit_level = created_unit.get("unit_level")

    if unit_level == "ARTICLE":
        article_number = str(replacement.get("number"))

        article_node = GraphNode(
            label="Article",
            id=created_unit_id,
            properties={
                "number": article_number,
                "title": replacement.get("title", ""),
            },
        )
        document_id = created_unit_id.rsplit("_D", 1)[0]

        child_nodes, child_rel = map_article_children(
            article_node, document_id, article_number, replacement
        )
        return (article_node, child_nodes, child_rel)

    if unit_level == "CLAUSE":
        clause_number = str(replacement.get("number"))
        clause_node = GraphNode(
            label="Clause",
            id=created_unit_id,
            properties={
                "number": clause_number,
                "content": replacement.get("content", ""),
            },
        )
        document_id = created_unit_id.rsplit("_D", 1)[0]
        article_part = created_unit_id.rsplit("_D", 1)[1]
        article_number = article_part.split("_K", 1)[0]
        child_nodes, child_rels = map_clause_children(
            clause_node, document_id, clause_number, article_number, replacement
        )
        return (clause_node, child_nodes, child_rels)

    if unit_level == "POINT":
        point_node = GraphNode(
            label="Point",
            id=created_unit_id,
            properties={
                "number": str(replacement.get("number")),
                "content": replacement.get("content", ""),
            },
        )
        return (point_node, [], [])

    return None, [], []


def map_replacement_unit(item: dict, created_unit: dict):

    replacement_tree = item.get("replacement_tree")

    if not replacement_tree:
        return None

    unit_level = created_unit.get("unit_level")
    unit_number = str(created_unit.get("number"))

    root_level = item.get("replacement_root_level")

    if unit_level == "ARTICLE":
        if root_level == "ARTICLE":
            article = replacement_tree.get("article")

            if article is not None:
                if str(article.get("number")) == unit_number:
                    return article

        if root_level == "ARTICLE_LIST":
            for article in replacement_tree.get("articles", []):
                if article is None:
                    continue

                if str(article.get("number")) == unit_number:
                    return article

    if unit_level == "CLAUSE":
        if root_level == "CLAUSE":
            clause = replacement_tree.get("clause")

            if clause is not None:
                if str(clause.get("number")) == unit_number:
                    return clause

        if root_level == "CLAUSE_LIST":
            for clause in replacement_tree.get("clauses", []):
                if clause is None:
                    continue

                if str(clause.get("number")) == unit_number:
                    return clause

    if unit_level == "POINT":
        if root_level == "POINT":
            point = replacement_tree.get("point")

            if point is not None:
                if str(point.get("number")) == unit_number:
                    return point

        if root_level == "POINT_LIST":
            for point in replacement_tree.get("points", []):
                if point is None:
                    continue

                if str(point.get("number")) == unit_number:
                    return point

    return None


def map_anchor_relationship(action_node_id: str, action: dict, resolver):
    relationships = []

    anchor = action.get("anchor")

    if not anchor:
        return relationships
    relation = anchor.get("relation")
    target = anchor.get("target", {})

    document = resolver.resolve_document(target.get("document"))
    article = target.get("article")
    clause = target.get("clause")
    point = target.get("point")

    if not document:
        raise ValueError("Anchor thiếu document")

    if not article:
        raise ValueError("Anchor thiếu article")

    if not relation:
        raise ValueError("Anchor thiếu relation")

    if point is not None:
        if clause is None:
            raise ValueError("Anchor POINT nhưng thiếu clause")
        target_id = make_point_id(document, article, clause, point)
    elif clause is not None:
        target_id = make_clause_id(document, article, clause)
    else:
        target_id = make_article_id(document, article)

    rel = GraphRelationship(
        start_id=action_node_id, relationship_type=relation, end_id=target_id
    )
    relationships.append(rel)

    return relationships


def map_bo_sung(
    item: dict, action: dict, semantic_node: dict, action_index: int, resolver
):

    nodes = []
    relationships = []
    action_node = map_amendment_action(semantic_node.id, action, action_index)
    nodes.append(action_node)

    action_rel = GraphRelationship(
        start_id=semantic_node.id, relationship_type="HAS_ACTION", end_id=action_node.id
    )
    relationships.append(action_rel)

    for created_unit in action.get("created_units", []):
        (created_root_node, child_nodes, child_relationships) = map_created_unit(
            item, created_unit, resolver
        )

        if created_root_node is None:
            raise ValueError(
                f"Không tạo được created unit: {created_unit.get('unit_id')}"
            )
        nodes.append(created_root_node)

        nodes.extend(child_nodes)

        relationships.extend(child_relationships)

        relationships.append(
            GraphRelationship(
                start_id=action_node.id,
                relationship_type="ADDS",
                end_id=created_root_node.id,
            )
        )

    anchor_relationships = map_anchor_relationship(action_node.id, action, resolver)

    relationships.extend(anchor_relationships)

    return nodes, relationships


def map_article_children(
    article_node, document_id, article_number, replacement_article
):
    nodes = []
    relationships = []

    for clause_data in replacement_article.get("clauses", []):
        clause_number = clause_data.get("number")
        clause_id = make_clause_id(document_id, article_number, clause_number)

        clause_node = GraphNode(
            label="Clause",
            id=clause_id,
            properties={
                "number": clause_number,
                "content": clause_data.get("content", ""),
            },
        )
        nodes.append(clause_node)

        relationship = GraphRelationship(
            start_id=article_node.id,
            relationship_type="CONTAINS_CLAUSE",
            end_id=clause_id,
        )
        relationships.append(relationship)

        point_nodes, point_relationships = map_clause_children(
            clause_node, document_id, clause_number, article_number, clause_data
        )
        nodes.extend(point_nodes)
        relationships.extend(point_relationships)

    return nodes, relationships


def map_clause_children(
    clause_node, document, clause_number, article_number, clause_data
):
    nodes = []
    relationships = []

    for point_data in clause_data.get("points", []):
        point_number = point_data.get("number")
        point_id = make_point_id(document, article_number, clause_number, point_number)

        point_node = GraphNode(
            label="Point",
            id=point_id,
            properties={
                "number": point_number,
                "content": point_data.get("content", ""),
            },
        )
        nodes.append(point_node)

        relationship = GraphRelationship(
            start_id=clause_node.id, relationship_type="CONTAINS_POINT", end_id=point_id
        )
        relationships.append(relationship)

    return nodes, relationships


# ========================================TEXT AMENDMENT============================================================================================
def map_amendment_text(action_id: str, amendment_text: dict):
    text_id = f"{action_id}_TEXT"

    properties = {"unit_type": amendment_text.get("unit_type")}

    if amendment_text.get("text") is not None:
        properties["text"] = amendment_text.get("text")
    if amendment_text.get("relation") is not None:
        properties["relation"] = amendment_text.get("relation")
    if amendment_text.get("anchor_text") is not None:
        properties["anchor_text"] = amendment_text.get("anchor_text")
    if amendment_text.get("old_text") is not None:
        properties["old_text"] = amendment_text.get("old_text")
    if amendment_text.get("new_text") is not None:
        properties["new_text"] = amendment_text.get("new_text")

    return GraphNode(label="AmendmentText", id=text_id, properties=properties)


def map_text_target_relationships(action_node_id: str, action: dict, resolver):
    relationships = []

    for target in action.get("targets", []):
        target_unit = resolver.resolve_unit(target.get("target_unit"))
        if not target_unit:
            continue
        relationship = GraphRelationship(
            start_id=action_node_id, relationship_type="APPLIES_TO", end_id=target_unit
        )
        relationships.append(relationship)
    return relationships


def map_text_amendment_operation(
    item: dict, action: dict, semantic_node: dict, action_index: int, resolver
):

    nodes = []
    relationships = []

    action_node = map_amendment_action(semantic_node.id, action, action_index)
    nodes.append(action_node)
    relationship = GraphRelationship(
        start_id=semantic_node.id, relationship_type="HAS_ACTION", end_id=action_node.id
    )
    relationships.append(relationship)

    text_amendment = action.get("text_amendment")

    if not text_amendment:
        raise ValueError(f"{action.get('operation')} không có text_amendment")

    text_node = map_amendment_text(action_node.id, text_amendment)

    nodes.append(text_node)

    relationships.append(
        GraphRelationship(
            start_id=action_node.id,
            relationship_type="HAS_TEXT_AMENDMENT",
            end_id=text_node.id,
        )
    )

    relationships.extend(
        map_text_target_relationships(action_node.id, action, resolver)
    )

    return nodes, relationships


# =================================================APPENDIX============================================================================================
def map_amendment_appendix(action_id: str, appendix_amendment: dict):

    appendix_id = f"{action_id}_APPENDIX"

    old_appendix = appendix_amendment.get("old_appendix", {})

    new_appendix = appendix_amendment.get("new_appendix", {})

    node = GraphNode(
        label="AmendmentAppendix",
        id=appendix_id,
        properties={
            "old_number": old_appendix.get("number"),
            "old_document": old_appendix.get("document"),
            "new_number": new_appendix.get("number"),
            "new_document": new_appendix.get("document"),
        },
    )

    return node


def map_thay_the_phu_luc(
    item: dict, action: dict, semantic_node: dict, action_index: int
):
    nodes = []
    relationships = []
    action_node = map_amendment_action(semantic_node.id, action, action_index)
    nodes.append(action_node)

    relationship = GraphRelationship(
        start_id=semantic_node.id, relationship_type="HAS_ACTION", end_id=action_node.id
    )
    relationships.append(relationship)
    appendix_amendment = action.get("appendix_amendment")

    if not appendix_amendment:
        raise ValueError("THAY_THE_PHU_LUC không có appendix_amendment")

    appendix_node = map_amendment_appendix(action_node.id, appendix_amendment)

    nodes.append(appendix_node)

    relationships.append(
        GraphRelationship(
            start_id=action_node.id,
            relationship_type="HAS_APPENDIX_AMENDMENT",
            end_id=appendix_node.id,
        )
    )

    return nodes, relationships
