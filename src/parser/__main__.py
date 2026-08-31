"""
__main__.py — Orchestrator. CHỈ gọi các module theo đúng thứ tự, không chứa
regex/logic parser/logic resolve/logic detect operation (toàn bộ nằm ở các
module con). Cho phép chạy bằng: python -m src.parser

Luồng xử lý:
    normalize.load_docx()
        -> normalize.normalize_paragraphs()
        -> structure.parse_document()
        -> semantic_unit.build()   (bên trong tự gọi operation.py + reference.py)
        -> validator.validate()
        -> exporter.save_*()
"""

import sys
from pathlib import Path

from src.config import (
    AMENDMENT_TARGET_FALLBACK,
    DOCUMENT_REGISTRY,
    FILE_SO_HIEU_MAP,
    PARSED_DIR,
    RAW_DIR,
    VAN_BAN_SCOPE,
)
from src.parser import (
    amendment_recorder,
    corpus_audit,
    corpus_postprocessor,
    exporter,
    metadata_versioning,
    normalize,
    scope_resolver,
    semantic_unit,
    structure,
    validator,
)


def _is_serious_warning(warning: str) -> bool:
    """Return whether a parser warning violates an artifact integrity invariant."""
    serious_markers = (
        "Số Điều bị thiếu",
        "TRÙNG",
        "id_cha",
        "KHÔNG tồn tại",
        "không resolve được văn bản",
    )
    return any(marker in warning for marker in serious_markers)


def run_one(filename: str, so_hieu: str) -> bool:
    path = Path(RAW_DIR) / filename
    if not path.exists():
        print(f"ERROR: {filename}: KHÔNG TÌM THẤY file trong {RAW_DIR}/")
        return False

    meta = VAN_BAN_SCOPE.get(so_hieu, {})
    ten = meta.get("ten", so_hieu)
    loai = meta.get("loai", "KhongRoLoai")

    paragraphs = normalize.load_docx(str(path))
    paragraphs = normalize.normalize_paragraphs(paragraphs)

    van_ban_full = structure.parse_document(paragraphs, so_hieu, ten=ten, loai=loai)
    header_metadata = metadata_versioning.extract_header_metadata(str(path))
    effective_payload = metadata_versioning.save_effective_rules(
        van_ban_full, PARSED_DIR
    )
    general_rule = next(
        (r for r in effective_payload["rules"] if r["rule_type"] == "GENERAL"), None
    )

    # Lưu Diagnostic Full Structure
    exporter.save_structure(
        van_ban_full,
        PARSED_DIR,
        filename_override=f"{so_hieu.replace('/', '_')}_structure.full.json",
    )

    # Lọc Selected Scope
    van_ban = scope_resolver.apply(van_ban_full)

    if meta.get("hieu_luc_tu"):
        for d in van_ban.dieu_khong_chuong:
            d.hieu_luc_tu = d.hieu_luc_tu or meta["hieu_luc_tu"]
        for c in van_ban.chuong:
            for d in c.dieu:
                d.hieu_luc_tu = d.hieu_luc_tu or meta["hieu_luc_tu"]

    target_mac_dinh = AMENDMENT_TARGET_FALLBACK.get(so_hieu)
    units = semantic_unit.build(van_ban, target_so_hieu_mac_dinh=target_mac_dinh)
    index = validator.build_global_index(PARSED_DIR, exclude_so_hieu=so_hieu)
    warnings = validator.validate(van_ban, units, index_so_hieu_to_ids=index)

    so_dieu_full = len(van_ban_full.dieu_khong_chuong) + sum(
        len(c.dieu) for c in van_ban_full.chuong
    )
    so_dieu_selected = len(van_ban.dieu_khong_chuong) + sum(
        len(c.dieu) for c in van_ban.chuong
    )
    status = "✅ OK" if not warnings else f"⚠️  {len(warnings)} cảnh báo"
    print(
        f"{filename} ({so_hieu}): Full {so_dieu_full} Điều, Selected {so_dieu_selected} Điều, {len(units)} semantic units — {status}"
    )
    for w in warnings:
        print("   -", w)

    serious_warnings = [warning for warning in warnings if _is_serious_warning(warning)]
    if serious_warnings:
        print(
            f"ERROR: {so_hieu} có {len(serious_warnings)} lỗi validation nghiêm trọng."
        )
        return False

    exporter.save_structure(van_ban, PARSED_DIR)
    exporter.save_semantic_units(units, so_hieu, PARSED_DIR)
    exporter.save_reference_index(units, so_hieu, PARSED_DIR)

    # Văn bản có role AMENDMENT/OMNIBUS -> ghi nhận Amendment Event (KHÔNG merge)
    role = DOCUMENT_REGISTRY.get(so_hieu, {}).get("role", "NORMAL")
    amendment_targets = []
    if role in ("AMENDMENT", "OMNIBUS"):
        _, amendment_targets = amendment_recorder.run_for(
            so_hieu, str(path), is_omnibus=(role == "OMNIBUS")
        )

    exporter.save_metadata(
        van_ban,
        PARSED_DIR,
        extra={
            **header_metadata,
            "hieu_luc_tu": (general_rule or {}).get("effective_from")
            or meta.get("hieu_luc_tu"),
            "canonical_document_id": so_hieu.replace("/", "_"),
            "effective_rule_count": len(effective_payload["rules"]),
        },
        amendment_target_documents=amendment_targets,
    )
    return True


def run() -> bool:
    Path(PARSED_DIR).mkdir(exist_ok=True, parents=True)
    if not FILE_SO_HIEU_MAP:
        print("ERROR: FILE_SO_HIEU_MAP đang trống — thêm file vào src/config.py trước.")
        return False
    succeeded = True
    for filename, so_hieu in FILE_SO_HIEU_MAP.items():
        succeeded = run_one(filename, so_hieu) and succeeded
    if not succeeded:
        return False
    corpus_postprocessor.run(PARSED_DIR)
    report = corpus_audit.run(PARSED_DIR)
    if not report.get("all_pass", False):
        failed_checks = [
            name
            for name, result in report.items()
            if name.startswith("issue_") and not result.get("pass", False)
        ]
        print("ERROR: Corpus audit failed: " + ", ".join(failed_checks))
        return False
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
