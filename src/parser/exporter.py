"""
exporter.py — Xuất dữ liệu ra file, mỗi loại phục vụ 1 mục đích khác nhau:
    structure.json      -> dùng để nạp vào Neo4j (giữ nguyên cây phân cấp)
    semantic_units.json -> dùng cho Embedding/LLM/RAG (đơn vị phẳng, nhỏ nhất)
    metadata.json        -> thông tin cấp văn bản (tên, loại, ngày hiệu lực...)
"""

import json
from dataclasses import asdict
from pathlib import Path

from src.parser.canonical_id_resolver import normalize_so_hieu
from src.parser.models import DonViNguNghia, VanBan


def save_structure(
    van_ban: VanBan, output_dir: str, filename_override: str | None = None
):
    filename = (
        filename_override
        if filename_override
        else f"{van_ban.so_hieu.replace('/', '_')}_structure.json"
    )
    path = Path(output_dir) / filename
    path.write_text(
        json.dumps(asdict(van_ban), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def save_semantic_units(units: list[DonViNguNghia], so_hieu: str, output_dir: str):
    path = Path(output_dir) / f"{so_hieu.replace('/', '_')}_semantic_units.json"
    path.write_text(
        json.dumps([asdict(u) for u in units], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def save_metadata(
    van_ban: VanBan,
    output_dir: str,
    extra: dict | None = None,
    amendment_target_documents: list[str] | None = None,
):
    meta = {
        "so_hieu": normalize_so_hieu(van_ban.so_hieu),
        "ten": van_ban.ten,
        "loai": van_ban.loai,
        "ngay_ban_hanh": van_ban.ngay_ban_hanh,
        "co_quan_ban_hanh": van_ban.co_quan_ban_hanh,
        "trang_thai_hieu_luc": van_ban.trang_thai_hieu_luc,
        "so_chuong": len(van_ban.chuong),
        "so_dieu": len(van_ban.dieu_khong_chuong)
        + sum(len(c.dieu) for c in van_ban.chuong),
        "is_amendment": bool(amendment_target_documents),
        "amendment_target_documents": [
            normalize_so_hieu(x) for x in (amendment_target_documents or [])
        ],
    }
    if extra:
        meta.update(extra)
    path = Path(output_dir) / f"{van_ban.so_hieu.replace('/', '_')}_metadata.json"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_reference_index(units: list[DonViNguNghia], so_hieu: str, output_dir: str):
    """
    Xuất reference_index.json — CHỈ chứa quan hệ THAM CHIẾU thuần (THAM_CHIEU/
    CAN_CU_VAO/NGOAI_LE/DAN_CHIEU). KHÔNG chứa quan hệ sửa đổi (SUA_DOI/BO_SUNG/
    THAY_THE/BAI_BO/THEM_MOI) — các quan hệ đó thuộc amendment_index.json
    (xem save_amendment_index), vì bản chất khác nhau: tham chiếu là liên kết
    ngữ nghĩa tĩnh, sửa đổi là sự kiện thay đổi nội dung theo thời gian.
    """
    edges = []
    seen_edges: set[tuple[str, str, str]] = set()
    for u in units:
        for tc in u.tham_chieu:
            tid = tc.gia_tri_xac_dinh.target_id()
            if not tid:
                continue
            edge_key = (u.id, tid, tc.quan_he)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edges.append({"source": u.id, "target": tid, "relation": tc.quan_he})

    path = Path(output_dir) / f"{so_hieu.replace('/', '_')}_reference_index.json"
    path.write_text(json.dumps(edges, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_amendment_index(events: list[dict], so_hieu: str, output_dir: str):
    """
    Xuất amendment_index.json — MỖI VĂN BẢN 1 FILE RIÊNG trong thư mục con
    <output_dir>/<document_id>/amendment_index.json (theo đúng §10). Mỗi phần
    tử là 1 "Amendment Event" độc lập (source_document -SUA_DOI-> target_document),
    KHÔNG tính version, KHÔNG merge, KHÔNG suy luận thứ tự áp dụng — việc đó
    thuộc về Graph Builder (đọc toàn bộ các file này rồi tự sắp xếp theo
    effective_date lấy từ metadata.json).
    """
    doc_dir = Path(output_dir) / so_hieu.replace("/", "_")
    doc_dir.mkdir(exist_ok=True, parents=True)
    path = doc_dir / "amendment_index.json"
    path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
