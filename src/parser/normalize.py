"""
normalize.py — Chuẩn hóa văn bản đầu vào.

Module này KHÔNG biết Điều, Khoản, hay Điểm là gì. Chỉ đọc file và làm sạch
text ở mức thô: unicode, khoảng trắng, số trang, header/footer lặp lại.
"""

import re
import unicodedata
from dataclasses import dataclass

import docx


@dataclass
class DoanVan:
    """1 đoạn văn sau khi đọc từ DOCX, giữ lại thuộc tính in đậm (bold) —
    đây là tín hiệu ĐỊNH DẠNG thuần túy, không phải khái niệm pháp lý, nên
    vẫn hợp lệ để normalize.py cung cấp cho structure.py dùng sau này."""
    text: str
    dam: bool   # in đậm hay không


PAGE_NUMBER_PATTERN = re.compile(r"^\s*\d{1,4}\s*$")
BOILERPLATE_PATTERNS = [
    re.compile(r"^CỘNG\s+HÒA\s+XÃ\s+HỘI", re.IGNORECASE),
    re.compile(r"^Độc\s+lập\s*[-–]\s*Tự\s+do\s*[-–]\s*Hạnh\s+phúc", re.IGNORECASE),
]


def load_docx(path: str) -> list[DoanVan]:
    """Đọc file DOCX, trả về danh sách đoạn văn (đã bỏ đoạn rỗng)."""
    doc = docx.Document(path)
    result = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        dam = any(run.bold for run in p.runs if run.text.strip())
        result.append(DoanVan(text=text, dam=dam))
    return result


def normalize_text(text: str) -> str:
    """Chuẩn hóa unicode (NFC), xóa khoảng trắng dư, chuẩn hóa xuống dòng."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Fix typo: straight quote at start of line used as opening quote
    text = re.sub(r'^"(?=[\w])', '“', text)
    # Fix typo: straight quote at end of line used as closing quote
    text = re.sub(r'"$', '”', text)
    # Fix typo: straight quote before punctuation
    text = re.sub(r'"(?=[\.\,\;\:\!\?])', '”', text)
    return text.strip()


def normalize_so_hieu(so_hieu: str) -> str:
    """Chuẩn hóa các alias pháp lý đã biết thành dạng chuẩn (Canonical ID)."""
    # VD: 151/2024/NĐ-CP -> 151/2024/ND-CP
    from src.parser.canonical_id_resolver import normalize_so_hieu as canonicalize
    return canonicalize(so_hieu)


def remove_page_number(paragraphs: list[DoanVan]) -> list[DoanVan]:
    """Loại bỏ các đoạn chỉ chứa số trang (dòng chỉ có 1 số, đứng riêng)."""
    return [p for p in paragraphs if not PAGE_NUMBER_PATTERN.match(p.text)]


def remove_header_footer(paragraphs: list[DoanVan]) -> list[DoanVan]:
    """Loại bỏ các dòng quốc hiệu/tiêu ngữ lặp lại (không mang nội dung pháp lý)."""
    return [
        p for p in paragraphs
        if not any(pat.match(p.text) for pat in BOILERPLATE_PATTERNS)
    ]


def merge_broken_paragraph(paragraphs: list[DoanVan]) -> list[DoanVan]:
    """
    Nối các đoạn bị ngắt dòng giữa chừng (do xuống dòng cứng trong Word, không
    phải do hết câu/hết mục). Heuristic: nối đoạn HIỆN TẠI vào đoạn TRƯỚC nếu
    đoạn trước KHÔNG kết thúc bằng dấu câu kết ('.', ';', ':', '"', '”', ')')
    VÀ đoạn hiện tại KHÔNG bắt đầu bằng tiêu đề cấu trúc (Điều/Khoản/Điểm/Chương)
    hay chữ in đậm (dấu hiệu tiêu đề mới) — tránh nối nhầm 2 mục khác nhau.
    """
    KET_CAU = (".", ";", ":", '"', "”", ")", "”.", "”;")
    TIEU_DE_MOI = re.compile(r"^(Điều\s+\d|Chương\s+[IVXLCDM]|[a-zđ]\)|\d+[a-zđ]?\.\s)")

    if not paragraphs:
        return paragraphs

    result = [paragraphs[0]]
    for p in paragraphs[1:]:
        prev = result[-1]
        prev_ket_thuc_cau = prev.text.rstrip().endswith(KET_CAU)
        hien_tai_la_tieu_de_moi = bool(TIEU_DE_MOI.match(p.text)) or p.dam

        if not prev_ket_thuc_cau and not hien_tai_la_tieu_de_moi and not prev.dam:
            result[-1] = DoanVan(text=prev.text.rstrip() + " " + p.text.lstrip(), dam=prev.dam)
        else:
            result.append(p)

    return result


def normalize_paragraphs(paragraphs: list[DoanVan]) -> list[DoanVan]:
    """Pipeline chuẩn hóa đầy đủ: chuẩn hóa text -> bỏ số trang -> bỏ boilerplate -> nối đoạn bị ngắt."""
    paragraphs = [DoanVan(text=normalize_text(p.text), dam=p.dam) for p in paragraphs]
    paragraphs = remove_page_number(paragraphs)
    paragraphs = remove_header_footer(paragraphs)
    paragraphs = [p for p in paragraphs if p.text]
    paragraphs = merge_broken_paragraph(paragraphs)
    return paragraphs
