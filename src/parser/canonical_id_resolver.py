def normalize_so_hieu(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().replace("NĐ-CP", "ND-CP").replace("QĐ-TTg", "QD-TTg")


def canonical_document_id(value: str | None) -> str | None:
    normalized = normalize_so_hieu(value)
    return normalized.replace("/", "_") if normalized else None
