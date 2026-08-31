"""
models.py — Định nghĩa cấu trúc dữ liệu dùng chung cho toàn bộ pipeline parser.

Dùng dataclass thay vì dict để có kiểm tra kiểu, IDE gợi ý thuộc tính, và
giảm lỗi gõ sai tên khóa (đã từng gặp nhiều lần khi thao tác dict thuần).
"""

from dataclasses import dataclass, field, asdict


# ---------- Cấu trúc phân cấp văn bản (Document -> Chapter -> Article -> Clause -> Point) ----------

@dataclass
class Diem:
    """Điểm (a, b, c...) — đơn vị nhỏ nhất."""
    id: str
    id_cha: str          # id của Khoản chứa Điểm này
    so: str               # "a", "b", "c"...
    noi_dung: str
    trang_thai: str = "hieu_luc"   # "hieu_luc" | "bai_bo"
    cap: int = 5           # level trong cây Document(1)->Chapter(2)->Article(3)->Clause(4)->Point(5)


@dataclass
class Khoan:
    """Khoản — chứa nhiều Điểm (có thể rỗng nếu Khoản không chia điểm)."""
    id: str
    id_cha: str          # id của Điều chứa Khoản này
    so: str | None         # "1", "2"... None nếu Điều không chia khoản
    noi_dung: str
    diem: list[Diem] = field(default_factory=list)
    hieu_luc_tu: str | None = None   # override ngày hiệu lực riêng (nếu khác văn bản sửa đổi)
    trang_thai: str = "hieu_luc"
    cap: int = 4


@dataclass
class Dieu:
    """Điều — chứa nhiều Khoản, thuộc về 1 Chương (có thể không thuộc Chương nào)."""
    id: str
    id_cha: str | None    # id của Chương chứa Điều này (None nếu văn bản không chia chương)
    so: str
    tieu_de: str
    so_hieu_van_ban: str    # văn bản mà Điều này thuộc về (khóa chuẩn hóa)
    noi_dung: str = ""      # toàn bộ văn bản của Điều (dùng để lưu trữ nếu không có khoản/điểm)
    khoan: list[Khoan] = field(default_factory=list)
    hieu_luc_tu: str | None = None
    sua_doi_boi_van_ban: str | None = None
    phien_ban: str = "goc"          # "goc" | "sua_doi_boi_<so_hieu>"
    trang_thai: str = "hieu_luc"
    cap: int = 3

    def __post_init__(self):
        if self.so_hieu_van_ban:
            from src.parser.normalize import normalize_so_hieu
            self.so_hieu_van_ban = normalize_so_hieu(self.so_hieu_van_ban)


@dataclass
class Chuong:
    """Chương — chứa nhiều Điều."""
    id: str
    so: str                # số La Mã: "I", "II"...
    tieu_de: str
    dieu: list[Dieu] = field(default_factory=list)
    cap: int = 2


@dataclass
class VanBan:
    """Toàn bộ 1 văn bản pháp luật sau khi parse."""
    so_hieu: str
    ten: str
    loai: str                       # "Luat" | "NghiDinh" | "Luat_gop" | ...
    ngay_ban_hanh: str | None = None
    co_quan_ban_hanh: str | None = None
    trang_thai_hieu_luc: str = "con_hieu_luc"   # "con_hieu_luc" | "het_hieu_luc"
    hieu_luc_tu: str | None = None
    chuong: list[Chuong] = field(default_factory=list)
    dieu_khong_chuong: list[Dieu] = field(default_factory=list)  # nếu văn bản không chia chương
    cap: int = 1

    def __post_init__(self):
        if self.so_hieu:
            from src.parser.normalize import normalize_so_hieu
            self.so_hieu = normalize_so_hieu(self.so_hieu)


# ---------- Cấu trúc cho hành vi sửa đổi (operation / target / reference) ----------

