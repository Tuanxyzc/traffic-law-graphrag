"""
semantic_unit.py — Chuyển cây cấu trúc (VanBan) thành danh sách Semantic Unit
phẳng — đơn vị nhỏ nhất, sẵn sàng đưa vào Embedding/LLM/RAG.

Mỗi Khoản (hoặc Điểm, nếu văn bản loại cần chunk theo Điểm) tương ứng 1 unit.

QUAN TRỌNG: với văn bản dạng "sửa đổi CHUYÊN BIỆT 1 văn bản khác" (vd 236/2026,
238/2026), chỉ dẫn sửa đổi ("Sửa đổi, bổ sung khoản X Điều Y") thường nằm ở
TIÊU ĐỀ ĐIỀU, còn nội dung Khoản/Điểm chỉ là đoạn text MỚI được trích dẫn (bản
thân nó thường KHÔNG chứa từ khóa "sửa đổi"). Vì vậy operation/target được dò
ở TIÊU ĐỀ ĐIỀU trước; nếu có, mọi Khoản/Điểm bên trong Điều đó KẾ THỪA cùng
hanh_dong + doi_tuong (đích chính là chỉ dẫn tại tiêu đề); nếu tiêu đề không
cho ra operation nào (Điều nội dung bình thường), mới dò tiếp trong chính nội
dung Khoản/Điểm như trước.
"""

from src.parser.models import VanBan, Chuong, Dieu, Khoan, Diem, DonViNguNghia, ViTri
from src.parser import operation, reference
from src.config import AMENDMENT_ARTICLE_TARGETS

CHUNK_BY_DIEM_LOAI = {"NghiDinh", "NghiDinh_suaDoi"}


def _dien_so_hieu_cho_doi_tuong(doi_tuong: list[ViTri], mac_dinh: str | None) -> list[ViTri]:
    """Điền so_hieu_van_ban mặc định vào các ViTri đích chưa có (chỉ đích nào
    KHÔNG tự nêu rõ văn bản mới dùng mặc định — không ghi đè nếu đã tự xác định)."""
    if not mac_dinh:
        return doi_tuong
    return [
        v if v.so_hieu_van_ban else ViTri(dieu=v.dieu, khoan=v.khoan, diem=v.diem, so_hieu_van_ban=mac_dinh)
        for v in doi_tuong
    ]


def _chuan_hoa_noi_dung(text: str, tham_chieu: list) -> str:
    RELATIVE_LOAI = {"dieu_nay", "khoan_nay", "diem_nay"}
    ket_qua = text
    for tc in tham_chieu:
        if tc.loai not in RELATIVE_LOAI:
            continue
        vt = tc.gia_tri_xac_dinh
        if tc.loai == "dieu_nay" and vt.dieu:
            thay = f"Điều {vt.dieu}"
        elif tc.loai == "khoan_nay" and vt.khoan:
            thay = f"Khoản {vt.khoan}"
        elif tc.loai == "diem_nay" and vt.diem:
            thay = f"Điểm {vt.diem}"
        else:
            continue
        ket_qua = ket_qua.replace(tc.van_ban_goc, thay)
    return ket_qua


def merge_vitri_child_parent(child: ViTri, parent: ViTri) -> ViTri:
    from copy import deepcopy
    res = deepcopy(child)
    if not res.dieu and parent.dieu: res.dieu = parent.dieu
    if not res.khoan and parent.khoan: res.khoan = parent.khoan
    if not res.diem and parent.diem: res.diem = parent.diem
    if not res.so_hieu_van_ban and parent.so_hieu_van_ban: res.so_hieu_van_ban = parent.so_hieu_van_ban
    return res

