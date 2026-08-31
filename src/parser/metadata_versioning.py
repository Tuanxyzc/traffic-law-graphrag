import json
import re
from pathlib import Path

import docx

from src.parser.canonical_id_resolver import canonical_document_id, normalize_so_hieu
from src.parser.models import VanBan
from src.parser import operation


DATE_RE = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
EFFECT_FROM_RE = re.compile(r"(?:có|được)\s+hiệu\s+lực(?:\s+thi\s+hành)?\s+(?:từ|kể\s+từ)\s+ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
EFFECT_TO_RE = re.compile(r"hết\s+hiệu\s+lực\s+(?:kể\s+từ|từ)\s+ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)


def _iso_date(match) -> str:
    return f"{int(match.group(3)):04d}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"


def extract_header_metadata(source_file: str) -> dict:
    document = docx.Document(source_file)
    header_texts = []
    for table in document.tables[:3]:
        for row in table.rows[:4]:
            header_texts.extend(cell.text.strip() for cell in row.cells if cell.text.strip())
    authority = None
    for text in header_texts:
        first = text.splitlines()[0].strip()
        if first in ("QUỐC HỘI", "CHÍNH PHỦ") or first.startswith(("BỘ ", "THỦ TƯỚNG CHÍNH PHỦ")):
            authority = first
            break
    issue_raw = next((text for text in header_texts if DATE_RE.search(text)), None)
    match = DATE_RE.search(issue_raw or "")
    return {
        "co_quan_ban_hanh": authority,
        "ngay_ban_hanh": _iso_date(match) if match else None,
        "ngay_ban_hanh_raw": issue_raw,
    }


def _articles(van_ban: VanBan):
    yield from van_ban.dieu_khong_chuong
    for chapter in van_ban.chuong:
        yield from chapter.dieu


def build_effective_rules(van_ban: VanBan) -> dict:
    rules = []
    doc = normalize_so_hieu(van_ban.so_hieu)
    for article in _articles(van_ban):
        title = (article.tieu_de or "").lower()
        if "hiệu lực" not in title and "điều khoản thi hành" not in title:
            continue
        sources = article.khoan or []
        if not sources and article.noi_dung:
            sources = [type("RuleSource", (), {"so": None, "noi_dung": article.noi_dung})()]
        for source in sources:
            raw = source.noi_dung.strip()
            for part_index, part in enumerate(re.split(r";\s*(?=(?:quy định|Luật|Nghị định))", raw)):
                from_match = EFFECT_FROM_RE.search(part)
                to_match = EFFECT_TO_RE.search(part)
                external = bool(re.search(r"hiệu lực.*theo quy định của pháp luật", part, re.IGNORECASE)) and not from_match
                if not from_match and not to_match and not external:
                    continue
                targets = operation.detect_target(part, doc)
                unique_targets = []
                seen_target_ids = set()
                for target in targets:
                    target_id = target.target_id()
                    if not target_id or target_id in seen_target_ids:
                        continue
                    seen_target_ids.add(target_id)
                    unique_targets.append(target)
                is_general = bool(re.match(r"^\s*(?:\d+[a-zđ]?\.\s*)?(?:Luật|Nghị định) này có hiệu lực", part, re.IGNORECASE))
                # A termination clause is version metadata, but its date is an end date.
                rule_type = "EXTERNAL_RULE" if external else ("GENERAL" if is_general else "EXPLICIT")
                rules.append({
                    "rule_id": f"{canonical_document_id(doc)}_ER_{article.so}_{source.so or '0'}_{part_index + 1}",
                    "rule_type": rule_type,
                    "source_document": doc,
                    "source_article": article.so,
                    "source_clause": source.so,
                    "target_document": doc,
                    "targets": [{
                        "unit_id": target.target_id(),
                        "article": target.dieu,
                        "clause": target.khoan,
                        "point": target.diem,
                    } for target in unique_targets] if not is_general else [],
                    "effective_from": _iso_date(from_match) if from_match else None,
                    "effective_to": _iso_date(to_match) if to_match else None,
                    "external_basis": part.strip() if external else None,
                    "condition": None,
                    "raw_text": part.strip(),
                    "status": "EXTERNAL" if external else "RESOLVED",
                })
    return {"document": doc, "document_id": canonical_document_id(doc), "rules": rules}


def save_effective_rules(van_ban: VanBan, output_dir: str):
    payload = build_effective_rules(van_ban)
    path = Path(output_dir) / f"{canonical_document_id(van_ban.so_hieu)}_effective_rules.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
