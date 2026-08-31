"""
operation.py — Xác định HÀNH ĐỘNG lập pháp (sửa/bổ sung/bãi bỏ/thay thế) và
VỊ TRÍ ĐÍCH mà hành động đó áp dụng, dựa trên câu dẫn (thường là câu đầu tiên
của 1 Khoản/mục trong văn bản sửa đổi).

Ví dụ:
    "Sửa đổi, bổ sung khoản 1 Điều 9 như sau:"      -> SUA_DOI, [Điều 9, Khoản 1]
    "Bổ sung Điều 25a vào sau Điều 25"               -> BO_SUNG, [Điều 25a]
    "Bãi bỏ khoản 3 Điều 6 và Điều 8"                -> BAI_BO,  [Khoản 3 Điều 6, Điều 8]
    "Thay thế cụm từ ... tại điểm g khoản 8 Điều 11,
     điểm b khoản 1 Điều 12"                          -> THAY_THE, [2 vị trí]
"""

import re

from src.parser import document_registry
from src.parser.models import ViTri

VI_TRI_DIEU = re.compile(r"Điều\s+(\d+[a-zđ]?)")
VI_TRI_KHOAN = re.compile(r"[Kk]hoản\s+(\d+[a-zđ]?)")
VI_TRI_DIEM = re.compile(r"[Đđ]iểm\s+([a-zđ]\d*)\b")

# Thứ tự kiểm tra CÓ Ý NGHĨA: kiểm tra các từ khóa đặc thù trước, "sửa đổi" chung chung sau cùng
OPERATION_KEYWORDS = [
    (
        "THAY_THE_PHU_LUC",
        re.compile(r"thay\s+thế\s+(một\s+số\s+)?phụ\s+lục", re.IGNORECASE),
    ),
    (
        "THAY_THE_TEXT",
        re.compile(r"thay\s+thế\s+(?:một\s+số\s+)?(?:từ|cụm\s+từ)", re.IGNORECASE),
    ),
    ("BO_SUNG_TEXT", re.compile(r"bổ\s+sung\s+(?:từ|cụm\s+từ)", re.IGNORECASE)),
    ("BAI_BO_TEXT", re.compile(r"(bãi\s+bỏ|bỏ)\s+(?:từ|cụm\s+từ)", re.IGNORECASE)),
    ("BAI_BO", re.compile(r"bãi\s+bỏ", re.IGNORECASE)),
    (
        "THAY_THE",
        re.compile(r"thay\s+thế\s+(cụm\s+từ|một\s+số\s+cụm\s+từ)", re.IGNORECASE),
    ),  # Giữ lại để back-compat hoặc bỏ? Nếu đã có THAY_THE_TEXT thì bỏ cụm từ ở đây
    ("THAY_THE", re.compile(r"thay\s+thế", re.IGNORECASE)),
    ("THEM_MOI", re.compile(r"thêm\s+mới", re.IGNORECASE)),
    (
        "BO_SUNG",
        re.compile(r"bổ\s+sung.{0,30}vào\s+sau", re.IGNORECASE),
    ),  # "bổ sung Điều X vào sau Điều Y" -> entity MỚI
    ("SUA_DOI", re.compile(r"sửa\s+đổi", re.IGNORECASE)),
    (
        "BO_SUNG",
        re.compile(r"bổ\s+sung", re.IGNORECASE),
    ),  # bổ sung nhưng không có "vào sau" -> vẫn coi là bổ sung nội dung/khoản mới
]


def detect_operation(text: str) -> str | None:
    """Trả về 1 trong: SUA_DOI | BO_SUNG | BAI_BO | THAY_THE | None (không xác định)."""
    for label, pattern in OPERATION_KEYWORDS:
        if pattern.search(text):
            return label
    return None


# Removed _extract_vi_tri_list as target_resolver is now the canonical implementation.


def detect_target(text: str, default_so_hieu: str | None = None) -> list[ViTri]:
    """
    Trích xuất TẤT CẢ vị trí đích được nêu trong câu dẫn. Luôn trả về list
    (kể cả khi chỉ có 1 vị trí) để nơi gọi không phải xử lý 2 kiểu khác nhau.

    Sử dụng canonical target_resolver.
    """
    from src.parser.target_resolver import resolve_targets

    resolved = resolve_targets(text, default_document=default_so_hieu)
    return [r.as_vitri() for r in resolved]


def detect_target_document(text: str) -> dict | None:
    """Resolve RIÊNG tên/số hiệu văn bản đích từ 1 đoạn text (vd tiêu đề
    'Điều 8. Sửa đổi, bổ sung một số điều của Luật Đường bộ') — dùng khi cần
    biết target_document độc lập với vị trí Điều/Khoản/Điểm cụ thể."""
    return document_registry.resolve(text)
