"""
config.py

Chỉ chứa:
- System Configuration
- Parser Constants
- Document Registry
- Parser Patterns
- Parser State

Không chứa:
- Tri thức pháp lý (quan hệ sửa đổi A->B, thứ tự áp dụng...)
- Workflow / logic parser
"""

# ==========================================================
# PATH
# ==========================================================

RAW_DIR = "data/raw"
PARSED_DIR = "data/parsed"

# ==========================================================
# DOCUMENT TYPE / ROLE / TARGET LEVEL / PARSER STATE
# ==========================================================

DOCUMENT_TYPES = {"LUAT": "LUAT", "NGHI_DINH": "NGHI_DINH"}
DOCUMENT_ROLES = {"NORMAL": "NORMAL", "AMENDMENT": "AMENDMENT", "OMNIBUS": "OMNIBUS"}
TARGET_LEVEL = {"ARTICLE": "ARTICLE", "CLAUSE": "CLAUSE", "POINT": "POINT"}
PARSER_STATE = {
    "NORMAL": "NORMAL",
    "AMENDMENT_HEADER": "AMENDMENT_HEADER",
    "AMENDMENT_BLOCK": "AMENDMENT_BLOCK",
    "REPLACEMENT_TREE": "REPLACEMENT_TREE",
}

# ==========================================================
# LEGAL RELATIONS
# ==========================================================

REFERENCE_RELATIONS = ["THAM_CHIEU", "CAN_CU_VAO", "NGOAI_LE", "DAN_CHIEU"]
AMENDMENT_RELATIONS = ["SUA_DOI", "BO_SUNG", "THAY_THE", "BAI_BO", "THEM_MOI"]

# ==========================================================
# PARSER KEYWORDS / QUOTE / PATTERNS
# ==========================================================

AMENDMENT_KEYWORDS = ["Sửa đổi", "Bổ sung", "Thay thế", "Bãi bỏ", "Thêm mới"]
QUOTE_CHARS = ['"', "“", "”"]

TARGET_PATTERNS = {
    "ARTICLE": [r"Điều\s+\d+[a-zđ]?"],
    "CLAUSE": [r"khoản\s+\d+[a-zđ]?"],
    "POINT": [r"điểm\s+[a-zđ]"],
}

REFERENCE_PATTERNS = ["Điều này", "Khoản này", "Điểm này", "Luật này", "Nghị định này"]

OPERATION_PRIORITY = ["BAI_BO", "THAY_THE", "SUA_DOI", "BO_SUNG", "THEM_MOI"]

# ==========================================================
# DOCUMENT REGISTRY
# Nguồn sự thật DUY NHẤT về văn bản — KHÔNG lưu quan hệ sửa đổi ở đây.
# document_registry.py sẽ resolve document_id qua number/name/aliases.
# ==========================================================

