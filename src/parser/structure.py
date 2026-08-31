"""
structure.py — Parser chính: tách văn bản thành cây Chương -> Điều -> Khoản -> Điểm.

QUAN TRỌNG: module này CHỈ tách Điều CẤP 1 của chính văn bản đang đọc — không
cố đệ quy vào nội dung trích dẫn/lồng bên trong (vd: nội dung Điều X của Luật
khác bị trích dẫn trong ngoặc kép khi văn bản này sửa đổi Luật đó). Việc diễn
giải "bên trong nội dung có Điều/Khoản gì" là việc của operation.py +
reference.py, dựa trên `content` (text thô) mà structure.py trả về — tránh
hẳn bug trộn số cấp 1 với số lồng bên trong (đã gặp nhiều lần).

Nếu cần tách sâu vào 1 khối content cụ thể (vd nội dung 1 Điều hoàn toàn mới
được trích dẫn để bổ sung), dùng hàm `parse_content_block()` — hàm này an toàn
để gọi vì nó chỉ nhận 1 đoạn text đã được cô lập rõ ràng, không có nguy cơ lẫn
số với cấp 1.
"""

import re

from src.parser.models import Chuong, Diem, Dieu, Khoan, VanBan
from src.parser.normalize import DoanVan

DIEU_TITLE_PATTERN = re.compile(r"^Điều\s+(\d+[a-zđ]?)\.\s*(.*)$")
KHOAN_PATTERN = re.compile(r"^\s*(\d+[a-zđ]?)\.\s+(.+)$")
DIEM_PATTERN = re.compile(r"^\s*([a-zđ]\d*)\)\s+(.+)$")
CHUONG_PATTERN = re.compile(r"^Chương\s+([IVXLCDM]+)\b", re.IGNORECASE)

STRUCTURAL_QUOTE_PATTERN = re.compile(r'([“"])(Điều \d+|[1-9]\d*\.|[a-zđ]\d*\))')
AMENDMENT_INSTRUCTION_PATTERN = re.compile(
    r"^\s*\d+[a-zđ]?\.\s+(?:Sửa đổi|Bổ sung|Thay thế|Bãi bỏ|Bỏ|Thêm mới)\b",
    re.IGNORECASE,
)


def find_replacement_quote_start(text: str) -> int:
    """Tách ranh giới giữa Tiêu đề (Instruction) và Nội dung thay thế (Replacement Block)"""
    m = STRUCTURAL_QUOTE_PATTERN.search(text)
    if m:
        return m.start()

    m2 = re.search(r'như sau:\s*([“"])', text, re.IGNORECASE)
    if m2:
        return m2.start(1)

    return -1


def normalize_diem_breaks(text: str) -> str:
    """Chèn xuống dòng trước mỗi điểm a)/b)/c)... nếu bị viết liền thành đoạn
    văn xuôi (thường do nội dung được trích dẫn/transcribe không giữ format
    xuống dòng gốc). Chỉ chèn khi điểm đứng ngay sau ':' hoặc ';' + khoảng trắng."""
    return re.sub(r"(?<=[:;]\s)([a-zđ]\))", r"\n\1", text)


def parse_diem_list(
    text: str,
    id_cha: str,
    initial_quote_balance: int = 0,
    initial_straight_quote: bool = False,
) -> list[Diem]:
    """Tách 1 đoạn text thành danh sách Điểm (a, b, c...). Rỗng nếu không có."""
    text = normalize_diem_breaks(text)
    lines = text.splitlines()
    result = []
    current_diem_so = None
    current_noi_dung = []
    quote_balance = initial_quote_balance
    inside_straight_quote = initial_straight_quote

    def flush_diem():
        if current_diem_so:
            result.append(
                Diem(
                    id=f"{id_cha}_D{current_diem_so}",
                    id_cha=id_cha,
                    so=current_diem_so,
                    noi_dung="\n".join(current_noi_dung).strip(),
                )
            )

    for line in lines:
        is_inside_quote = (
            quote_balance > 0
            or inside_straight_quote
            or line.lstrip().startswith("“")
            or line.lstrip().startswith('"')
        )

        m = DIEM_PATTERN.match(line)
        # A malformed inline quote in one amendment instruction must not hide
        # later numbered instructions. Explicit legislative-operation headings
        # remain structural boundaries even while quote state is unbalanced.
        is_amendment_instruction = bool(AMENDMENT_INSTRUCTION_PATTERN.match(line))
        if m and (not is_inside_quote or is_amendment_instruction):
            flush_diem()
            current_diem_so = m.group(1)
            current_noi_dung = [line]
        else:
            if current_diem_so:
                current_noi_dung.append(line)

        quote_balance += line.count("“") - line.count("”")
        quote_balance = max(quote_balance, 0)
        if line.count('"') % 2 != 0:
            inside_straight_quote = not inside_straight_quote

    flush_diem()
    return result


