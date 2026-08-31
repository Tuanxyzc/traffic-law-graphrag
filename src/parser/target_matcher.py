"""
target_matcher.py — Map Targets to Replacement Tree paths.
"""


def _target_level_cua(vt) -> str:
    if vt.diem:
        return "POINT"
    if vt.khoan:
        return "CLAUSE"
    return "ARTICLE"


def get_nodes_at_level(replacement_tree, root_level, target_level):
    nodes = []
    if target_level == "ARTICLE":
        if root_level == "ARTICLE" and "article" in replacement_tree:
            nodes.append((replacement_tree["article"], ["article"]))
        elif root_level == "ARTICLE_LIST" and "articles" in replacement_tree:
            for i, article in enumerate(replacement_tree["articles"]):
                nodes.append((article, ["articles", i]))
    elif target_level == "CLAUSE":
        if root_level == "ARTICLE" and "article" in replacement_tree:
            for i, c in enumerate(replacement_tree["article"].get("clauses", [])):
                nodes.append((c, ["article", "clauses", i]))
        elif root_level == "CLAUSE_LIST" and "clauses" in replacement_tree:
            for i, c in enumerate(replacement_tree["clauses"]):
                nodes.append((c, ["clauses", i]))
        elif root_level == "CLAUSE" and "clause" in replacement_tree:
            nodes.append((replacement_tree["clause"], ["clause"]))
    elif target_level == "POINT":
        if root_level == "ARTICLE" and "article" in replacement_tree:
            for i, c in enumerate(replacement_tree["article"].get("clauses", [])):
                for j, p in enumerate(c.get("points", [])):
                    nodes.append((p, ["article", "clauses", i, "points", j]))
        elif root_level == "CLAUSE_LIST" and "clauses" in replacement_tree:
            for i, c in enumerate(replacement_tree["clauses"]):
                for j, p in enumerate(c.get("points", [])):
                    nodes.append((p, ["clauses", i, "points", j]))
        elif root_level == "CLAUSE" and "clause" in replacement_tree:
            for j, p in enumerate(replacement_tree["clause"].get("points", [])):
                nodes.append((p, ["clause", "points", j]))
        elif root_level == "POINT_LIST" and "points" in replacement_tree:
            for i, p in enumerate(replacement_tree["points"]):
                nodes.append((p, ["points", i]))
        elif root_level == "POINT" and "point" in replacement_tree:
            nodes.append((replacement_tree["point"], ["point"]))
    return nodes


def match_targets(targets, replacement_tree, root_level) -> list[dict]:
    mapped = []
    for idx, target in enumerate(targets):
        t_level = _target_level_cua(target)
        t_num = (
            target.dieu
            if t_level == "ARTICLE"
            else (target.khoan if t_level == "CLAUSE" else target.diem)
        )

        nodes = get_nodes_at_level(replacement_tree, root_level, t_level)
        matched_path = None

        # Priority 1: Match by Level + Number/Letter
        if t_num:
            for node, path in nodes:
                if str(node.get("number", "")) == str(t_num):
                    matched_path = path
                    break

        # Numbered nodes must never be assigned to a differently numbered
        # target. Order is meaningful only for unnumbered replacement text.
        if (
            not matched_path
            and len(nodes) == len(targets)
            and all(not str(node.get("number") or "").strip() for node, _ in nodes)
        ):
            matched_path = nodes[idx][1] if idx < len(nodes) else None

        target_context = {
            "document": target.so_hieu_van_ban,
            "article": {"id": None, "number": target.dieu} if target.dieu else None,
            "clause": {"id": None, "number": target.khoan} if target.khoan else None,
            "point": {"id": None, "number": target.diem} if target.diem else None,
        }

        mapped.append(
            {
                "target_unit_mock": target,
                "target_context": target_context,
                "target_level": t_level,
                "replacement_level": t_level if matched_path else None,
                "replacement_path": matched_path,
            }
        )

    return mapped
