from src.graph.identity import (
    make_article_id,
    make_chapter_id,
    make_clause_id,
    make_point_id,
)
from src.graph.validators.graph_validator import validate_graph_integrity


def collect_expected_node_ids(document_data, resolver):

    expected_ids = set()

    document_id = resolver.resolve_document(document_data["so_hieu"])
    expected_ids.add(document_id)

    for chapter_data in document_data.get("chuong", []):
        chapter_number = chapter_data["so"]
        chapter_id = make_chapter_id(document_id, chapter_number)
        expected_ids.add(chapter_id)

        for article_data in chapter_data.get("dieu", []):
            article_number = article_data["so"]
            article_ids = make_article_id(document_id, article_number)
            expected_ids.add(article_ids)

            for clause_data in article_data.get("khoan", []):
                clause_number = clause_data["so"]
                clause_ids = make_clause_id(document_id, article_number, clause_number)
                expected_ids.add(clause_ids)

                for point_data in clause_data.get("diem", []):
                    point_number = point_data["so"]
                    point_ids = make_point_id(
                        document_id, article_number, clause_number, point_number
                    )
                    expected_ids.add(point_ids)

    for article_data in document_data.get("dieu_khong_chuong", []):
        article_number = article_data["so"]
        article_ids = make_article_id(document_id, article_number)
        expected_ids.add(article_ids)

        for clause_data in article_data.get("khoan", []):
            clause_number = clause_data["so"]
            clause_ids = make_clause_id(document_id, article_number, clause_number)
            expected_ids.add(clause_ids)

            for point_data in clause_data.get("diem", []):
                point_number = point_data["so"]
                point_ids = make_point_id(
                    document_id, article_number, clause_number, point_number
                )
                expected_ids.add(point_ids)

    return expected_ids


def validate_node_ids(document_data, nodes, resolver):

    expected_ids = collect_expected_node_ids(document_data, resolver)

    actual_ids = {node.id for node in nodes}

    missing = expected_ids - actual_ids

    unexpected = actual_ids - expected_ids

    if missing:
        print("\n❌ MISSING NODES")

        for node_id in sorted(missing):
            print(node_id)

    if unexpected:
        print("\n❌ UNEXPECTED NODES")

        for node_id in sorted(unexpected):
            print(node_id)

    if missing or unexpected:
        raise ValueError("Structure ↔ Graph node ID validation failed")

    print("\n✅ Structure ↔ Graph node ID validation passed")

    return True


def collect_expected_relationship(document_data, resolver):
    expected_relas = set()

    document_id = resolver.resolve_document(document_data["so_hieu"])

    for chapter_data in document_data.get("chuong", []):
        chapter_number = chapter_data["so"]
        chapter_id = make_chapter_id(document_id, chapter_number)
        expected_relas.add((document_id, "CONTAINS_CHAPTER", chapter_id))

        for article_data in chapter_data.get("dieu", []):
            article_number = article_data["so"]
            article_ids = make_article_id(document_id, article_number)
            expected_relas.add((chapter_id, "CONTAINS_ARTICLE", article_ids))

            for clause_data in article_data.get("khoan", []):
                clause_number = clause_data["so"]
                clause_ids = make_clause_id(document_id, article_number, clause_number)
                expected_relas.add((article_ids, "CONTAINS_CLAUSE", clause_ids))

                for point_data in clause_data.get("diem", []):
                    point_number = point_data["so"]
                    point_ids = make_point_id(
                        document_id, article_number, clause_number, point_number
                    )
                    expected_relas.add((clause_ids, "CONTAINS_POINT", point_ids))

    for article_data in document_data.get("dieu_khong_chuong", []):
        article_number = article_data["so"]
        article_ids = make_article_id(document_id, article_number)
        expected_relas.add((document_id, "CONTAINS_ARTICLE", article_ids))

        for clause_data in article_data.get("khoan", []):
            clause_number = clause_data["so"]
            clause_ids = make_clause_id(document_id, article_number, clause_number)
            expected_relas.add((article_ids, "CONTAINS_CLAUSE", clause_ids))

            for point_data in clause_data.get("diem", []):
                point_number = point_data["so"]
                point_ids = make_point_id(
                    document_id, article_number, clause_number, point_number
                )
                expected_relas.add((clause_ids, "CONTAINS_POINT", point_ids))

    return expected_relas


