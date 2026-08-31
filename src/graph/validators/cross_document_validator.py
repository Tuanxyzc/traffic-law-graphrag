def build_structure_node_index(structure_results):
    index = {}

    for document_id, result in structure_results.items():
        index[document_id] = {node.id for node in result["nodes"]}

    return index


def get_document_id_from_node_id(node_id: str):
    return node_id.split("_D", 1)[0]


def validate_target_exists(target_unit: str, structure_node_index: dict):

    document_id = get_document_id_from_node_id(target_unit)

    if document_id not in structure_node_index:
        raise ValueError(f"Không tìm thấy target unit: {document_id}")
    if target_unit not in structure_node_index[document_id]:
        raise ValueError(f"Không tìm thấy target unit: {target_unit}")
    return True


def validate_amends_targets(relationships, structure_node_index):

    for rel in relationships:
        if rel.relationship_type != "AMENDS":
            continue

        validate_target_exists(rel.end_id, structure_node_index)
    return True


def validate_repeals_targets(relationships, structure_node_index):

    for rel in relationships:
        if rel.relationship_type != "REPEALS":
            continue

        validate_target_exists(rel.end_id, structure_node_index)
    return True


def validate_applies_to_targets(relationships, structure_node_index):

    for rel in relationships:
        if rel.relationship_type != "APPLIES_TO":
            continue
        validate_target_exists(rel.end_id, structure_node_index)
    return True


def validate_adds_targets(relationships, amendment_nodes):
    adds_node_id = build_created_unit_index(amendment_nodes)

    adds_target_ids = get_adds_target_ids(relationships)

    missing = adds_target_ids - adds_node_id
    if missing:
        raise ValueError(f"Không tìm thấy target unit trong Amendment Graph: {missing}")
    return True


def build_created_unit_index(amendment_nodes):
    return {
        node.id
        for node in amendment_nodes
        if node.label in ("ARTICLE", "POINT", "CLAUSE")
    }


def get_adds_target_ids(relationships):
    return {rel.end_id for rel in relationships if rel.relationship_type == "ADDS"}


def validate_cross_document(structure_results, amendment_results):

    structure_node_index = build_structure_node_index(structure_results)

    for document_id, result in amendment_results.items():
        relationships = result["relationships"]
        nodes = result["nodes"]

        validate_amends_targets(relationships, structure_node_index)

        validate_repeals_targets(relationships, structure_node_index)

        validate_applies_to_targets(relationships, structure_node_index)

    print("Cross-document validation passed")
    return True


def merge_graph_results(structure_results, amendment_results):

    all_nodes = []
    all_relationships = []

    for result in structure_results.values():
        all_nodes.extend(result["nodes"])
        all_relationships.extend(result["relationships"])

    for result in amendment_results.values():
        all_nodes.extend(result["nodes"])
        all_relationships.extend(result["relationships"])

    return all_nodes, all_relationships


# GLOBAL DUPLICATE VALIDATIONS
def validate_global_node_duplicates(nodes):

    seen = set()

    for node in nodes:
        if node.id in seen:
            raise ValueError(f"Global duplicate node ID: {node.id}")

        seen.add(node.id)

    return True


def validate_global_relationship_duplicates(relationships):

    seen = set()

    for rel in relationships:
        key = (
            rel.start_id,
            rel.relationship_type,
            rel.end_id,
        )

        if key in seen:
            raise ValueError(f"Global duplicate relationship: {key}")

        seen.add(key)

    return True


def validate_global_relationship_references(nodes, relationships):

    node_ids = {node.id for node in nodes}

    for rel in relationships:
        if rel.start_id not in node_ids:
            raise ValueError(f"Global relationship start not found: {rel.start_id}")

        if rel.end_id not in node_ids:
            raise ValueError(f"Global relationship end not found: {rel.end_id}")

    return True


def validate_global_graph(nodes, relationships):

    validate_global_node_duplicates(nodes)

    validate_global_relationship_duplicates(relationships)

    validate_global_relationship_references(nodes, relationships)

    print("Global graph validation passed")
    return True
