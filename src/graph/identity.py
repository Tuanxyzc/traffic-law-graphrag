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


def make_version_id(provision_id: str, version_number: int) -> str:
    return f"{provision_id}_V{version_number}"


def make_semantic_unit_id(source_unit: str, index: int) -> str:
    return f"{source_unit}_SU{index}"


def make_action_id(semantic_unit_id: str, action_index: int) -> str:
    return f"{semantic_unit_id}_A{action_index}"
