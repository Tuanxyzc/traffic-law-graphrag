def make_chapter_id(document_id: str, chapter_number: str) -> str:
    return f"{document_id}_C{chapter_number}"


def make_article_id(document_id: str, article_number: str) -> str:
    return f"{document_id}_D{article_number}"


def make_clause_id(document_id: str, article_number: str, clause_number: str) -> str:
    return f"{document_id}_D{article_number}_K{clause_number}"


def make_point_id(
    document_id: str, article_number: str, clause_number: str, point_number: str
) -> str:
    return f"{document_id}_D{article_number}_K{clause_number}_D{point_number}"