@dataclass
class ViTri:
    """Định danh một vị trí cụ thể trong văn bản pháp luật (để làm đích tham chiếu/sửa đổi)."""
    dieu: str | None = None
    khoan: str | None = None
    diem: str | None = None
    so_hieu_van_ban: str | None = None

    def __post_init__(self):
        # Normalize so_hieu_van_ban
        if self.so_hieu_van_ban:
            from src.parser.normalize import normalize_so_hieu
            self.so_hieu_van_ban = normalize_so_hieu(self.so_hieu_van_ban)

    def to_dict(self):
        return asdict(self)

    def target_id(self) -> str | None:
        """
        Sinh id ĐÍCH một cách xác định (deterministic) — KHÔNG cần biết đích có
        thật tồn tại hay không (việc đó là của validator.py, chạy sau, đọc index
        toàn cục). Chỉ cần đủ so_hieu_van_ban + dieu là sinh được id theo đúng
        quy ước đặt tên đã dùng xuyên suốt: <so_hieu>_D<dieu>[_K<khoan>[_D<diem>]]
        """
        if not self.so_hieu_van_ban or not self.dieu:
            return None
        base = f"{self.so_hieu_van_ban.replace('/', '_')}_D{self.dieu}"
        if self.khoan:
            base += f"_K{self.khoan}"
            if self.diem:
                base += f"_D{self.diem}"
        return base


def build_target_id(vi_tri: ViTri) -> str | None:
    """
    Sinh id đích DUY NHẤT theo đúng quy ước đã dùng xuyên suốt pipeline
    (vd '151_2024_ND-CP_D20_K5_Da'). Trả về None nếu chưa resolve được
    văn bản (so_hieu_van_ban rỗng) — nơi gọi PHẢI tự xử lý trường hợp None,
    không được giả định luôn có giá trị.
    """
    if not vi_tri.so_hieu_van_ban or not vi_tri.dieu:
        return None
    tid = f"{vi_tri.so_hieu_van_ban.replace('/', '_')}_D{vi_tri.dieu}"
    if vi_tri.khoan:
        tid += f"_K{vi_tri.khoan}"
    if vi_tri.diem:
        tid += f"_D{vi_tri.diem}"
    return tid


@dataclass
class ThamChieu:
    """1 tham chiếu được resolve trong nội dung (vd: 'Điều này' -> Điều 20)."""
    loai: str              # "dieu_nay" | "khoan_nay" | "diem_nay" | "van_ban_nay" | "tuyet_doi" | "cheo_van_ban"
    van_ban_goc: str         # cụm từ gốc trong text, vd "Điều này"
    gia_tri_xac_dinh: ViTri   # kết quả sau khi resolve
    quan_he: str = "THAM_CHIEU"   # THAM_CHIEU | CAN_CU_VAO | NGOAI_LE — dùng làm loại cạnh khi import Neo4j


@dataclass
class DonViNguNghia:
    """
    Semantic Unit — đơn vị nhỏ nhất đưa vào LLM/RAG.
    Mỗi Khoản hoặc Điểm (hoặc cả Điều, nếu bổ sung/bãi bỏ toàn bộ) tương ứng 1 unit.
    """
    id: str
    vi_tri: ViTri                      # vị trí CỦA chính unit này
    hanh_dong: str                      # "GIU_NGUYEN" | "SUA_DOI" | "BO_SUNG" | "BAI_BO" | "THAY_THE"
    level: int = 4                       # 0=VanBan,1=Chuong,2=Dieu,3=Khoan,4=Diem — dùng cho Neo4j/validator
    doi_tuong: list[ViTri] = field(default_factory=list)  # vị trí ĐÍCH bị tác động (dùng cho THAY_THE/BAI_BO nhiều vị trí)
    tham_chieu: list[ThamChieu] = field(default_factory=list)
    noi_dung_goc: str = ""              # nguyên văn, CHƯA thay "Điều này"/"khoản này"...
    noi_dung_chuan_hoa: str = ""        # đã thay thế mọi tham chiếu tương đối bằng số tuyệt đối
    noi_dung: str = ""                  # giữ để tương thích ngược (= noi_dung_chuan_hoa)
    hieu_luc_tu: str | None = None
    tieu_de_dieu: str = ""
    chuong: str | None = None
    tieu_de_chuong: str | None = None
    phien_ban: str = "goc"
    sua_doi_boi_van_ban: str | None = None


def van_ban_to_dict(van_ban: VanBan) -> dict:
    """Serialize VanBan (và toàn bộ cây con) sang dict thuần để json.dumps."""
    return asdict(van_ban)


