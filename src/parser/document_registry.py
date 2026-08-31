"""
document_registry.py — Resolve document_id/number từ số hiệu, tên, hoặc alias.

Đây là NGUỒN DUY NHẤT để tra cứu "văn bản này là văn bản nào" — operation.py,
reference.py, amendment_recorder.py đều gọi qua đây, KHÔNG tự tra DOCUMENT_REGISTRY
trực tiếp, để nếu sau này đổi cách resolve (vd thêm fuzzy match) chỉ sửa 1 chỗ.
"""

import re

from src.config import DOCUMENT_REGISTRY
from src.parser.canonical_id_resolver import canonical_document_id, normalize_so_hieu


def _canonical_meta(meta: dict | None) -> dict | None:
    if not meta:
        return None
    result = dict(meta)
    result["number"] = normalize_so_hieu(result["number"])
    result["id"] = canonical_document_id(result["number"])
    return result


SO_HIEU_PATTERN = re.compile(r"(\d+/\d{4}/[A-ZĐ\-]+\d*)")


def resolve_by_number(number: str) -> dict | None:
    """Tra theo số hiệu — chấp nhận cả 'NĐ-CP' và 'ND-CP' (không phân biệt dấu)."""
    if number in DOCUMENT_REGISTRY:
        return _canonical_meta(DOCUMENT_REGISTRY[number])
    normalized = number.replace("NĐ-CP", "ND-CP").replace("nđ-cp", "ND-CP")
    for num, meta in DOCUMENT_REGISTRY.items():
        if num.replace("NĐ-CP", "ND-CP") == normalized:
            return _canonical_meta(meta)
    return None


def resolve_by_alias(text: str) -> dict | None:
    """Tra theo tên/alias xuất hiện TRONG text (khớp gần đúng, không cần y hệt)."""
    text_norm = text.strip().rstrip(".,;")
    # Ưu tiên alias DÀI hơn trước (tránh "Luật Đường bộ" match nhầm khi text
    # thực ra là "Luật Trật tự, an toàn giao thông đường bộ" chứa chung tiền tố)
    candidates = []
    for meta in DOCUMENT_REGISTRY.values():
        for alias in meta["aliases"]:
            if alias.lower() in text_norm.lower():
                candidates.append((len(alias), meta))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return _canonical_meta(candidates[0][1])


def resolve(text: str) -> dict | None:
    """Resolve tổng quát: thử số hiệu tường minh trước (chắc chắn nhất),
    sau đó thử alias/tên."""
    m = SO_HIEU_PATTERN.search(text)
    if m:
        found = resolve_by_number(m.group(1))
        if found:
            return found
    return resolve_by_alias(text)


def get_id(number: str) -> str | None:
    meta = DOCUMENT_REGISTRY.get(number)
    return meta["id"] if meta else None