def validate_relationship(document_data, relationships, resolver):

    expected_relas = collect_expected_relationship(document_data, resolver)

    actual_relas = {(r.start_id, r.relationship_type, r.end_id) for r in relationships}

    missing = expected_relas - actual_relas
    unexpected = actual_relas - expected_relas

    if missing:
        print("❌ MISSING RELATIONSHIPS")

        for start, rel, end in sorted(missing):
            print(f"{start} -[{rel}]-> {end}")

    if unexpected:
        print("❌ UNEXPECTED RELATIONSHIPS")

        for start, rel, end in sorted(unexpected):
            print(f"{start} -[{rel}]-> {end}")

    if missing or unexpected:
        raise ValueError("Structure ↔ Graph relationship ID validation failed")

    print("\n✅ Structure ↔ Graph relationship ID validation passed")
    return True


def validation_document_properties(document_data, nodes, resolver):
    node_by_id = {node.id: node for node in nodes}
    document_id = resolver.resolve_document(document_data["so_hieu"])
    if document_id not in node_by_id:
        raise ValueError(
            f"Không tìm thấy document_id: {document_id} trong danh sách node"
        )
    graph_node = node_by_id[document_id]
    expected_so_hieu = document_data["so_hieu"]
    actual_so_hieu = graph_node.properties.get("so_hieu")
    expected_ten = document_data.get("ten")
    actual_ten = graph_node.properties.get("ten")
    expected_loai = document_data.get("loai")
    actual_loai = graph_node.properties.get("loai")
    expected_ngay_ban_hanh = document_data.get("ngay_ban_hanh")
    actual_ngay_ban_hanh = graph_node.properties.get("ngay_ban_hanh")
    expected_co_quan_ban_hanh = document_data.get("co_quan_ban_hanh")
    actual_co_quan_ban_hanh = graph_node.properties.get("co_quan_ban_hanh")
    expected_trang_thai_hieu_luc = document_data.get("trang_thai_hieu_luc")
    actual_trang_thai_hieu_luc = graph_node.properties.get("trang_thai_hieu_luc")
    expected_hieu_luc_tu = document_data.get("hieu_luc_tu")
    actual_hieu_luc_tu = graph_node.properties.get("hieu_luc_tu")
    expected_cap = document_data.get("cap")
    actual_cap = graph_node.properties.get("cap")
    if expected_so_hieu != actual_so_hieu:
        raise ValueError(
            f"Document {document_id}"
            f"so_hieu mismatch"
            f"Expected ={expected_so_hieu}"
            f"Actual = {actual_so_hieu}"
        )
    if expected_ten != actual_ten:
        raise ValueError(f"Document {document_id}ten mismatch")
    if expected_loai != actual_loai:
        raise ValueError(f"Document {document_id}loai mismatch")
    if expected_ngay_ban_hanh != actual_ngay_ban_hanh:
        raise ValueError(f"Document {document_id}ngay_ban_hanh mismatch")
    if expected_co_quan_ban_hanh != actual_co_quan_ban_hanh:
        raise ValueError(f"Document {document_id}co_quan_ban_hanh mismatch")
    if expected_trang_thai_hieu_luc != actual_trang_thai_hieu_luc:
        raise ValueError(f"Document {document_id}trang_thai_hieu_luc mismatch")
    if expected_hieu_luc_tu != actual_hieu_luc_tu:
        raise ValueError(f"Document {document_id}hieu_luc_tu mismatch")
    if expected_cap != actual_cap:
        raise ValueError(f"Document {document_id}cap mismatch")
    print("Document property validation passed")
    return True


def validation_chapter_properties(document_data, nodes, resolver):
    node_by_id = {node.id: node for node in nodes}
    document_id = resolver.resolve_document(document_data["so_hieu"])
    for chapter_data in document_data.get("chuong", []):
        chapter_number = str(chapter_data["so"])
        chapter_id = make_chapter_id(document_id, chapter_number)
        if chapter_id not in node_by_id:
            raise ValueError(
                f"Không tìm thấy chapter_id: {chapter_id} trong danh sách node"
            )
        graph_node = node_by_id[chapter_id]
        expected_number = chapter_number
        actual_number = graph_node.properties.get("number")
        expected_title = chapter_data.get("tieu_de")
        actual_title = graph_node.properties.get("title")
        if expected_number != actual_number:
            raise ValueError(
                f"Chapter {chapter_id}, "
                f"number mismatch, "
                f"Expected ={expected_number}, "
                f"Actual = {actual_number}"
            )
        if expected_title != actual_title:
            raise ValueError(f"Chapter {chapter_id}title mismatch")
    print("Chapter property validation passed")
    return True


