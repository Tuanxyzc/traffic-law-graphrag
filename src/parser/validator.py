"""
validator.py — Kiểm tra tính hợp lệ của dữ liệu sau khi parse.
Chỉ PHÁT HIỆN lỗi và ghi log/trả về danh sách cảnh báo — KHÔNG tự sửa dữ liệu.
"""

from src.parser.models import VanBan


def _all_dieu(van_ban: VanBan):
    result = list(van_ban.dieu_khong_chuong)
    for chuong in van_ban.chuong:
        result.extend(chuong.dieu)
    return result


def validate_article_number(van_ban: VanBan) -> list[str]:
    """Kiểm tra số Điều có liên tục không (phát hiện Điều bị bắt sót)."""
    warnings = []
    so_list = []
    for d in _all_dieu(van_ban):
        try:
            so_list.append(int("".join(c for c in d.so if c.isdigit())))
        except ValueError:
            continue
    if not so_list:
        return warnings
    missing = [n for n in range(min(so_list), max(so_list) + 1) if n not in so_list]
    if missing:
        warnings.append(
            f"[{van_ban.so_hieu}] Số Điều bị thiếu (không liên tục): {missing}"
        )
    return warnings


def validate_clause(van_ban: VanBan) -> list[str]:
    """Cảnh báo nếu 1 Điều có nhiều Khoản trùng số (dấu hiệu lẫn số cấp lồng — bug đã gặp)."""
    warnings = []
    for d in _all_dieu(van_ban):
        so_list = [k.so for k in d.khoan if k.so is not None]
        dup = {x for x in so_list if so_list.count(x) > 1}
        if dup:
            warnings.append(
                f"[{van_ban.so_hieu}] Điều {d.so}: Khoản bị TRÙNG số {dup} — kiểm tra lại có bị lẫn số lồng không"
            )
    return warnings


def validate_point(van_ban: VanBan) -> list[str]:
    warnings = []
    for d in _all_dieu(van_ban):
        for k in d.khoan:
            so_list = [p.so for p in k.diem]
            dup = {x for x in so_list if so_list.count(x) > 1}
            if dup:
                warnings.append(
                    f"[{van_ban.so_hieu}] Điều {d.so} Khoản {k.so}: Điểm bị TRÙNG số {dup}"
                )
    return warnings


def validate_duplicate(van_ban: VanBan) -> list[str]:
    """Kiểm tra trùng id ở mọi cấp (Điều/Khoản/Điểm)."""
    warnings = []
    ids = []
    for d in _all_dieu(van_ban):
        ids.append(d.id)
        for k in d.khoan:
            ids.append(k.id)
            ids.extend(p.id for p in k.diem)
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        warnings.append(f"[{van_ban.so_hieu}] TRÙNG id: {dup}")
    return warnings


def validate_reference(van_ban: VanBan, units) -> list[str]:
    """Cảnh báo nếu có tham chiếu 'văn bản này' nhưng so_hieu hiện tại rỗng
    (dấu hiệu quên truyền so_hieu khi build semantic unit)."""
    warnings = []
    for u in units:
        for tc in u.tham_chieu:
            if not tc.gia_tri_xac_dinh.so_hieu_van_ban:
                warnings.append(
                    f"[{u.id}] Tham chiếu '{tc.van_ban_goc}' không resolve được văn bản"
                )
    return warnings


def validate_missing_parent(van_ban: VanBan) -> list[str]:
    """Kiểm tra mọi id_cha có trỏ tới 1 node THẬT SỰ tồn tại trong cây không
    (phát hiện lỗi dựng cây — vd Khoản bị gán nhầm id_cha của Điều khác)."""
    warnings = []
    all_ids = {van_ban.so_hieu.replace("/", "_")}
    for c in van_ban.chuong:
        all_ids.add(c.id)
    for d in _all_dieu(van_ban):
        all_ids.add(d.id)
        for k in d.khoan:
            all_ids.add(k.id)
            for p in k.diem:
                all_ids.add(p.id)

    for c in van_ban.chuong:
        for d in c.dieu:
            if d.id_cha and d.id_cha not in all_ids:
                warnings.append(
                    f"[{van_ban.so_hieu}] Điều {d.id}: id_cha '{d.id_cha}' không tồn tại"
                )
    for d in _all_dieu(van_ban):
        for k in d.khoan:
            if k.id_cha not in all_ids:
                warnings.append(
                    f"[{van_ban.so_hieu}] Khoản {k.id}: id_cha '{k.id_cha}' không tồn tại"
                )
            for p in k.diem:
                if p.id_cha not in all_ids:
                    warnings.append(
                        f"[{van_ban.so_hieu}] Điểm {p.id}: id_cha '{p.id_cha}' không tồn tại"
                    )
    return warnings


