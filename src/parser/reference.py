"""
reference.py — Resolve MỌI tham chiếu trong nội dung thành ViTri tuyệt đối,
kèm phân loại quan hệ (quan_he) để xuất thẳng ra reference_index.json — LLM
KHÔNG cần resolve lại "Điều này"/"Luật này" hay suy luận quan hệ.

Các dạng được resolve:
    Điều này / khoản này / điểm này              -> tương đối, cùng cấp hiện tại
    khoản 2 Điều này / điểm b khoản này /
    điểm c khoản 3 Điều này                        -> tuyệt đối 1 phần + tương đối 1 phần
    Luật này / Nghị định này / Thông tư này        -> văn bản hiện tại
    Điều 20 Luật này / Điều 15 Nghị định này        -> tuyệt đối trong văn bản hiện tại
    Điều 17 Luật Đường bộ                           -> tuyệt đối, tra so_hieu qua VAN_BAN_SCOPE (theo tên)
    Điều 45 Nghị định số 151/2024/NĐ-CP             -> tuyệt đối, tra so_hieu trực tiếp từ số hiệu nêu rõ trong text
"""

import re

from src.parser import document_registry
from src.parser.models import ThamChieu, ViTri

DIEU_SO = r"(\d+[a-zđ]?)"
SO_HIEU_PATTERN = re.compile(
    r"(\d+/\d{4}/[A-ZĐ\-]+\d*)"
)  # vd "151/2024/NĐ-CP", "35/2024/QH15"