def parse_khoan_list(
    text: str,
    id_cha: str,
    initial_quote_balance: int = 0,
    initial_straight_quote: bool = False,
) -> list[Khoan]:
    """Tách 1 đoạn text (nội dung 1 Điều) thành danh sách Khoản, mỗi Khoản
    tách tiếp thành Điểm nếu có."""
    lines = text.splitlines()
    result = []
    current_khoan_so = None
    current_noi_dung = []
    quote_balance = initial_quote_balance
    inside_straight_quote = initial_straight_quote

    def flush_khoan():
        if current_noi_dung and current_khoan_so:
            khoan_id = f"{id_cha}_K{current_khoan_so}"
            nd = "\n".join(current_noi_dung).strip()
            result.append(
                Khoan(
                    id=khoan_id,
                    id_cha=id_cha,
                    so=current_khoan_so,
                    noi_dung=nd,
                    diem=parse_diem_list(nd, khoan_id),
                )
            )

    for line in lines:
        is_inside_quote = (
            quote_balance > 0
            or inside_straight_quote
            or line.lstrip().startswith("“")
            or line.lstrip().startswith('"')
        )

        m = KHOAN_PATTERN.match(line)
        is_amendment_instruction = bool(AMENDMENT_INSTRUCTION_PATTERN.match(line))
        if m and (not is_inside_quote or is_amendment_instruction):
            flush_khoan()
            current_khoan_so = m.group(1)
            current_noi_dung = [line]
        else:
            if current_khoan_so:
                current_noi_dung.append(line)

        quote_balance += line.count("“") - line.count("”")
        quote_balance = max(quote_balance, 0)
        if line.count('"') % 2 != 0:
            inside_straight_quote = not inside_straight_quote

    flush_khoan()
    return result


def parse_content_block(text: str, id_cha: str) -> list[Khoan]:
    """
    Parse AN TOÀN 1 khối content bị cô lập rõ ràng (vd nội dung 1 Điều mới
    trích dẫn để bổ sung) thành Khoản/Điểm. Dùng khi operation.py/reference.py
    đã xác định chắc chắn ranh giới của khối này, KHÔNG dùng trực tiếp trên
    toàn văn bản (dễ lẫn số với cấp 1).
    """
    khoan_list = parse_khoan_list(text, id_cha)
    return khoan_list


