from src.graph.mapper import map_article, map_clause, map_document, map_point
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver


def test_map_document():
    document_data = {"so_hieu": "236/2026/NĐ-CP"}
    resolver = CanonicalIDResolver()
    document = map_document(document_data, resolver)
    assert document.id == "236_2026_ND-CP"
    assert document.label == "Document"


def test_map_article_clause_and_point_hierarchy():
    document_id = "236_2026_ND-CP"
    article_data = {"so": "16", "tieu_de": "Bãi bỏ..."}
    clause_data = {"so": "5", "noi_dung": "Bãi bỏ khoản 3, khoản 4 Điều 27..."}
    point_data = {"so": "a", "noi_dung": "Nội dung điểm a..."}

    article, article_rel = map_article(document_id, article_data)
    assert article.id == "236_2026_ND-CP_D16"
    assert article_rel.relationship_type == "CONTAINS_ARTICLE"
    assert article_rel.start_id == document_id
    assert article_rel.end_id == article.id

    clause, clause_rel = map_clause(document_id, article_data["so"], clause_data)
    assert clause.id == "236_2026_ND-CP_D16_K5"
    assert clause_rel.relationship_type == "CONTAINS_CLAUSE"
    assert clause_rel.start_id == article.id
    assert clause_rel.end_id == clause.id

    point, point_rel = map_point(
        document_id, article_data["so"], clause_data["so"], point_data
    )
    assert point.id == "236_2026_ND-CP_D16_K5_Da"
    assert point_rel.relationship_type == "CONTAINS_POINT"
    assert point_rel.start_id == clause.id
    assert point_rel.end_id == point.id