# Sắp xếp TỪ CỤ THỂ NHẤT ĐẾN CHUNG NHẤT — pattern đứng trước match trước,
# tránh bị pattern chung ("Điều này") nuốt mất phần đã đủ tuyệt đối.
PATTERNS = [
    (
        "diem_khoan_dieu_tuyet_doi_nay",
        re.compile(
            rf"điểm\s+([a-zđ])\s+khoản\s+{DIEU_SO}\s+Điều\s+{DIEU_SO}\s+(?:của\s+)?"
            r"(?:Luật|Nghị định|Thông tư)\s+này",
            re.IGNORECASE,
        ),
    ),
    (
        "khoan_dieu_tuyet_doi_nay",
        re.compile(
            rf"khoản\s+{DIEU_SO}\s+Điều\s+{DIEU_SO}\s+(?:của\s+)?"
            r"(?:Luật|Nghị định|Thông tư)\s+này",
            re.IGNORECASE,
        ),
    ),
    # Vị trí chi tiết liên văn bản: "điểm a khoản 3 Điều 46 của Luật ..."
    (
        "diem_khoan_dieu_cheo_ten",
        re.compile(
            rf"điểm\s+([a-zđ])\s+khoản\s+{DIEU_SO}\s+Điều\s+{DIEU_SO}\s+(?:của\s+)?"
            rf"(Luật\s+(?!này\b)[^,.;\n]{{2,100}}?)(?=\s+(?:và|hoặc|quy định|được|tại|theo|điều khiển)\b|[,.;\n]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "khoan_dieu_cheo_ten",
        re.compile(
            rf"khoản\s+{DIEU_SO}\s+Điều\s+{DIEU_SO}\s+(?:của\s+)?"
            rf"(Luật\s+(?!này\b)[^,.;\n]{{2,100}}?)(?=\s+(?:và|hoặc|quy định|được|tại|theo|điều khiển)\b|[,.;\n]|$)",
            re.IGNORECASE,
        ),
    ),
    # 1. Tuyệt đối + tên văn bản chéo có SỐ HIỆU rõ ràng: "Điều 45 Nghị định số 151/2024/NĐ-CP"
    (
        "dieu_cheo_so_hieu",
        re.compile(
            rf"Điều\s+{DIEU_SO}\s+(?:của\s+)?(?:Nghị định|Luật|Thông tư)(?:\s+số)?\s+({SO_HIEU_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    # 2. Tuyệt đối + tên văn bản chéo nêu TÊN (không có số hiệu): "Điều 17 Luật Đường bộ"
    (
        "dieu_cheo_ten",
        re.compile(
            rf"Điều\s+{DIEU_SO}\s+(?:của\s+)?(Luật\s+(?!này\b)[^,.;\n]{{2,100}}?|Nghị định\s+số\s+{SO_HIEU_PATTERN.pattern})"
            rf"(?=\s+(?:và|hoặc|quy định|được|tại|theo|của)\b|[,.;\n]|$)",
            re.IGNORECASE,
        ),
    ),
    # 3. Tuyệt đối trong CHÍNH văn bản này: "Điều 20 Luật này" / "Điều 15 Nghị định này"
    (
        "dieu_tuyet_doi_nay",
        re.compile(
            rf"Điều\s+{DIEU_SO}\s+(Luật|Nghị định|Thông tư)\s+này", re.IGNORECASE
        ),
    ),
    # 4. Kết hợp tuyệt đối + tương đối: "điểm c khoản 3 Điều này"
    (
        "diem_khoan_tuyet_doi_dieu_nay",
        re.compile(rf"điểm\s+([a-zđ])\s+khoản\s+{DIEU_SO}\s+Điều\s+này", re.IGNORECASE),
    ),
    # 5. "khoản 2 Điều này"
    (
        "khoan_tuyet_doi_dieu_nay",
        re.compile(rf"khoản\s+{DIEU_SO}\s+Điều\s+này", re.IGNORECASE),
    ),
    # 6. "điểm b khoản này"
    (
        "diem_tuyet_doi_khoan_nay",
        re.compile(r"điểm\s+([a-zđ])\s+khoản\s+này", re.IGNORECASE),
    ),
    # 7. Thuần tương đối
    ("dieu_nay", re.compile(r"[Đđ]iều\s+này")),
    ("khoan_nay", re.compile(r"[Kk]hoản\s+này")),
    ("diem_nay", re.compile(r"[Đđ]iểm\s+này")),
    ("van_ban_nay", re.compile(r"(Nghị định|Luật|Thông tư)\s+này", re.IGNORECASE)),
]

QUAN_HE_KEYWORDS = [
    ("CAN_CU_VAO", re.compile(r"căn\s+cứ", re.IGNORECASE)),
    ("NGOAI_LE", re.compile(r"trừ\s+(trường\s+hợp|quy\s+định)", re.IGNORECASE)),
]


_KHOAN = "kho\u1ea3n"
_DIEU = "\u0110i\u1ec1u"
_VAN_BAN_NAY = r"(?:Lu\u1eadt|Ngh\u1ecb \u0111\u1ecbnh|Th\u00f4ng t\u01b0)\s+n\u00e0y"
_SO_DON_VI = r"(\d+[a-z\u0111]?)"
_CAP_DON_VI = r"(?:,|v\u00e0|ho\u1eb7c)"

_KHOAN_LIST_DIEU_NAY = re.compile(
    rf"{_KHOAN}\s+{_SO_DON_VI}(?:\s*{_CAP_DON_VI}\s*{_KHOAN}\s+{_SO_DON_VI})+\s+{_DIEU}\s+n\u00e0y",
    re.IGNORECASE,
)
_KHOAN_LIST_DIEU_SO_NAY = re.compile(
    rf"(?P<clauses>{_KHOAN}\s+{_SO_DON_VI}"
    rf"(?:\s*{_CAP_DON_VI}\s*{_KHOAN}\s+{_SO_DON_VI})+)"
    rf"\s+{_DIEU}\s+(?P<article>\d+[a-z\u0111]?)"
    rf"\s+(?:c\u1ee7a\s+)?{_VAN_BAN_NAY}",
    re.IGNORECASE,
)
_KHOAN_DIEU_SERIES_NAY = re.compile(
    rf"(?P<series>{_KHOAN}\s+{_SO_DON_VI}\s+{_DIEU}\s+{_SO_DON_VI}"
    rf"(?:\s*{_CAP_DON_VI}\s*{_KHOAN}\s+{_SO_DON_VI}\s+{_DIEU}\s+{_SO_DON_VI})+)"
    rf"\s+(?:c\u1ee7a\s+)?{_VAN_BAN_NAY}",
    re.IGNORECASE,
)
_KHOAN_DIEU_PAIR = re.compile(
    rf"{_KHOAN}\s+(\d+[a-z\u0111]?)\s+{_DIEU}\s+(\d+[a-z\u0111]?)",
    re.IGNORECASE,
)


def _tra_so_hieu_theo_ten(ten_text: str) -> str | None:
    """Tra so_hieu từ tên văn bản, qua Document Registry (số hiệu/tên/alias)."""
    meta = document_registry.resolve_by_alias(ten_text)
    if not meta:
        compact = re.sub(r"\s+", " ", ten_text).strip().lower()
        # Tên rút gọn được dùng phổ biến trong các nghị định hướng dẫn.
        if compact.startswith("luật trật tự"):
            meta = document_registry.resolve_by_number("36/2024/QH15")
        elif compact == "luật đường bộ" or compact.startswith("luật đường bộ "):
            meta = document_registry.resolve_by_number("35/2024/QH15")
    return meta["number"] if meta else None


def _quan_he_cho(text_quanh: str) -> str:
    for quan_he, pattern in QUAN_HE_KEYWORDS:
        if pattern.search(text_quanh):
            return quan_he
    return "THAM_CHIEU"


def resolve_references(
    text: str, vi_tri_hien_tai: ViTri, so_hieu_hien_tai: str
) -> list[ThamChieu]:
    """Quét text theo thứ tự pattern cụ thể -> chung, resolve mỗi tham chiếu
    thành ViTri tuyệt đối kèm phân loại quan_he. Đã match ở vùng nào thì loại
    trừ vùng đó khỏi các pattern sau (tránh match trùng/lồng)."""
    result: list[ThamChieu] = []
    da_match: list[
        tuple[int, int]
    ] = []  # các khoảng (start,end) đã bị 1 pattern cụ thể hơn nuốt

    def da_bi_nuot(start, end) -> bool:
        return any(s <= start and end <= e for s, e in da_match)

    def them_tham_chieu(loai, van_ban_goc, gia_tri, start, end):
        quan_he = _quan_he_cho(text[max(0, start - 40) : start])
        result.append(
            ThamChieu(
                loai=loai,
                van_ban_goc=van_ban_goc,
                gia_tri_xac_dinh=gia_tri,
                quan_he=quan_he,
            )
        )
        da_match.append((start, end))

    # Mixed point/clause series ending in ``Điều này`` are best parsed by the
    # hierarchical target resolver. For example, each group in ``điểm a ...
    # khoản 2; ...; khoản 7; điểm đ khoản 11 Điều này`` has its own clause
    # context; only the article is shared by the complete series.
    series_pattern = re.compile(
        r"(?P<series>(?:điểm\s+[a-zđ]\d*\b|khoản\s+\d+[a-zđ]?)"
        r"[^.\n]*?Điều\s+này)",
        re.IGNORECASE,
    )
    from src.parser.target_resolver import resolve_targets

    for m in series_pattern.finditer(text):
        if da_bi_nuot(m.start(), m.end()):
            continue
        series_text = m.group("series")
        if re.search(r"Điều\s+\d+[a-zđ]?", series_text, re.IGNORECASE):
            continue
        normalized_series = re.sub(
            r"Điều\s+này",
            f"Điều {vi_tri_hien_tai.dieu}",
            series_text,
            flags=re.IGNORECASE,
        )
        resolved_targets = resolve_targets(
            normalized_series,
            default_document=so_hieu_hien_tai,
        )
        if not resolved_targets:
            continue
        for target in resolved_targets:
            them_tham_chieu(
                "structural_series",
                series_text,
                target.as_vitri(),
                m.start(),
                m.end(),
            )

    # Resolve coordinated references before the single-reference patterns.
    # Each explicit ``khoan X Dieu Y`` is a separate target even when the
    # document qualifier appears only after the final element in the series.
    for m in _KHOAN_DIEU_SERIES_NAY.finditer(text):
        if da_bi_nuot(m.start(), m.end()):
            continue
        for pair in _KHOAN_DIEU_PAIR.finditer(m.group("series")):
            them_tham_chieu(
                "khoan_dieu_tuyet_doi_nay",
                pair.group(0),
                ViTri(
                    dieu=pair.group(2),
                    khoan=pair.group(1),
                    so_hieu_van_ban=so_hieu_hien_tai,
                ),
                m.start(),
                m.end(),
            )

    # ``khoan 1 va khoan 2 Dieu nay`` is a list of clauses in the current
    # article. The article context may be shared, but every explicit clause
    # remains a separate reference.
    for m in _KHOAN_LIST_DIEU_NAY.finditer(text):
        if da_bi_nuot(m.start(), m.end()):
            continue
        clause_numbers = re.findall(
            rf"{_KHOAN}\s+(\d+[a-z\u0111]?)", m.group(0), re.IGNORECASE
        )
        for clause_number in clause_numbers:
            them_tham_chieu(
                "khoan_tuyet_doi_dieu_nay",
                f"{_KHOAN} {clause_number} {_DIEU} n\u00e0y",
                ViTri(
                    dieu=vi_tri_hien_tai.dieu,
                    khoan=clause_number,
                    so_hieu_van_ban=so_hieu_hien_tai,
                ),
                m.start(),
                m.end(),
            )

    # Several clauses may share one explicit article and one trailing document
    # qualifier: ``khoan 1, khoan 2, khoan 3 Dieu 23 cua Nghi dinh nay``.
    for m in _KHOAN_LIST_DIEU_SO_NAY.finditer(text):
        if da_bi_nuot(m.start(), m.end()):
            continue
        clause_numbers = re.findall(
            rf"{_KHOAN}\s+(\d+[a-z\u0111]?)",
            m.group("clauses"),
            re.IGNORECASE,
        )
        for clause_number in clause_numbers:
            them_tham_chieu(
                "khoan_dieu_tuyet_doi_nay",
                f"{_KHOAN} {clause_number} {_DIEU} {m.group('article')}",
                ViTri(
                    dieu=m.group("article"),
                    khoan=clause_number,
                    so_hieu_van_ban=so_hieu_hien_tai,
                ),
                m.start(),
                m.end(),
            )

    for loai, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if da_bi_nuot(m.start(), m.end()):
                continue

            quan_he = _quan_he_cho(text[max(0, m.start() - 40) : m.start()])

            if loai == "diem_khoan_dieu_tuyet_doi_nay":
                gia_tri = ViTri(
                    dieu=m.group(3),
                    khoan=m.group(2),
                    diem=m.group(1),
                    so_hieu_van_ban=so_hieu_hien_tai,
                )
            elif loai == "khoan_dieu_tuyet_doi_nay":
                gia_tri = ViTri(
                    dieu=m.group(2), khoan=m.group(1), so_hieu_van_ban=so_hieu_hien_tai
                )
            elif loai == "diem_khoan_dieu_cheo_ten":
                so_hieu = _tra_so_hieu_theo_ten(m.group(4))
                gia_tri = ViTri(
                    dieu=m.group(3),
                    khoan=m.group(2),
                    diem=m.group(1),
                    so_hieu_van_ban=so_hieu,
                )
            elif loai == "khoan_dieu_cheo_ten":
                so_hieu = _tra_so_hieu_theo_ten(m.group(3))
                gia_tri = ViTri(
                    dieu=m.group(2), khoan=m.group(1), so_hieu_van_ban=so_hieu
                )
            elif loai == "dieu_cheo_so_hieu":
                gia_tri = ViTri(dieu=m.group(1), so_hieu_van_ban=m.group(2))
            elif loai == "dieu_cheo_ten":
                so_hieu = _tra_so_hieu_theo_ten(m.group(2))
                gia_tri = ViTri(dieu=m.group(1), so_hieu_van_ban=so_hieu)
            elif loai == "dieu_tuyet_doi_nay":
                gia_tri = ViTri(dieu=m.group(1), so_hieu_van_ban=so_hieu_hien_tai)
            elif loai == "diem_khoan_tuyet_doi_dieu_nay":
                gia_tri = ViTri(
                    dieu=vi_tri_hien_tai.dieu,
                    khoan=m.group(2),
                    diem=m.group(1),
                    so_hieu_van_ban=so_hieu_hien_tai,
                )
            elif loai == "khoan_tuyet_doi_dieu_nay":
                gia_tri = ViTri(
                    dieu=vi_tri_hien_tai.dieu,
                    khoan=m.group(1),
                    so_hieu_van_ban=so_hieu_hien_tai,
                )
            elif loai == "diem_tuyet_doi_khoan_nay":
                gia_tri = ViTri(
                    dieu=vi_tri_hien_tai.dieu,
                    khoan=vi_tri_hien_tai.khoan,
                    diem=m.group(1),
                    so_hieu_van_ban=so_hieu_hien_tai,
                )
            elif loai == "dieu_nay":
                gia_tri = ViTri(
                    dieu=vi_tri_hien_tai.dieu, so_hieu_van_ban=so_hieu_hien_tai
                )
            elif loai == "khoan_nay":
                gia_tri = ViTri(
                    dieu=vi_tri_hien_tai.dieu,
                    khoan=vi_tri_hien_tai.khoan,
                    so_hieu_van_ban=so_hieu_hien_tai,
                )
            elif loai == "diem_nay":
                gia_tri = ViTri(
                    dieu=vi_tri_hien_tai.dieu,
                    khoan=vi_tri_hien_tai.khoan,
                    diem=vi_tri_hien_tai.diem,
                    so_hieu_van_ban=so_hieu_hien_tai,
                )
            else:  # van_ban_nay
                gia_tri = ViTri(so_hieu_van_ban=so_hieu_hien_tai)

            result.append(
                ThamChieu(
                    loai=loai,
                    van_ban_goc=m.group(0),
                    gia_tri_xac_dinh=gia_tri,
                    quan_he=quan_he,
                )
            )
            da_match.append((m.start(), m.end()))

    return result