DOCUMENT_REGISTRY = {
    "35/2024/QH15": {
        "id": "35_2024_QH15", "number": "35/2024/QH15", "name": "Luật Đường bộ",
        "aliases": ["Luật Đường bộ", "Luật số 35/2024/QH15", "35/2024/QH15"],
        "type": "LUAT", "role": "NORMAL",
    },
    "36/2024/QH15": {
        "id": "36_2024_QH15", "number": "36/2024/QH15",
        "name": "Luật Trật tự, an toàn giao thông đường bộ",
        "aliases": ["Luật Trật tự, an toàn giao thông đường bộ", "Luật số 36/2024/QH15", "36/2024/QH15"],
        "type": "LUAT", "role": "NORMAL",
    },
    "118/2025/QH15": {
        "id": "118_2025_QH15", "number": "118/2025/QH15",
        "name": "Luật sửa đổi, bổ sung một số luật về an ninh, trật tự",
        "aliases": ["Luật sửa đổi, bổ sung một số luật về an ninh, trật tự", "Luật số 118/2025/QH15", "118/2025/QH15"],
        "type": "LUAT", "role": "OMNIBUS",
    },
    "151/2024/ND-CP": {
        "id": "151_2024_ND_CP", "number": "151/2024/NĐ-CP",
        "name": "Nghị định quy định chi tiết Luật Trật tự, an toàn giao thông đường bộ",
        "aliases": ["Nghị định 151/2024/NĐ-CP", "Nghị định số 151/2024/NĐ-CP", "151/2024/NĐ-CP", "151/2024/ND-CP"],
        "type": "NGHI_DINH", "role": "NORMAL",
    },
    "168/2024/ND-CP": {
        "id": "168_2024_ND_CP", "number": "168/2024/NĐ-CP",
        "name": "Nghị định xử phạt vi phạm hành chính về trật tự, an toàn giao thông đường bộ",
        "aliases": ["Nghị định 168/2024/NĐ-CP", "Nghị định số 168/2024/NĐ-CP", "168/2024/NĐ-CP", "168/2024/ND-CP"],
        "type": "NGHI_DINH", "role": "NORMAL",
    },
    "184/2025/ND-CP": {
        "id": "184_2025_ND_CP", "number": "184/2025/NĐ-CP",
        "name": "Nghị định phân định thẩm quyền chính quyền 2 cấp (lĩnh vực ANTT)",
        "aliases": ["Nghị định 184/2025/NĐ-CP", "Nghị định số 184/2025/NĐ-CP", "184/2025/NĐ-CP", "184/2025/ND-CP"],
        "type": "NGHI_DINH", "role": "OMNIBUS",
    },
    "236/2026/ND-CP": {
        "id": "236_2026_ND_CP", "number": "236/2026/NĐ-CP",
        "name": "Nghị định sửa đổi, bổ sung Nghị định 151/2024/NĐ-CP",
        "aliases": ["Nghị định 236/2026/NĐ-CP", "Nghị định số 236/2026/NĐ-CP", "236/2026/NĐ-CP", "236/2026/ND-CP"],
        "type": "NGHI_DINH", "role": "AMENDMENT",
    },
    "238/2026/ND-CP": {
        "id": "238_2026_ND_CP", "number": "238/2026/NĐ-CP",
        "name": "Nghị định sửa đổi, bổ sung Nghị định 168/2024/NĐ-CP",
        "aliases": ["Nghị định 238/2026/NĐ-CP", "Nghị định số 238/2026/NĐ-CP", "238/2026/NĐ-CP", "238/2026/ND-CP"],
        "type": "NGHI_DINH", "role": "AMENDMENT",
    },
    "165/2024/ND-CP": {
        "id": "165_2024_ND_CP", "number": "165/2024/NĐ-CP",
        "name": "Nghị định QUY ĐỊNH CHI TIẾT, HƯỚNG DẪN THI HÀNH MỘT SỐ ĐIỀU CỦA LUẬT ĐƯỜNG BỘ VÀ ĐIỀU 77 LUẬT TRẬT TỰ, AN TOÀN GIAO THÔNG ĐƯỜNG BỘ",
        "aliases": ["Nghị định 165/2024/NĐ-CP", "Nghị định số 165/2024/NĐ-CP", "165/2024/NĐ-CP", "165/2024/ND-CP"],
        "type": "NGHI_DINH", "role": "NORMAL",
    },
    "160/2024/ND-CP": {
        "id": "160_2024_ND_CP", "number": "160/2024/NĐ-CP",
        "name": "Nghị định QUY ĐỊNH VỀ HOẠT ĐỘNG ĐÀO TẠO VÀ SÁT HẠCH LÁI XE",
        "aliases": ["Nghị định 160/2024/NĐ-CP", "Nghị định số 160/2024/NĐ-CP", "160/2024/NĐ-CP", "160/2024/ND-CP"],
        "type": "NGHI_DINH", "role": "NORMAL",
    },
    "156/2024/ND-CP": {
        "id": "156_2024_ND_CP", "number": "156/2024/NĐ-CP",
        "name": "Nghị định QUY ĐỊNH VỀ ĐẤU GIÁ BIỂN SỐ XE",
        "aliases": ["Nghị định 156/2024/NĐ-CP", "Nghị định số 156/2024/NĐ-CP", "156/2024/NĐ-CP", "156/2024/ND-CP"],
        "type": "NGHI_DINH", "role": "NORMAL",
    },
}

# ==========================================================
# FILE NAME -> DOCUMENT NUMBER (chỉ mapping file vật lý, không phải tri thức pháp lý)
# ==========================================================