def parse_document(
    paragraphs: list[DoanVan], so_hieu: str, ten: str = "", loai: str = ""
) -> VanBan:
    """
    Tách toàn bộ văn bản thành cây Chương -> Điều -> Khoản -> Điểm.
    Điều kiện nhận diện 1 Điều CẤP 1: đoạn văn khớp regex "Điều X." VÀ in đậm.
    """
    van_ban = VanBan(so_hieu=so_hieu, ten=ten, loai=loai)

    SECTION_DOCUMENT_BODY = "DOCUMENT_BODY"
    SECTION_APPENDIX = "APPENDIX_SECTION"
    SECTION_SIGNATURE = "SIGNATURE_SECTION"
    SECTION_RECIPIENT = "RECIPIENT_SECTION"

    import re

    APPENDIX_HEADING = re.compile(r"^(?:PHỤ\s+LỤC|Phụ\s+lục)[\sIIVX0-9A-Z]*\b")
    SIGNATURE_HEADING = re.compile(r"^(?:TM\.\s+CHÍNH\s+PHỦ|KT\.\s+BỘ\s+TRƯỞNG)\b")
    RECIPIENT_HEADING = re.compile(r"^Nơi\s+nhận:")

    section_state = SECTION_DOCUMENT_BODY

    current_chuong: Chuong | None = None
    current_dieu_so = None
    current_dieu_tieu_de = None
    current_dieu_noi_dung = ""
    waiting_chuong_title = False
    quote_balance = (
        0  # >0 = đang ở trong khối "..." — KHÔNG coi là ranh giới Điều cấp 1
    )
    inside_straight_quote = False

    def flush_dieu():
        nonlocal current_dieu_so, current_dieu_noi_dung, current_dieu_tieu_de
        if current_dieu_so is None:
            return
        id_cha_chuong = current_chuong.id if current_chuong else None
        dieu_id = f"{so_hieu.replace('/', '_')}_D{current_dieu_so}"

        # Calculate quote boundary inherited from title
        d_title = current_dieu_tieu_de or ""
        t_quote_bal = max(0, d_title.count("“") - d_title.count("”"))
        t_straight_quote = d_title.count('"') % 2 != 0

        nd_clean = current_dieu_noi_dung.strip()

        dieu = Dieu(
            id=dieu_id,
            id_cha=id_cha_chuong,
            so=current_dieu_so,
            tieu_de=d_title,
            so_hieu_van_ban=so_hieu,
            noi_dung=nd_clean,
            khoan=parse_khoan_list(nd_clean, dieu_id, t_quote_bal, t_straight_quote),
        )
        if current_chuong:
            current_chuong.dieu.append(dieu)
        else:
            van_ban.dieu_khong_chuong.append(dieu)
        current_dieu_so = None
        current_dieu_noi_dung = ""
        current_dieu_tieu_de = None

    for p in paragraphs:
        text = p.text

        # Đang ở trong khối ngoặc kép (từ đoạn trước) HOẶC chính đoạn này tự mở
        # ngoặc kép -> không được coi là ranh giới Chương/Điều cấp 1, dù có bold
        # và khớp regex — đây là nội dung trích dẫn/lồng bên trong, không phải
        # cấu trúc thật của chính văn bản đang parse.
        is_inside_quote = (
            (quote_balance > 0)
            or inside_straight_quote
            or text.startswith("“")
            or text.startswith('"')
        )

        chuong_match = CHUONG_PATTERN.match(text)
        if chuong_match and not is_inside_quote:
            flush_dieu()
            chuong_id = f"{so_hieu.replace('/', '_')}_C{chuong_match.group(1)}"
            current_chuong = Chuong(id=chuong_id, so=chuong_match.group(1), tieu_de="")
            van_ban.chuong.append(current_chuong)
            waiting_chuong_title = True
            quote_balance += text.count("“") - text.count("”")
            quote_balance = max(quote_balance, 0)
            if text.count('"') % 2 != 0:
                inside_straight_quote = not inside_straight_quote
            continue

        if waiting_chuong_title and not is_inside_quote:
            current_chuong.tieu_de = text
            waiting_chuong_title = False
            quote_balance += text.count("“") - text.count("”")
            quote_balance = max(quote_balance, 0)
            if text.count('"') % 2 != 0:
                inside_straight_quote = not inside_straight_quote
            continue

        if (
            APPENDIX_HEADING.match(text.strip())
            and section_state == SECTION_DOCUMENT_BODY
        ):
            flush_dieu()
            section_state = SECTION_APPENDIX
        elif (
            SIGNATURE_HEADING.match(text.strip())
            and section_state == SECTION_DOCUMENT_BODY
        ):
            flush_dieu()
            section_state = SECTION_SIGNATURE
        elif (
            RECIPIENT_HEADING.match(text.strip())
            and section_state == SECTION_DOCUMENT_BODY
        ):
            flush_dieu()
            section_state = SECTION_RECIPIENT

        dieu_match = DIEU_TITLE_PATTERN.match(text)
        if (
            dieu_match
            and p.dam
            and not is_inside_quote
            and section_state == SECTION_DOCUMENT_BODY
        ):
            flush_dieu()
            current_dieu_so = dieu_match.group(1)
            raw_title = dieu_match.group(2)

            quote_idx = find_replacement_quote_start(raw_title)
            if quote_idx != -1:
                current_dieu_tieu_de = raw_title[:quote_idx].strip()
                current_dieu_noi_dung = raw_title[quote_idx:] + "\n"
            else:
                current_dieu_tieu_de = raw_title.strip()
                current_dieu_noi_dung = ""

            quote_balance += text.count("“") - text.count("”")
            quote_balance = max(quote_balance, 0)
            if text.count('"') % 2 != 0:
                inside_straight_quote = not inside_straight_quote
            continue

        if current_dieu_so is not None:
            current_dieu_noi_dung += text + "\n"

        quote_balance += text.count("“") - text.count("”")
        quote_balance = max(quote_balance, 0)
        if text.count('"') % 2 != 0:
            inside_straight_quote = not inside_straight_quote

    flush_dieu()
    return van_ban
