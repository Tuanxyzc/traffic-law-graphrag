"""
GIAI ĐOẠN 2 — AGGREGATOR
Với kiến trúc mới, việc "chunk theo Khoản/Điểm" đã được `semantic_unit.py`
làm ngay trong Giai đoạn 1 (mỗi Điều parse xong lập tức sinh Semantic Unit).
Module này CHỈ còn nhiệm vụ gom tất cả *_semantic_units.json trong data/parsed/
thành 1 file duy nhất, chuẩn bị cho Giai đoạn 3 (Embedding).

CÁCH DÙNG:
    python -m src.chunker
"""

import json
from pathlib import Path

from src.config import PARSED_DIR, VAN_BAN_SCOPE

SKIP_FILENAME_PATTERNS = ["_all_chunks.json"]

# Văn bản CHỈ đóng vai trò nguồn sửa đổi (omnibus, đã trích scope thủ công qua
# apply_amendments.py) -> không chunk trực tiếp, tránh trùng/nhiễu nội dung.
# Tự động suy ra từ VAN_BAN_SCOPE: văn bản nào có "pham_vi_ngoai_scope" = True.
EXCLUDE_SO_HIEU = {
    so_hieu for so_hieu, meta in VAN_BAN_SCOPE.items()
    if meta.get("pham_vi_ngoai_scope")
}


def load_all_units() -> list[dict]:
    """Quét toàn bộ data/parsed/*_semantic_units.json, gom + loại trùng id."""
    all_units = []
    seen_id = set()

    for path in sorted(Path(PARSED_DIR).glob("*_semantic_units.json")):
        if any(pat in path.name for pat in SKIP_FILENAME_PATTERNS):
            continue

        units = json.loads(path.read_text(encoding="utf-8"))
        for u in units:
            so_hieu = u["vi_tri"]["so_hieu_van_ban"]
            if so_hieu in EXCLUDE_SO_HIEU:
                continue
            if u["id"] in seen_id:
                print(f"⚠️  TRÙNG id '{u['id']}' (từ {path.name}) — kiểm tra lại có 2 file cùng chứa 1 đơn vị không")
                continue
            seen_id.add(u["id"])
            all_units.append(u)

    return all_units


def run():
    all_units = load_all_units()
    print(f"Tổng số semantic units nạp được: {len(all_units)}")

    by_van_ban = {}
    for u in all_units:
        so_hieu = u["vi_tri"]["so_hieu_van_ban"]
        by_van_ban.setdefault(so_hieu, 0)
        by_van_ban[so_hieu] += 1
    for so_hieu, count in by_van_ban.items():
        print(f"  - {so_hieu}: {count} units")

    out_path = Path(PARSED_DIR) / "_all_chunks.json"
    out_path.write_text(json.dumps(all_units, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã lưu -> {out_path}")
    return all_units


if __name__ == "__main__":
    run()