FILE_SO_HIEU_MAP = {
    "168_2024_ND-CP_619502.docx": "168/2024/ND-CP",
    "35_2024_QH15_588811.docx": "35/2024/QH15",
    "36_2024_QH15_m_444251.docx": "36/2024/QH15",
    "151_2024_ND-CP_619564.docx": "151/2024/ND-CP",
    "184_2025_ND-CP_664032.docx": "184/2025/ND-CP",
    "236_2026_ND-CP_712588.docx": "236/2026/ND-CP",
    "238_2026_ND-CP_712521.docx": "238/2026/ND-CP",
    "165_2024_ND-CP_623287.docx": "165/2024/ND-CP",
    "160_2024_ND-CP_624017.docx": "160/2024/ND-CP",
    "156_2024_ND-CP_635371.docx": "156/2024/ND-CP",
    "118_2025_QH15_682798.docx": "118/2025/QH15",
}

# ==========================================================
# OMNIBUS CONFIG — CHỈ khai báo (source, keyword) để LỌC ĐÚNG khối cấp 1 nào
# thuộc về văn bản mục tiêu nào. KHÔNG phải quan hệ sửa đổi (target_document
# vẫn do parser tự resolve qua Document Registry, không hard-code ở đây).
# ==========================================================

OMNIBUS_CONFIG = [
    {
        "source": "118/2025/QH15",
        "targets": [
            {"document": "35/2024/QH15", "keywords": ["Luật Đường bộ", "Luật số 35/2024/QH15", "35/2024/QH15"]},
            {"document": "36/2024/QH15", "keywords": ["Luật Trật tự, an toàn giao thông đường bộ", "Luật số 36/2024/QH15", "36/2024/QH15"]},
        ],
    },
    {
        "source": "184/2025/ND-CP",
        "targets": [
            {"document": "151/2024/ND-CP", "keywords": ["Nghị định 151/2024/NĐ-CP", "Nghị định số 151/2024/NĐ-CP", "151/2024/NĐ-CP"]},
        ],
    },
]

# ==========================================================
# SCOPE CONFIG — Xác định tường minh Selected Scope cho GraphRAG.
# Những document hoặc article KHÔNG nằm trong scope sẽ bị filter ra
# khỏi tập dữ liệu Selected Dataset.
# ==========================================================

SCOPE_CONFIG = {
    "184/2025/ND-CP": {
        "scope_mode": "SELECTED",
        "selected_articles": ["27"]
    },
    "118/2025/QH15": {
        "scope_mode": "SELECTED",
        "selected_articles": ["7", "8"]
    },
    "default": {
        "scope_mode": "ALL"
    }
}

# ==========================================================
# TRƯỜNG HỢP ĐẶC BIỆT: văn bản không đủ thông tin để tự resolve target_document
# (tiêu đề không nhắc lại số hiệu/tên văn bản đích ở từng Điều, chỉ có ở phần
# căn cứ đầu văn bản). Theo đúng ngoại lệ được phép ở quy tắc "không hard-code
# quan hệ sửa đổi" — CHỈ dùng khi parser tự resolve thất bại, không phải nguồn
# sự thật chính.
# ==========================================================

AMENDMENT_TARGET_FALLBACK = {
    "184/2025/ND-CP": "151/2024/ND-CP",
    "238/2026/ND-CP": "168/2024/ND-CP",
    "236/2026/ND-CP": "151/2024/ND-CP",
}

# Văn bản sửa đổi gộp có thể sửa nhiều văn bản đích; target phải được chọn
# theo Điều cấp cao nhất thay vì dùng một fallback chung cho toàn văn bản.
AMENDMENT_ARTICLE_TARGETS = {
    "118/2025/QH15": {
        "7": "36/2024/QH15",
        "8": "35/2024/QH15",
    },
    "184/2025/ND-CP": {
        "27": "151/2024/ND-CP",
    },
}


# ==========================================================
# Tương thích ngược: VAN_BAN_SCOPE (dùng bởi reference.py, semantic_unit.py,
# chunker.py, exporter.py...) — suy ra TỰ ĐỘNG từ DOCUMENT_REGISTRY, không
# khai báo trùng lặp lần 2.
# ==========================================================

VAN_BAN_SCOPE = {
    number: {
        "ten": meta["name"],
        "loai": ("NghiDinh_suaDoi" if meta["role"] == "AMENDMENT"
                  else "Luat_gop" if meta["role"] == "OMNIBUS" and meta["type"] == "LUAT"
                  else "NghiDinh_phanDinhThamQuyen" if meta["role"] == "OMNIBUS"
                  else "Luat" if meta["type"] == "LUAT" else "NghiDinh"),
        "pham_vi_ngoai_scope": meta["role"] == "OMNIBUS",
    }
    for number, meta in DOCUMENT_REGISTRY.items()
}
