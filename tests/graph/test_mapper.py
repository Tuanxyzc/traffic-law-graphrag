import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.graph.mapper import map_article, map_clause, map_document, map_point
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

document_data = {"so_hieu": "236/2026/NĐ-CP"}


article_data = {"so": "16", "tieu_de": "Bãi bỏ..."}


clause_data = {"so": "5", "noi_dung": "Bãi bỏ khoản 3, khoản 4 Điều 27..."}


point_data = {"so": "a", "noi_dung": "Nội dung điểm a..."}


resolver = CanonicalIDResolver()
document = map_document(document_data, resolver)

article, article_rel = map_article(document.id, article_data)

clause, clause_rel = map_clause(document.id, article_data["so"], clause_data)

point, point_rel = map_point(
    document.id, article_data["so"], clause_data["so"], point_data
)


print(document)
print(article)
print(article_rel)
print(clause)
print(clause_rel)
print(point)
print(point_rel)