def _build_unit(vi_tri: ViTri, id_: str, level: int, hanh_dong_dieu: str | None,
                 doi_tuong_dieu: list[ViTri], noi_dung_rieng: str,
                 noi_dung_day_du: str, dieu: Dieu, khoan: Khoan | None,
                 chuong: Chuong | None, so_hieu: str, target_mac_dinh: str | None) -> DonViNguNghia:
    """Hàm dùng chung cho cả build unit cấp Khoản và cấp Điểm."""
    # Extract only the instruction part (before the first quote) to avoid detecting targets in the replacement content
    instruction = ""
    # Check if we are already inside a quote inherited from the title
    is_inherited_quote = False
    if level == 2 and dieu and dieu.tieu_de:
        t_quote_bal = max(0, dieu.tieu_de.count("“") - dieu.tieu_de.count("”"))
        t_straight_quote = (dieu.tieu_de.count('"') % 2 != 0)
        if t_quote_bal > 0 or t_straight_quote:
            is_inherited_quote = True
            
    if not is_inherited_quote:
        quote_start = -1
        for i, c in enumerate(noi_dung_rieng):
            if c in ('“', '"'):
                quote_start = i
                break
                
        if quote_start != -1:
            instruction = noi_dung_rieng[:quote_start]
        else:
            instruction = noi_dung_rieng
            
    # Dò operation/target TRONG NỘI DUNG RIÊNG (của Khoản/Điểm)
    hanh_dong_rieng = operation.detect_operation(instruction)
    doi_tuong_rieng = operation.detect_target(instruction) if hanh_dong_rieng else []
    
    hanh_dong = hanh_dong_rieng or hanh_dong_dieu or "GIU_NGUYEN"
    
    if doi_tuong_rieng:
        if doi_tuong_dieu:
            base_target = doi_tuong_dieu[0]
            doi_tuong = [merge_vitri_child_parent(t, base_target) for t in doi_tuong_rieng]
        else:
            doi_tuong = doi_tuong_rieng
    else:
        doi_tuong = doi_tuong_dieu if hanh_dong_dieu else []
        
    doi_tuong = _dien_so_hieu_cho_doi_tuong(doi_tuong, target_mac_dinh)

    # Nội dung nằm sau chỉ dẫn sửa đổi là nội dung của văn bản ĐÍCH. Các cụm
    # tương đối như "Điều này", "khoản này" vì vậy phải được resolve trong
    # ngữ cảnh đích, không phải Điều của văn bản sửa đổi đang chứa đoạn trích.
    reference_vi_tri = vi_tri
    reference_so_hieu = so_hieu
    if hanh_dong != "GIU_NGUYEN" and doi_tuong:
        target = doi_tuong[0]
        reference_vi_tri = ViTri(
            dieu=target.dieu or vi_tri.dieu,
            khoan=target.khoan,
            diem=target.diem,
            so_hieu_van_ban=target.so_hieu_van_ban or so_hieu,
        )
        reference_so_hieu = reference_vi_tri.so_hieu_van_ban

    tham_chieu = reference.resolve_references(
        noi_dung_rieng, reference_vi_tri, reference_so_hieu
    )
    noi_dung_chuan_hoa = _chuan_hoa_noi_dung(noi_dung_day_du, tham_chieu)

    return DonViNguNghia(
        id=id_, vi_tri=vi_tri, hanh_dong=hanh_dong, level=level,
        doi_tuong=doi_tuong, tham_chieu=tham_chieu,
        noi_dung_goc=noi_dung_day_du, noi_dung_chuan_hoa=noi_dung_chuan_hoa,
        noi_dung=noi_dung_chuan_hoa,
        hieu_luc_tu=(khoan.hieu_luc_tu if khoan else None) or dieu.hieu_luc_tu,
        tieu_de_dieu=dieu.tieu_de,
        chuong=chuong.so if chuong else None,
        tieu_de_chuong=chuong.tieu_de if chuong else None,
        phien_ban=dieu.phien_ban,
        sua_doi_boi_van_ban=dieu.sua_doi_boi_van_ban,
    )


