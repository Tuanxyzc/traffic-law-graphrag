from src.graph.identity import (
    make_article_id,
    make_chapter_id,
    make_clause_id,
    make_point_id,
)
from src.graph.models import GraphNode, GraphRelationship


def map_structure(document_data):
    document_node = map_document(document_data)
    nodes = [document_node]
    relationships = []

    document_id = document_node.id

    articles = document_data.get("dieu_khong_chuong", [])

    article_nodes, article_relationships = map_articles(document_id, articles)

    nodes.extend(article_nodes)
    relationships.extend(article_relationships)

    return nodes, relationships


def map_document(document_data, resolver):

    so_hieu = document_data["so_hieu"]

    document_id = resolver.resolve_document(so_hieu)

    node = GraphNode(
        label="Document",
        id=document_id,
        properties={
            "so_hieu": so_hieu,
            "ten": document_data.get("ten"),
            "loai": document_data.get("loai"),
            "ngay_ban_hanh": document_data.get("ngay_ban_hanh"),
            "co_quan_ban_hanh": document_data.get("co_quan_ban_hanh"),
            "trang_thai_hieu_luc": document_data.get("trang_thai_hieu_luc"),
            "hieu_luc_tu": document_data.get("hieu_luc_tu"),
            "cap": document_data.get("cap"),
        },
    )
    return node


def map_chapter(document_id: str, chapter_data: dict):

    so = str(chapter_data["so"])
    chapter_id = make_chapter_id(document_id, so)

    node = GraphNode(
        label="Chapter",
        id=chapter_id,
        properties={"number": so, "title": chapter_data.get("tieu_de", "")},
    )

    relationship = GraphRelationship(
        start_id=document_id, relationship_type="CONTAINS_CHAPTER", end_id=chapter_id
    )
    return node, relationship


def map_chapter_articles(document_id: str, chapter_data: dict):
    nodes = []
    relationships = []

    chapter_id = make_chapter_id(document_id, str(chapter_data["so"]))

    for article_data in chapter_data.get("dieu", []):
        article_nodes, article_relationships = map_article(
            document_id, article_data, chapter_id
        )
        nodes.append(article_nodes)
        relationships.append(article_relationships)

        for clause_data in article_data.get("khoan", []):
            clause_nodes, clause_relationships = map_clause(
                document_id, article_data["so"], clause_data
            )
            nodes.append(clause_nodes)
            relationships.append(clause_relationships)

            for point_data in clause_data.get("diem", []):
                point_nodes, point_relationships = map_point(
                    document_id, article_data["so"], clause_data["so"], point_data
                )
                nodes.append(point_nodes)
                relationships.append(point_relationships)
    return nodes, relationships


def map_article(document_id: str, article_data: dict, parent_id: str = None):

    so = str(article_data["so"])
    article_id = make_article_id(document_id, so)

    node = GraphNode(
        label="Article",
        id=article_id,
        properties={
            "number": so,
            "title": article_data.get("tieu_de", ""),
            "content": article_data.get("noi_dung", ""),
        },
    )

    if parent_id is None:
        parent_id = document_id
        relationship_type = "CONTAINS_ARTICLE"
    else:
        relationship_type = "CONTAINS_ARTICLE"

    relationship = GraphRelationship(
        start_id=parent_id, relationship_type=relationship_type, end_id=article_id
    )
    return node, relationship


def map_clause(document_id: str, article_number: str, clause_data: dict):

    number = str(clause_data["so"])

    clause_id = make_clause_id(document_id, article_number, number)
    article_id = make_article_id(document_id, article_number)
    node = GraphNode(
        label="Clause",
        id=clause_id,
        properties={"number": number, "content": clause_data.get("noi_dung", "")},
    )

    relationship = GraphRelationship(
        start_id=article_id, relationship_type="CONTAINS_CLAUSE", end_id=clause_id
    )
    return node, relationship


def map_point(
    document_id: str, article_number: str, clause_number: str, point_data: dict
):

    number = str(point_data["so"])
    point_id = make_point_id(document_id, article_number, clause_number, number)

    node = GraphNode(
        label="Point",
        id=point_id,
        properties={"number": number, "content": point_data.get("noi_dung", "")},
    )
    relationship = GraphRelationship(
        start_id=make_clause_id(document_id, article_number, clause_number),
        relationship_type="CONTAINS_POINT",
        end_id=point_id,
    )
    return node, relationship


def map_articles(document_id: str, articles: list):
    nodes = []
    relationships = []
    for article_data in articles:
        node, relationship = map_article(document_id, article_data)
        nodes.append(node)
        relationships.append(relationship)

        clause_nodes, clause_relationships = map_clauses(document_id, article_data)
        nodes.extend(clause_nodes)
        relationships.extend(clause_relationships)
    return nodes, relationships


def map_clauses(document_id, article_data: dict):

    nodes = []
    relationships = []

    so = str(article_data["so"])

    clauses = article_data.get("khoan", [])

    for clause_data in clauses:
        node, relationship = map_clause(document_id, so, clause_data)
        nodes.append(node)
        relationships.append(relationship)

        point_nodes, point_relationships = map_points(document_id, so, clause_data)

        nodes.extend(point_nodes)
        relationships.extend(point_relationships)

    return nodes, relationships


def map_points(document_id, article_number: str, clause_data):

    nodes = []
    relationships = []

    so = str(clause_data["so"])

    points = clause_data.get("diem", [])

    for point_data in points:
        node, relationship = map_point(document_id, article_number, so, point_data)
        nodes.append(node)
        relationships.append(relationship)

    return nodes, relationships


def map_document_structure(document_data: dict, resolver):

    nodes = []
    relationships = []

    document_node = map_document(document_data, resolver)
    nodes.append(document_node)
    document_id = document_node.id

    for chapter_data in document_data.get("chuong", []):
        chapter_node, chapter_relationship = map_chapter(document_id, chapter_data)
        nodes.append(chapter_node)
        relationships.append(chapter_relationship)

        chapter_nodes, chapter_relationships = map_chapter_articles(
            document_id, chapter_data
        )
        nodes.extend(chapter_nodes)
        relationships.extend(chapter_relationships)

    for article_data in document_data.get("dieu_khong_chuong", []):
        article_node, article_relationship = map_article(document_id, article_data)
        nodes.append(article_node)
        relationships.append(article_relationship)
        for clause_data in article_data.get("khoan", []):
            clause_node, clause_relationship = map_clause(
                document_id, str(article_data["so"]), clause_data
            )
            nodes.append(clause_node)
            relationships.append(clause_relationship)
            for point_data in clause_data.get("diem", []):
                point_node, point_relationship = map_point(
                    document_id,
                    str(article_data["so"]),
                    str(clause_data["so"]),
                    point_data,
                )
                nodes.append(point_node)
                relationships.append(point_relationship)
    return nodes, relationships