def validation_article_properties(document_data, nodes, resolver):
    node_by_id = {node.id: node for node in nodes}

    document_id = resolver.resolve_document(document_data["so_hieu"])
    articles = get_all_articles(document_data)

    for article_data in articles:
        article_number = str(article_data["so"])
        article_id = make_article_id(document_id, article_number)

        if article_id not in node_by_id:
            raise ValueError(
                f"Không tìm thấy article_id: {article_id} trong danh sách node"
            )

        graph_node = node_by_id[article_id]

        expected_number = article_number
        actual_number = graph_node.properties.get("number")

        expected_title = article_data.get("tieu_de")
        actual_title = graph_node.properties.get("title")

        expected_content = article_data.get("noi_dung")
        actual_content = graph_node.properties.get("content")

        if expected_number != actual_number:
            raise ValueError(
                f"Article {article_id}"
                f"number mismatch"
                f"Expected ={expected_number}"
                f"Actual = {actual_number}"
            )
        if expected_title != actual_title:
            raise ValueError(f"Article {article_id}title mismatch")
        if expected_content != actual_content:
            raise ValueError(f"Article {article_id}content mismatch")
    print("Article property validation passed")
    return True


def validation_clause_properties(document_data, nodes, resolver):
    node_by_id = {node.id: node for node in nodes}
    document_id = resolver.resolve_document(document_data["so_hieu"])
    clauses = get_all_clauses(document_data)
    for article, clause in clauses:
        clause_number = clause["so"]
        article_number = article["so"]
        clause_id = make_clause_id(document_id, article_number, clause_number)

        if clause_id not in node_by_id:
            raise ValueError(
                f"Không tìm thấy clause_id: {clause_id} trong danh sách node"
            )

        graph_node = node_by_id[clause_id]

        expected_number = clause_number
        actual_number = graph_node.properties.get("number")

        expected_content = clause.get("noi_dung")
        actual_content = graph_node.properties.get("content")

        if expected_number != actual_number:
            raise ValueError(
                f"Clause {clause_id}, "
                f"number mismatch, "
                f"Expected ={expected_number}, "
                f"Actual = {actual_number}"
            )

        if expected_content != actual_content:
            raise ValueError(
                f"Clause {clause_id}, "
                f"content mismatch, "
                f"Expected ={expected_content}, "
                f"Actual = {actual_content}"
            )
    print("Clause property validation passed")
    return True


def validation_point_properties(document_data, nodes, resolver):
    node_by_id = {node.id: node for node in nodes}
    document_id = resolver.resolve_document(document_data["so_hieu"])
    points = get_all_points(document_data)
    for article, clause, point in points:
        point_number = point["so"]
        article_number = article["so"]
        clause_number = clause["so"]
        point_id = make_point_id(
            document_id, article_number, clause_number, point_number
        )
        if point_id not in node_by_id:
            raise ValueError(
                f"Không tìm thấy point_id: {point_id} trong danh sách node"
            )
        graph_node = node_by_id[point_id]
        expected_number = point_number
        actual_number = graph_node.properties.get("number")
        expected_content = point.get("noi_dung")
        actual_content = graph_node.properties.get("content")
        if expected_number != actual_number:
            raise ValueError(
                f"Point {point_id}"
                f"number mismatch"
                f"Expected ={expected_number}"
                f"Actual = {actual_number}"
            )
        if expected_content != actual_content:
            raise ValueError(f"Point {point_id}content mismatch")
    print("Point property validation passed")
    return True


def get_all_articles(document_data):
    articles = []

    for article_data in document_data.get("dieu_khong_chuong", []):
        articles.append(article_data)

    for chapter_data in document_data.get("chuong", []):
        for article_data in chapter_data.get("dieu", []):
            articles.append(article_data)

    return articles


def get_all_clauses(document_data):
    clauses = []
    articles = get_all_articles(document_data)
    for article in articles:
        for clause in article.get("khoan", []):
            clauses.append((article, clause))
    return clauses


def get_all_points(document_data):
    points = []
    clauses = get_all_clauses(document_data)
    for a, c in clauses:
        for point in c.get("diem", []):
            points.append((a, c, point))
    return points


def validate_structure_graph(document_data, nodes, relationships, resolver):
    validate_graph_integrity(nodes, relationships)
    validate_node_ids(document_data, nodes, resolver)
    validate_relationship(document_data, relationships, resolver)
    validation_document_properties(document_data, nodes, resolver)
    validation_chapter_properties(document_data, nodes, resolver)
    validation_article_properties(document_data, nodes, resolver)
    validation_clause_properties(document_data, nodes, resolver)
    validation_point_properties(document_data, nodes, resolver)
    return True