def validate_duplicate_semantic_unit(units) -> list[str]:
    """Phát hiện 2 Semantic Unit có id KHÁC nhau nhưng nội dung chuẩn hóa
    GIỐNG HỆT nhau — dấu hiệu bị tách/nhân đôi dữ liệu (khác với validate_duplicate
    vốn chỉ kiểm tra trùng id)."""
    warnings = []
    seen: dict[str, str] = {}
    for u in units:
        key = u.noi_dung_chuan_hoa.strip()
        if not key:
            continue
        if key in seen and seen[key] != u.id:
            warnings.append(f"Semantic unit '{u.id}' trùng nội dung với '{seen[key]}'")
        else:
            seen[key] = u.id
    return warnings


def validate_invalid_reference(
    units, index_so_hieu_to_ids: dict[str, set[str]] | None
) -> list[str]:
    """
    Kiểm tra mỗi tham chiếu ĐÃ RESOLVE ra target_id có thật sự tồn tại không —
    cần index toàn cục (map so_hieu_van_ban -> set các id thật sự có), đọc từ
    các *_structure.json khác trong data/parsed/. Nếu index=None (văn bản kia
    chưa được parse), BỎ QUA kiểm tra này thay vì báo lỗi sai.
    """
    if index_so_hieu_to_ids is None:
        return []
    warnings = []
    for u in units:
        for tc in u.tham_chieu:
            vt = tc.gia_tri_xac_dinh
            tid = vt.target_id()
            if not tid or not vt.so_hieu_van_ban:
                continue
            known_ids = index_so_hieu_to_ids.get(vt.so_hieu_van_ban)
            if known_ids is not None and tid not in known_ids:
                warnings.append(
                    f"[{u.id}] Tham chiếu '{tc.van_ban_goc}' -> '{tid}' KHÔNG tồn tại trong {vt.so_hieu_van_ban}"
                )
    return warnings


def build_global_index(
    parsed_dir: str, exclude_so_hieu: str | None = None
) -> dict[str, set[str]]:
    """
    Quét mọi *_structure.json trong parsed_dir, dựng map so_hieu_van_ban -> set
    toàn bộ id (Điều/Khoản/Điểm) THẬT SỰ có — dùng cho validate_invalid_reference.
    Đọc trực tiếp id đã lưu sẵn trong file (không cần deserialize dataclass đầy đủ).
    """
    import json
    from pathlib import Path

    index: dict[str, set[str]] = {}
    for path in Path(parsed_dir).glob("*_structure.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        so_hieu = data.get("so_hieu")
        if not so_hieu or so_hieu == exclude_so_hieu:
            continue
        ids: set[str] = set()

        def _collect(dieu_list):
            for d in dieu_list:
                ids.add(d["id"])
                for k in d.get("khoan", []):
                    ids.add(k["id"])
                    for p in k.get("diem", []):
                        ids.add(p["id"])

        _collect(data.get("dieu_khong_chuong", []))
        for c in data.get("chuong", []):
            _collect(c.get("dieu", []))

        index[so_hieu] = ids
    return index


def validate(
    van_ban: VanBan, units=None, index_so_hieu_to_ids: dict[str, set[str]] | None = None
) -> list[str]:
    """Chạy toàn bộ validator, trả về danh sách cảnh báo gộp."""
    warnings = []
    warnings += validate_article_number(van_ban)
    warnings += validate_clause(van_ban)
    warnings += validate_point(van_ban)
    warnings += validate_duplicate(van_ban)
    warnings += validate_missing_parent(van_ban)
    if units is not None:
        warnings += validate_reference(van_ban, units)
        warnings += validate_duplicate_semantic_unit(units)
        warnings += validate_invalid_reference(units, index_so_hieu_to_ids)
    return warnings


def validate_amendment(events: list[dict]) -> list[str]:
    warnings = []
    for event in events:
        for item in event["items"]:
            for act in item.get("actions", []):
                op = act.get("operation")
                targets = act.get("targets", [])

                # Check duplicates
                t_units = [
                    t.get("target_unit") for t in targets if t.get("target_unit")
                ]
                dups = set([x for x in t_units if t_units.count(x) > 1])
                if dups:
                    warnings.append(
                        f"Validation Error: Duplicate targets found in action: {dups}"
                    )

                repl_paths = []
                for target in targets:
                    repl_path = target.get("replacement_path")
                    if repl_path:
                        repl_paths.append(str(repl_path))

                    if op == "BAI_BO" and repl_path is not None:
                        warnings.append(
                            f"Validation Error: BAI_BO cannot have a replacement path. Found: {repl_path}"
                        )
                    if op in ["SUA_DOI", "BO_SUNG", "THAY_THE"] and repl_path is None:
                        warnings.append(
                            f"Validation Error: {op} must have a valid replacement path mapped to a tree for target {target.get('target_unit')}"
                        )

                    # Check levels
                    if target.get("target_level") and target.get("replacement_level"):
                        if target["target_level"] != target["replacement_level"]:
                            warnings.append(
                                f"Validation Error: Target Level ({target['target_level']}) does not match Replacement Level ({target['replacement_level']})"
                            )

                # Replacement paths should be unique
                if op == "SUA_DOI":
                    path_dups = set([x for x in repl_paths if repl_paths.count(x) > 1])
                    if path_dups:
                        warnings.append(
                            f"Validation Error: Duplicate replacement paths found in SUA_DOI: {path_dups}"
                        )
    return warnings