def build_for_dieu_list(dieu_list: list[Dieu], so_hieu: str, loai: str,
                          chuong: Chuong | None = None,
                          target_so_hieu_mac_dinh: str | None = None) -> list[DonViNguNghia]:
    """Sinh Semantic Unit từ 1 danh sách Điều rời."""
    units: list[DonViNguNghia] = []
    chunk_by_diem = loai in CHUNK_BY_DIEM_LOAI

    for dieu in dieu_list:
        article_target_default = AMENDMENT_ARTICLE_TARGETS.get(so_hieu, {}).get(
            dieu.so, target_so_hieu_mac_dinh
        )
        if dieu.trang_thai == "bai_bo":
            noi_dung = f"Điều {dieu.so} ({dieu.tieu_de}) ĐÃ BỊ BÃI BỎ bởi {dieu.sua_doi_boi_van_ban}."
            units.append(DonViNguNghia(
                id=f"{dieu.id}_BAIBO", vi_tri=ViTri(dieu=dieu.so, so_hieu_van_ban=so_hieu),
                hanh_dong="BAI_BO", level=2,
                noi_dung_goc=noi_dung, noi_dung_chuan_hoa=noi_dung, noi_dung=noi_dung,
                hieu_luc_tu=dieu.hieu_luc_tu, tieu_de_dieu=dieu.tieu_de,
                phien_ban=dieu.phien_ban, sua_doi_boi_van_ban=dieu.sua_doi_boi_van_ban,
            ))
            continue

        # Dò operation/target Ở TIÊU ĐỀ ĐIỀU trước (chỉ dẫn sửa đổi văn bản khác)
        vi_tri_dieu = ViTri(dieu=dieu.so, so_hieu_van_ban=so_hieu)
        hanh_dong_dieu = operation.detect_operation(dieu.tieu_de or "")
        doi_tuong_dieu = operation.detect_target(dieu.tieu_de or "") if hanh_dong_dieu else []

        if not dieu.khoan:
            noi_dung_day_du = f"Điều {dieu.so}. {dieu.tieu_de}\n{dieu.noi_dung}".strip()
            units.append(_build_unit(
                vi_tri_dieu, dieu.id, 2, hanh_dong_dieu, doi_tuong_dieu,
                dieu.noi_dung, noi_dung_day_du, dieu, None, chuong, so_hieu, article_target_default,
            ))
            continue

        for khoan in dieu.khoan:
            if khoan.trang_thai == "bai_bo":
                noi_dung = f"Khoản {khoan.so} Điều {dieu.so} ĐÃ BỊ BÃI BỎ bởi {dieu.sua_doi_boi_van_ban}."
                units.append(DonViNguNghia(
                    id=f"{khoan.id}_BAIBO",
                    vi_tri=ViTri(dieu=dieu.so, khoan=khoan.so, so_hieu_van_ban=so_hieu),
                    hanh_dong="BAI_BO", level=3,
                    noi_dung_goc=noi_dung, noi_dung_chuan_hoa=noi_dung, noi_dung=noi_dung,
                    hieu_luc_tu=khoan.hieu_luc_tu or dieu.hieu_luc_tu, tieu_de_dieu=dieu.tieu_de,
                    phien_ban=dieu.phien_ban, sua_doi_boi_van_ban=dieu.sua_doi_boi_van_ban,
                ))
                continue

            if chunk_by_diem and khoan.diem:
                clause_instruction = khoan.noi_dung.splitlines()[0] if khoan.noi_dung else ""
                hanh_dong_khoan = operation.detect_operation(clause_instruction)
                doi_tuong_khoan = operation.detect_target(clause_instruction) if hanh_dong_khoan else []
                if doi_tuong_khoan and doi_tuong_dieu:
                    doi_tuong_khoan = [
                        merge_vitri_child_parent(target, doi_tuong_dieu[0])
                        for target in doi_tuong_khoan
                    ]
                inherited_action = hanh_dong_khoan or hanh_dong_dieu
                inherited_targets = doi_tuong_khoan or doi_tuong_dieu
                for diem in khoan.diem:
                    vi_tri = ViTri(dieu=dieu.so, khoan=khoan.so, diem=diem.so, so_hieu_van_ban=so_hieu)
                    noi_dung_day_du = f"Điều {dieu.so}. {dieu.tieu_de}\nKhoản {khoan.so}: {khoan.noi_dung.splitlines()[0]}\n{diem.noi_dung}"
                    units.append(_build_unit(
                        vi_tri, diem.id, 4, inherited_action, inherited_targets,
                        diem.noi_dung, noi_dung_day_du, dieu, khoan, chuong, so_hieu, article_target_default,
                    ))
            else:
                vi_tri = ViTri(dieu=dieu.so, khoan=khoan.so, so_hieu_van_ban=so_hieu)
                noi_dung_day_du = f"Điều {dieu.so}. {dieu.tieu_de}\n{khoan.noi_dung}"
                units.append(_build_unit(
                    vi_tri, khoan.id, 3, hanh_dong_dieu, doi_tuong_dieu,
                    khoan.noi_dung, noi_dung_day_du, dieu, khoan, chuong, so_hieu, article_target_default,
                ))

    return units


def build(van_ban: VanBan, target_so_hieu_mac_dinh: str | None = None) -> list[DonViNguNghia]:
    """Duyệt toàn bộ cây VanBan, sinh danh sách Semantic Unit phẳng."""
    units: list[DonViNguNghia] = []
    units.extend(build_for_dieu_list(van_ban.dieu_khong_chuong, van_ban.so_hieu, van_ban.loai,
                                      chuong=None, target_so_hieu_mac_dinh=target_so_hieu_mac_dinh))
    for chuong in van_ban.chuong:
        units.extend(build_for_dieu_list(chuong.dieu, van_ban.so_hieu, van_ban.loai,
                                          chuong=chuong, target_so_hieu_mac_dinh=target_so_hieu_mac_dinh))
    return units