def don_vi_list_to_dict(units: list[DonViNguNghia]) -> list[dict]:
    return [asdict(u) for u in units]


# ---------- Deserialize: dict thuần (từ json.load) -> dataclass ----------
# Cần thiết vì json.load() không tự khôi phục dataclass, chỉ trả về dict/list thô.

def diem_from_dict(d: dict) -> Diem:
    return Diem(**d)


def khoan_from_dict(d: dict) -> Khoan:
    dd = dict(d)
    dd["diem"] = [diem_from_dict(x) for x in d.get("diem", [])]
    return Khoan(**dd)


def dieu_from_dict(d: dict) -> Dieu:
    dd = dict(d)
    dd["khoan"] = [khoan_from_dict(x) for x in d.get("khoan", [])]
    return Dieu(**dd)


def chuong_from_dict(d: dict) -> Chuong:
    dd = dict(d)
    dd["dieu"] = [dieu_from_dict(x) for x in d.get("dieu", [])]
    return Chuong(**dd)


def van_ban_from_dict(d: dict) -> VanBan:
    return VanBan(
        so_hieu=d["so_hieu"],
        ten=d.get("ten", ""),
        loai=d.get("loai", ""),
        ngay_ban_hanh=d.get("ngay_ban_hanh"),
        co_quan_ban_hanh=d.get("co_quan_ban_hanh"),
        trang_thai_hieu_luc=d.get("trang_thai_hieu_luc", "con_hieu_luc"),
        hieu_luc_tu=d.get("hieu_luc_tu"),
        chuong=[chuong_from_dict(x) for x in d.get("chuong", [])],
        dieu_khong_chuong=[dieu_from_dict(x) for x in d.get("dieu_khong_chuong", [])],
    )


def van_ban_from_old_flat_list(data: list[dict], so_hieu: str, ten: str = "", loai: str = "") -> VanBan:
    """
    Chuyển đổi schema CŨ (list dict phẳng: mỗi phần tử = 1 Điều với
    dieu_id/dieu/tieu_de/chuong/khoan_list...) sang VanBan (dataclass mới).
    Dùng 1 lần cho các file JSON đã parse từ trước bằng bản parser cũ.
    """
    van_ban = VanBan(so_hieu=so_hieu, ten=ten, loai=loai)
    chuong_map: dict[str, Chuong] = {}

    for d in data:
        dieu_id = d["dieu_id"]
        khoan_list = []
        for k in d.get("khoan_list", []):
            khoan_id = f"{dieu_id}_K{k.get('khoan') or '0'}"
            diem_list = [
                Diem(
                    id=p.get("diem_id", f"{khoan_id}_D{p['diem']}"),
                    id_cha=khoan_id,
                    so=p["diem"],
                    noi_dung=p["noi_dung"],
                )
                for p in k.get("diem_list", [])
            ]
            khoan_list.append(Khoan(
                id=khoan_id, id_cha=dieu_id, so=k.get("khoan"),
                noi_dung=k["noi_dung"], diem=diem_list,
                hieu_luc_tu=k.get("hieu_luc_tu"),
                trang_thai=k.get("trang_thai", "hieu_luc"),
            ))

        chuong_so = d.get("chuong")
        dieu = Dieu(
            id=dieu_id,
            id_cha=None,
            so=d["dieu"],
            tieu_de=d["tieu_de"],
            so_hieu_van_ban=d.get("so_hieu_van_ban", so_hieu),
            khoan=khoan_list,
            hieu_luc_tu=d.get("hieu_luc_tu"),
            sua_doi_boi_van_ban=d.get("sua_doi_boi_van_ban"),
            phien_ban=d.get("phien_ban", "goc"),
            trang_thai=d.get("trang_thai", "hieu_luc"),
        )

        if chuong_so:
            if chuong_so not in chuong_map:
                chuong_map[chuong_so] = Chuong(
                    id=f"{so_hieu.replace('/', '_')}_C{chuong_so}",
                    so=chuong_so, tieu_de=d.get("tieu_de_chuong", ""),
                )
                van_ban.chuong.append(chuong_map[chuong_so])
            dieu.id_cha = chuong_map[chuong_so].id
            chuong_map[chuong_so].dieu.append(dieu)
        else:
            van_ban.dieu_khong_chuong.append(dieu)

    return van_ban
