import collections


def validation_duplicate_node_ids(nodes):
    ids = [node.id for node in nodes]

    duplicates = [
        node_id
        for node_id, count in collections.Counter(ids).items()
        if count > 1
    ]

    if duplicates:
        raise ValueError(
            f"Duplicate node id: {duplicates}"
        )
    else: 
        print("Node duplicates validation passed")
    return True

def validation_duplicate_relationship_tuples(relationships):
    tuples = [(rel.start_id, rel.relationship_type, rel.end_id) for rel in relationships]

    duplicates = [
        t
        for t, count in collections.Counter(tuples).items()
        if count > 1
    ]

    if duplicates:
        raise ValueError(
            f"Duplicate relationship tuples: {duplicates}"
        )
    else: 
        print("Relationship duplicates validation passed")
    return True

def validation_relationship_references(nodes, relationships):
    node_ids = {node.id for node in nodes}

    error = []

    for r in relationships:
        if r.start_id not in node_ids:
            error.append(
                f"Không tìm thấy node id {r.start_id} trong graph"
            )
        if r.end_id not in node_ids:
            error.append(
                f"Không tìm thấy node id {r.end_id} trong graph"
            )
    if error:
        raise ValueError(
            "\n".join(error)
        )
    else: 
        print("Relationship references validation passed")
    return True
    

def validate_graph_integrity(nodes, relationships):
    validation_duplicate_node_ids(nodes)
    validation_duplicate_relationship_tuples(relationships)
    validation_relationship_references(nodes, relationships)
    return True