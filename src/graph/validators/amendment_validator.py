from src.graph.amendment.amendment_mapper import get_sua_doi_replacement


def validate_sua_doi_replacement_levels(action):
    if action.get("operation") != "SUA_DOI":
        return True
    for target in action.get("targets", []):
        target_level = target.get("target_level")
        replacement_level = target.get("replacement_level")
        if target_level != replacement_level:
            raise ValueError(
                "SUA_DOI target_level != "
                "replacement_level: "
                f"{target.get('target_unit')}"
            )
    return True


def validate_sua_doi_replacement_node_levels(action, replacements, replacement_nodes):

    expected = {r["target_unit"]: r["replacement_level"] for r in replacements}

    if len(replacement_nodes) != len(replacements):
        raise ValueError(
            "Replacement node count mismatch: "
            f"expected={len(replacements)}, actual={len(replacement_nodes)}"
        )

    for node in replacement_nodes:
        target_unit = node.properties.get("target_unit")

        actual_level = node.properties.get("replacement_level")

        expected_level = expected.get(target_unit)

        if actual_level != expected_level:
            raise ValueError(
                f"Replacement level mismatch: "
                f"{target_unit}: "
                f"expected={expected_level}, "
                f"actual={actual_level}"
            )

    return True


def validate_sua_doi_replacements(item, action, resolver):

    if action.get("operation") != "SUA_DOI":
        return True

    targets = action.get("targets", [])

    replacements = get_sua_doi_replacement(item, action, resolver)
    if replacements is None:
        raise ValueError("SUA_DOI có replacement_tree rỗng")

    if len(targets) != len(replacements):
        raise ValueError(
            "SUA_DOI targets/replacements mismatch: "
            f"{len(targets)} != "
            f"{len(replacements)}"
        )

    return True


def validate_sua_doi_replacement_paths(action, replacements):

    targets = action.get("targets", [])

    if len(targets) != len(replacements):
        raise ValueError("Target/replacement count mismatch")

    for target, replacement in zip(targets, replacements):
        target_unit = target.get("target_unit")

        replacement_target = replacement.get("target_unit")

        if target_unit != replacement_target:
            raise ValueError(
                f"Target/replacement mismatch: {target_unit} != {replacement_target}"
            )

        replacement_path = replacement.get("replacement_path")

        if not replacement_path:
            raise ValueError(f"SUA_DOI target {target_unit} missing replacement_path")

        replacement_node = replacement.get("replacement") or {}
        actual_number = replacement_node.get("number")
        level_key = {
            "ARTICLE": "article",
            "CLAUSE": "clause",
            "POINT": "point",
        }.get(target.get("target_level"))
        context_node = (
            (target.get("target_context") or {}).get(level_key) if level_key else None
        )
        expected_number = context_node.get("number") if context_node else None
        if (
            actual_number is not None
            and expected_number is not None
            and str(actual_number) != str(expected_number)
        ):
            raise ValueError(
                f"SUA_DOI replacement identity mismatch for {target_unit}: "
                f"expected number={expected_number}, actual number={actual_number}, "
                f"path={replacement_path}"
            )

    return True


def validate_sua_doi_graph(action_node, relationships, replacement_nodes):

    if action_node.properties.get("operation") != "SUA_DOI":
        return True

    action_id = action_node.id

    amend_targets = [
        r.end_id
        for r in relationships
        if (r.start_id == action_id and r.relationship_type == "AMENDS")
    ]

    replacement_target_units = [
        node.properties.get("target_unit") for node in replacement_nodes
    ]

    if len(amend_targets) != len(replacement_target_units):
        raise ValueError(
            "SUA_DOI AMENDS/replacement count mismatch: "
            f"{len(amend_targets)} != "
            f"{len(replacement_target_units)}"
        )

    if set(amend_targets) != set(replacement_target_units):
        raise ValueError(
            "SUA_DOI target/replacement mismatch: "
            f"AMENDS={amend_targets}, "
            f"REPLACEMENTS={replacement_target_units}"
        )

    return True


def validate_amendment_graph(item, action, nodes, relationships, resolver):

    if action.get("operation") != "SUA_DOI":
        return True

    actions = item.get("actions", [])
    try:
        action_index = next(
            i
            for i, candidate in enumerate(actions, start=1)
            if candidate is action or candidate == action
        )
    except StopIteration:
        raise ValueError("Action không tồn tại trong item")

    source_unit = item.get("source_unit")

    # Lấy SemanticUnit từ list nodes để sinh ra ID (vì ID nay đã có dạng _SU)
    semantic_nodes = [n for n in nodes if n.label == "SemanticUnit"]
    if not semantic_nodes:
        raise ValueError("Không tìm thấy SemanticUnit node để validate")
    semantic_node_id = semantic_nodes[0].id

    expected_action_id = f"{semantic_node_id}_A{action_index}"
    action_nodes = [
        node
        for node in nodes
        if node.label == "AmendmentAction" and node.id == expected_action_id
    ]

    if len(action_nodes) != 1:
        raise ValueError(
            f"Expected exactly 1 AmendmentAction node, found {len(action_nodes)}"
        )

    action_node = action_nodes[0]

    replacement_nodes = [
        node
        for node in nodes
        if node.label == "AmendmentReplacement"
        and node.id.startswith(expected_action_id + "_R")
    ]

    replacements = get_sua_doi_replacement(item, action, resolver)

    validate_sua_doi_replacement_levels(action)

    validate_sua_doi_replacements(item, action, resolver)

    validate_sua_doi_replacement_node_levels(action, replacements, replacement_nodes)
    validate_sua_doi_replacement_paths(action, replacements)

    validate_sua_doi_graph(action_node, relationships, replacement_nodes)

    return True
