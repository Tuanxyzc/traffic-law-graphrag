"""
amendment_recorder.py — Ghi nhận "Amendment Event"
"""

from pathlib import Path
import re
from copy import deepcopy
from dataclasses import asdict

from src.parser.normalize import load_docx, normalize_paragraphs, DoanVan
from src.parser.structure import DIEU_TITLE_PATTERN, KHOAN_PATTERN, DIEM_PATTERN, parse_khoan_list, parse_diem_list
from src.parser import operation, document_registry, exporter, reference
from src.config import PARSED_DIR, AMENDMENT_TARGET_FALLBACK, OMNIBUS_CONFIG

class State:
    NORMAL = 0
    AMENDMENT_BLOCK = 1
    SOURCE_CONTEXT = 2
    SOURCE_ITEM = 3
    TARGET_DETECTION = 4
    QUOTE_BLOCK = 5
    REPLACEMENT_TREE = 6
    TARGET_MATCHING = 7
    END_QUOTE = 8

def split_source_items(text: str) -> list[str]:
    lines = text.split('\n')
    items = []
    current = ""
    for line in lines:
        if DIEM_PATTERN.match(line):
            if current.strip():
                items.append(current.strip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        items.append(current.strip())
    return items

def _target_level_cua(vt) -> str:
    if vt.diem: return "POINT"
    if vt.khoan: return "CLAUSE"
    return "ARTICLE"

def build_replacement_tree_and_root(quote_block: str, root_level: str) -> tuple[dict, str]:
    if root_level == "POINT":
        pts = parse_diem_list(quote_block, "tmp")
        if len(pts) > 1:
            return {"points": [{"number": p.so, "content": p.noi_dung} for p in pts]}, "POINT_LIST"
        elif len(pts) == 1:
            return {"point": {"number": pts[0].so, "content": pts[0].noi_dung}}, "POINT"
        # Fallback if parse fails
        return {"point": {"number": quote_block[:1] if len(quote_block)>1 and quote_block[1] == ")" else None, "content": quote_block.strip()}}, "POINT"

    if root_level == "CLAUSE":
        khoan_list = parse_khoan_list(quote_block, "tmp")
        if khoan_list:
            if len(khoan_list) > 1:
                return {"clauses": [
                    {"number": k.so, "content": k.noi_dung, "points": [{"number": p.so, "content": p.noi_dung} for p in k.diem]}
                    for k in khoan_list
                ]}, "CLAUSE_LIST"
            else:
                k = khoan_list[0]
                return {"clause": {
                    "number": k.so, "content": k.noi_dung,
                    "points": [{"number": p.so, "content": p.noi_dung} for p in k.diem],
                }}, "CLAUSE"
        return {"clause": {"number": None, "content": quote_block, "points": []}}, "CLAUSE"

    article_blocks = []
    current_article = []
    for line in quote_block.splitlines(keepends=True):
        if DIEU_TITLE_PATTERN.match(line.strip()) and current_article:
            article_blocks.append("".join(current_article).strip())
            current_article = []
        current_article.append(line)
    if current_article:
        article_blocks.append("".join(current_article).strip())
    if (len(article_blocks) > 1
            and all(DIEU_TITLE_PATTERN.match(block.splitlines()[0]) for block in article_blocks)):
        articles = [build_replacement_tree_and_root(block, "ARTICLE")[0]["article"]
                    for block in article_blocks]
        return {"articles": articles}, "ARTICLE_LIST"

    article_lines = quote_block.splitlines()
    title_line = article_lines[0] if article_lines else quote_block
    dieu_match = DIEU_TITLE_PATTERN.match(title_line)
    so = dieu_match.group(1) if dieu_match else None
    title = dieu_match.group(2) if dieu_match else ""
    remainder = "\n".join(article_lines[1:]).strip() if dieu_match else quote_block
    khoan_list = parse_khoan_list(remainder, "tmp")
    
    return {"article": {
        "number": so, "title": title,
        "clauses": [
            {"number": k.so, "content": k.noi_dung,
             "points": [{"number": p.so, "content": p.noi_dung} for p in k.diem]}
            for k in khoan_list
        ]
    }}, "ARTICLE"

def parse_amendment_workflow(paragraphs) -> list[dict]:
    items = []
    state = State.NORMAL
    
    current_clause = None
    current_point = None
    current_instruction = ""
    current_quote = ""
    quote_balance = 0
    inside_straight_quote = False
    
    def extract_quote_block(text: str) -> str:
        start_idx = -1
        for i, c in enumerate(text):
            if c in ('“', '"'):
                start_idx = i
                break
        if start_idx == -1: return text.strip()
        end_idx = -1
        for i in range(len(text)-1, -1, -1):
            if text[i] in ('”', '"'):
                end_idx = i
                break
        if end_idx != -1 and end_idx > start_idx:
            return text[start_idx+1:end_idx].strip()
        return text[start_idx+1:].strip()
    
    def flush_item():
        nonlocal current_clause, current_point, current_instruction, current_quote
        instruction = current_instruction.strip()
        quote = extract_quote_block(current_quote) if current_quote.strip() else ""
        
        if instruction:
            source_items = split_source_items(instruction)
            for s_item in source_items:
                point_match = DIEM_PATTERN.match(s_item)
                point_val = point_match.group(1) if point_match else current_point
                items.append({
                    "source_clause": current_clause,
                    "source_point": point_val,
                    "instruction": s_item,
                    "quote_block": quote,
                    "implicit": not bool(point_match) and not bool(point_val)
                })
        current_instruction = ""
        current_quote = ""

    for p in paragraphs:
        text = p.text.strip()
        if not text: continue
        
        if state == State.NORMAL:
            k_match = KHOAN_PATTERN.match(text)
            d_match = DIEM_PATTERN.match(text)
            
            is_new_structure = False
            if k_match:
                flush_item()
                current_clause = k_match.group(1)
                current_point = None
                is_new_structure = True
            elif d_match:
                flush_item()
                current_point = d_match.group(1)
                is_new_structure = True
                
            is_text_amend_inst = bool(re.search(r'(bổ\s+sung|bãi\s+bỏ|thay\s+thế|bỏ)\s+(?:một\s+số\s+)?(từ|cụm\s+từ|phụ\s+lục)', text, re.IGNORECASE))
            quote_start = -1
            if not is_text_amend_inst:
                for i, c in enumerate(text):
                    if c in ('“', '"'):
                        # Cẩn thận: nếu phía trước quote không có từ khóa báo hiệu replacement block (như "như sau:"), có thể là inline quote
                        # Nhưng tạm thời giữ logic cũ, chỉ bypass cho text/appendix amendment
                        quote_start = i
                        break
                    
            if quote_start != -1:
                state = State.QUOTE_BLOCK
                quote_balance += text.count("“") - text.count("”")
                quote_balance = max(quote_balance, 0)
                if text.count('"') % 2 != 0:
                    inside_straight_quote = not inside_straight_quote
                    
                if is_new_structure:
                    current_instruction = text[:quote_start]
                    current_quote = text[quote_start:]
                else:
                    if not current_instruction:
                        current_instruction = text[:quote_start]
                    current_quote += "\n" + text[quote_start:]
                    
                if quote_balance <= 0 and not inside_straight_quote:
                    state = State.NORMAL
                    quote_balance = 0
            else:
                if is_new_structure:
                    current_instruction = text
                else:
                    if not current_instruction:
                        current_instruction = text
                    else:
                        current_instruction += "\n" + text
                        
        elif state == State.QUOTE_BLOCK:
            current_quote += "\n" + text
            quote_balance += text.count("“") - text.count("”")
            quote_balance = max(quote_balance, 0)
            if text.count('"') % 2 != 0:
                inside_straight_quote = not inside_straight_quote
                
            if quote_balance <= 0 and not inside_straight_quote:
                state = State.NORMAL
                quote_balance = 0
                
    flush_item()
    return items

from src.parser.target_matcher import match_targets, get_nodes_at_level

def build_ids_for_context(so_hieu: str, context: dict, dieu=None, khoan=None, diem=None):
    # Use explicit document if available, else fallback to so_hieu
    actual_so_hieu = context.get("document") or so_hieu
    if context.get("article") and context["article"]["number"]:
        context["article"]["id"] = f"{actual_so_hieu.replace('/', '_')}_D{context['article']['number']}"
        if context.get("clause") and context["clause"]["number"]:
            context["clause"]["id"] = f"{context['article']['id']}_K{context['clause']['number']}"
            if context.get("point") and context["point"]["number"]:
                context["point"]["id"] = f"{context['clause']['id']}_D{context['point']['number']}"

def parse_actions(text: str, default_so_hieu: str):
    import re
    pattern = re.compile(
        r'\b(?:và|đồng thời)\s+'
        r'(?=(?:sửa đổi|bổ sung|thay thế|bãi bỏ|thêm mới)\s+'
        r'(?:khoản|điểm|Điều|từ|cụm\s+từ|Phụ\s+lục)\b)',
        re.IGNORECASE,
    )
    segments = pattern.split(text.replace("Sửa đổi, bổ sung", "SUADOI_BOSUNG"))
    # Coordinated actions often repeat the operation but place the shared legal
    # location only in the final segment (e.g. "sửa khoản 18 và bổ sung ...
    # khoản 18 Điều 9"). Preserve provenance while supplying that location to
    # structural target detection for the earlier segment.
    shared_articles = re.findall(r"\bĐiều\s+(\d+[a-zđ]?)", text, re.IGNORECASE)
    shared_article = shared_articles[0] if len(set(shared_articles)) == 1 else None
    
    actions = []

    def mask_quoted_spans(value: str) -> str:
        """Mask quoted content for structural target detection only.

        The original instruction is retained separately as immutable provenance.
        Both straight and Vietnamese curly quote spans are supported, including
        multiple spans in one instruction.
        """
        chars = list(value)
        opening = None
        for i, ch in enumerate(chars):
            # Treat any quote glyph as a boundary. Real-world DOCX text can use
            # an orphan closing quote (”) as the opening delimiter.
            if ch in ('"', '“', '”') and opening is None:
                opening = i
            elif ch in ('"', '“', '”') and opening is not None:
                for j in range(opening, i + 1):
                    if chars[j] not in ('\n', '\r'):
                        chars[j] = ' '
                opening = None
        if opening is not None:
            for j in range(opening, len(chars)):
                if chars[j] not in ('\n', '\r'):
                    chars[j] = ' '
        return ''.join(chars)
    for seg in segments:
        seg = seg.replace("SUADOI_BOSUNG", "Sửa đổi, bổ sung")
        raw_instruction = seg.strip()
        hanh_dong = operation.detect_operation(seg)
        if not hanh_dong: 
            continue
            
        anchor = None
        text_amend = None
        appendix_amend = None
        
        if hanh_dong == "THAY_THE_TEXT":
            m = re.search(r'thay thế\s+(?:một\s+số\s+)?(từ|cụm\s+từ)\s*["“”](.*?)["”]\s*bằng\s*(?:từ|cụm\s+từ)\s*["“”](.*?)["”]', seg, re.IGNORECASE)
            if m:
                text_amend = {
                    "unit_type": "WORD" if m.group(1).lower() == "từ" else "PHRASE",
                    "old_text": m.group(2),
                    "new_text": m.group(3)
                }
        elif hanh_dong == "BO_SUNG_TEXT":
            m = re.search(r'bổ sung\s+(từ|cụm\s+từ)\s*["“”](.*?)["”]\s*(vào\s+sau|sau|vào\s+trước|trước)\s*(?:từ|cụm\s+từ|từ\s+ngữ)\s*["“”](.*?)["”]', seg, re.IGNORECASE)
            if m:
                rel_str = m.group(3).lower()
                rel = "AFTER" if "sau" in rel_str else "BEFORE"
                text_amend = {
                    "unit_type": "WORD" if m.group(1).lower() == "từ" else "PHRASE",
                    "text": m.group(2),
                    "relation": rel,
                    "anchor_text": m.group(4)
                }
        elif hanh_dong == "BAI_BO_TEXT":
            m = re.search(r'(?:bãi\s+bỏ|bỏ)\s+(từ|cụm\s+từ)\s*["“”](.*?)["”]', seg, re.IGNORECASE)
            if m:
                text_amend = {
                    "unit_type": "WORD" if m.group(1).lower() == "từ" else "PHRASE",
                    "text": m.group(2)
                }
        elif hanh_dong == "THAY_THE_PHU_LUC":
            m = re.search(r'thay thế\s+(?:một số )?(phụ lục\s+[IVX0-9A-Z]+)\b.*?(\bban hành\b.*?)?(?:bằng\s+(phụ lục\s+[IVX0-9A-Z]+))?', seg, re.IGNORECASE)
            if m:
                old_doc = None
                if m.group(2):
                    v_meta = document_registry.resolve(m.group(2))
                    if v_meta:
                        old_doc = v_meta["number"]
                if not old_doc:
                    v_meta = document_registry.resolve(seg)
                    old_doc = v_meta["number"] if v_meta else default_so_hieu
                    
                appendix_amend = {
                    "old_appendix": {
                        "number": m.group(1).replace("Phụ lục", "").strip(),
                        "document": old_doc
                    },
                    "new_appendix": {
                        "number": m.group(3).replace("Phụ lục", "").strip() if m.group(3) else m.group(1).replace("Phụ lục", "").strip(),
                        "document": None # Will be set to source_document by caller
                    }
                }

        anchor_match = re.search(r'(vào sau|vào trước|trước|sau|cuối)\s+(khoản|điểm|điều)\s+(.*?)(?=\s+như\s+sau|\s+và|$|,)', raw_instruction, re.IGNORECASE)
        anchor_span = anchor_match.span() if anchor_match else None
        if anchor_match and hanh_dong not in ("BO_SUNG_TEXT", "THAY_THE_TEXT", "BAI_BO_TEXT", "THAY_THE_PHU_LUC"):
            rel_str = anchor_match.group(1).lower()
            rel_enum = "AFTER" if "sau" in rel_str else ("BEFORE" if "trước" in rel_str else "APPEND")
            anchor_text = anchor_match.group(2) + " " + anchor_match.group(3)
            anchor_vts = operation.detect_target(anchor_text, default_so_hieu)
            if anchor_vts:
                anchor = {
                    "relation": rel_enum,
                    "target_document": default_so_hieu,
                    "target": {
                        "document": default_so_hieu,
                        "article": anchor_vts[0].dieu,
                        "clause": anchor_vts[0].khoan,
                        "point": anchor_vts[0].diem
                    }
                }
            masked_instruction = raw_instruction[:anchor_match.start()] + " " * (anchor_match.end() - anchor_match.start()) + raw_instruction[anchor_match.end():]
        else:
            masked_instruction = raw_instruction
            
        targets = []
        created_targets = []
        if hanh_dong == "THAY_THE_PHU_LUC":
            pass
        else:
            target_source = (mask_quoted_spans(raw_instruction)
                              if hanh_dong in ("BO_SUNG_TEXT", "BAI_BO_TEXT", "THAY_THE_TEXT")
                              else masked_instruction)
            contextual_target_source = target_source
            if shared_article and not re.search(r"\bĐiều\s+\d+[a-zđ]?", contextual_target_source, re.IGNORECASE):
                contextual_target_source += f" Điều {shared_article}"
            targets = operation.detect_target(contextual_target_source, default_so_hieu)
            # For insertion, the existing target is the anchor; the created unit
            # is represented separately by replacement_tree (never overload target_unit).
            if anchor and anchor.get("relation") in ("BEFORE", "AFTER") and anchor.get("target"):
                created_targets = targets
                at = anchor["target"]
                targets = [operation.ViTri(dieu=at.get("article"), khoan=at.get("clause"),
                                           diem=at.get("point"), so_hieu_van_ban=default_so_hieu)]
            
        actions.append({
                "operation": hanh_dong,
                "targets": targets,
                "created_targets": created_targets,
                "anchor": anchor,
                "text_amendment": text_amend,
                "appendix_amendment": appendix_amend,
                "raw_instruction": raw_instruction,
                "normalized_instruction": raw_instruction,
                "masked_instruction": masked_instruction,
                "anchor_span": anchor_span,
        })
    return actions

def merge_vitri(child, parent):
    if not child.dieu and parent: child.dieu = parent.dieu
    if not child.khoan and parent: child.khoan = parent.khoan
    if not child.diem and parent: child.diem = parent.diem
    if not child.so_hieu_van_ban and parent and parent.so_hieu_van_ban: child.so_hieu_van_ban = parent.so_hieu_van_ban
    return child


def is_non_action_container(item: dict, instruction: str) -> bool:
    """Return true for article/clause headings that only introduce child items."""
    if item.get("source_point") is not None:
        return False
    text = instruction.strip()
    if item.get("source_clause") is None:
        if DIEU_TITLE_PATTERN.match(text):
            return True
        if re.match(r"^(?:Bổ sung|Sửa đổi|Thay thế|Bãi bỏ|Bỏ)\b.*(?:một số|kèm theo|phụ lục)", text, re.IGNORECASE):
            return True
    return bool(re.match(
        r"^\s*\d+[a-zđ]?\.\s+(?:Bổ sung|Sửa đổi|Thay thế|Bãi bỏ|Bỏ)\s+"
        r"(?:một số|một vài)\b.*\bnhư sau\s*:?\s*$", text, re.IGNORECASE
    ))


def build_created_units(replacement_tree: dict, root_level: str, target_document: str,
                        existing_target=None, created_targets=None) -> list[dict]:
    """Build newly-created structural units from replacement content.

    Anchor/existing target context supplies only missing parents. The created
    number itself always comes from replacement_tree.
    """
    nodes = []
    if root_level == "ARTICLE" and replacement_tree.get("article"):
        nodes = [("ARTICLE", replacement_tree["article"])]
    elif root_level == "CLAUSE" and replacement_tree.get("clause"):
        nodes = [("CLAUSE", replacement_tree["clause"])]
    elif root_level == "CLAUSE_LIST":
        nodes = [("CLAUSE", n) for n in replacement_tree.get("clauses", [])]
    elif root_level == "POINT" and replacement_tree.get("point"):
        nodes = [("POINT", replacement_tree["point"])]
    elif root_level == "POINT_LIST":
        nodes = [("POINT", n) for n in replacement_tree.get("points", [])]
    elif root_level == "ARTICLE_LIST":
        nodes = [("ARTICLE", n) for n in replacement_tree.get("articles", [])]

    article = existing_target.dieu if existing_target else None
    clause = existing_target.khoan if existing_target else None
    if created_targets:
        result = []
        for target in created_targets:
            if not target.dieu: target.dieu = article
            if not target.khoan and target.diem: target.khoan = clause
            level = _target_level_cua(target)
            number = target.diem or target.khoan or target.dieu
            result.append({"unit_id": target.target_id(), "unit_level": level, "number": number})
        return result
    result = []
    for level, node in nodes:
        number = str(node.get("number", "")).strip()
        if not number:
            continue
        if level == "ARTICLE":
            vt = operation.ViTri(dieu=number, so_hieu_van_ban=target_document)
        elif level == "CLAUSE":
            vt = operation.ViTri(dieu=article, khoan=number, so_hieu_van_ban=target_document)
        else:
            vt = operation.ViTri(dieu=article, khoan=clause, diem=number,
                                 so_hieu_van_ban=target_document)
        result.append({"unit_id": vt.target_id(), "unit_level": level, "number": number})
    return result


def restrict_replacement_tree_to_created(tree: dict, root_level: str, created_targets) -> tuple[dict, str]:
    """For insertion operations, retain only structural nodes actually created.

    Quoted insertion blocks can include the anchor or surrounding context. Those
    nodes are not newly created and must not be presented as replacement output.
    """
    if not created_targets:
        return tree, root_level
    wanted = {( _target_level_cua(t), str(t.diem or t.khoan or t.dieu) ) for t in created_targets}
    if root_level == "CLAUSE_LIST":
        nodes = [n for n in tree.get("clauses", []) if ("CLAUSE", str(n.get("number"))) in wanted]
        return ({"clauses": nodes}, "CLAUSE_LIST")
    if root_level == "CLAUSE":
        n = tree.get("clause") or {}
        return ({"clause": n}, "CLAUSE") if ("CLAUSE", str(n.get("number"))) in wanted else ({"clauses": []}, "CLAUSE_LIST")
    if root_level == "POINT_LIST":
        nodes = [n for n in tree.get("points", []) if ("POINT", str(n.get("number"))) in wanted]
        return ({"points": nodes}, "POINT_LIST")
    if root_level == "POINT":
        n = tree.get("point") or {}
        return ({"point": n}, "POINT") if ("POINT", str(n.get("number"))) in wanted else ({"points": []}, "POINT_LIST")
    if root_level == "ARTICLE":
        n = tree.get("article") or {}
        if n.get("number") is None and len(created_targets) == 1:
            n = dict(n); n["number"] = created_targets[0].dieu
        return {"article": n}, "ARTICLE"
    return tree, root_level


def resolve_replacement_references(tree: dict, target, target_document: str) -> list[dict]:
    """Resolve relative references in replacement content against target law context."""
    if not tree or not target:
        return []
    texts = []
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("content"), str):
                texts.append(value["content"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(tree)
    current = operation.ViTri(dieu=target.dieu, khoan=target.khoan, diem=target.diem,
                              so_hieu_van_ban=target_document)
    result = []
    for text in texts:
        result.extend(asdict(x) for x in reference.resolve_references(text, current, target_document))
    return result

def _split_top_level_raw(paragraphs):
    from src.parser.structure import DIEU_TITLE_PATTERN
    blocks = []
    current_block = None
    quote_balance = 0
    for p in paragraphs:
        text = p.text
        is_inside_quote = quote_balance > 0 or text.lstrip().startswith("“") or text.lstrip().startswith('"')
        m = DIEU_TITLE_PATTERN.match(text)
        if m and p.dam and not is_inside_quote:
            if current_block: blocks.append(current_block)
            current_block = {"so": m.group(1), "tieu_de": text, "paragraphs": []}
        else:
            if current_block: current_block["paragraphs"].append(p)
        quote_balance += text.count("“") - text.count("”")
        quote_balance = max(quote_balance, 0)
    if current_block: blocks.append(current_block)
    return blocks

def record_dedicated(source_file: str, source_so_hieu: str) -> list[dict]:
    from src.parser.operation import ViTri
    paragraphs = normalize_paragraphs(load_docx(source_file))
    blocks = _split_top_level_raw(paragraphs)
    events = []

    from src.parser.structure import DIEU_TITLE_PATTERN
    for block in blocks:
        tieu_de = block["tieu_de"]
        m_tieu_de = DIEU_TITLE_PATTERN.match(tieu_de)
        clean_tieu_de = m_tieu_de.group(2) if m_tieu_de else tieu_de

        hanh_dong = operation.detect_operation(clean_tieu_de)
        target_meta = document_registry.resolve(clean_tieu_de)
        target_so_hieu = target_meta["number"] if target_meta else AMENDMENT_TARGET_FALLBACK.get(source_so_hieu)
        if not target_so_hieu: continue

        targets_block = operation.detect_target(clean_tieu_de, default_so_hieu=target_so_hieu)
        pars = [DoanVan(text=block["tieu_de"], dam=True)] + block["paragraphs"]
        source_items = parse_amendment_workflow(pars)
            
        event_items = []
        clause_target_context = {}
        for item in source_items:
            inst = item["instruction"] if item["instruction"] else block["tieu_de"]
            m_inst = DIEU_TITLE_PATTERN.match(inst)
            inst = m_inst.group(2) if m_inst else inst
            if is_non_action_container(item, inst):
                continue
            
            # Parent context resolution
            base_target = ViTri(None, None, None)
            if targets_block:
                base_target = ViTri(targets_block[0].dieu, targets_block[0].khoan, targets_block[0].diem)
            
            if item["source_point"] and item["source_clause"]:
                parent_t = clause_target_context.get(item["source_clause"])
                if parent_t:
                    base_target = ViTri(parent_t.dieu, parent_t.khoan, parent_t.diem)

            actions = parse_actions(inst, target_so_hieu)
            if not actions:
                continue
                
            # Merge context into actions
            for act in actions:
                for t in act["targets"]:
                    merge_vitri(t, base_target)
                for t in act.get("created_targets", []):
                    merge_vitri(t, base_target)
                if act["anchor"] and act["anchor"].get("target"):
                    a_t = act["anchor"]["target"]
                    if not a_t["article"]: a_t["article"] = base_target.dieu
                    if not a_t["clause"]: a_t["clause"] = base_target.khoan
                    for t in act["targets"]:
                        if not t.dieu and a_t["article"]: t.dieu = a_t["article"]
                        if not t.khoan and a_t["clause"]: t.khoan = a_t["clause"]

            if item["source_clause"] and not item["source_point"] and actions and actions[0]["targets"]:
                clause_target_context[item["source_clause"]] = ViTri(
                    actions[0]["targets"][0].dieu,
                    actions[0]["targets"][0].khoan,
                    actions[0]["targets"][0].diem
                )

            first_target = actions[0]["targets"][0] if actions and actions[0]["targets"] else None
            level_hint = _target_level_cua(first_target) if first_target else "ARTICLE"
            dieu_match = DIEU_TITLE_PATTERN.match(item["quote_block"])
            if dieu_match: level_hint = "ARTICLE"
            
            repl_tree, root_lvl = build_replacement_tree_and_root(item["quote_block"], level_hint)
            is_text_or_app = any(a["operation"] in ("BO_SUNG_TEXT", "BAI_BO_TEXT", "THAY_THE_TEXT", "THAY_THE_PHU_LUC")
                                 or a.get("text_amendment") or a.get("appendix_amendment") for a in actions)
            if not item["quote_block"] and actions[0]["operation"] != "BAI_BO" and not is_text_or_app: 
                continue

            source_context = {
                "article": {"id": None, "number": block["so"]} if block["so"] else None,
                "clause": {"id": None, "number": item["source_clause"]} if item["source_clause"] else None,
                "point": {"id": None, "number": item["source_point"]} if item["source_point"] else None
            }
            build_ids_for_context(source_so_hieu, source_context)
            p_ctx = source_context.get("point")
            c_ctx = source_context.get("clause")
            a_ctx = source_context.get("article")
            source_unit_id = (p_ctx.get("id") if p_ctx else None) or (c_ctx.get("id") if c_ctx else None) or (a_ctx.get("id") if a_ctx else None)

            final_actions = []
            for act in actions:
                is_text = act.get("text_amendment") is not None
                is_app = act.get("appendix_amendment") is not None
                is_insert = bool(act.get("anchor") and act["anchor"].get("relation") in ("BEFORE", "AFTER"))

                if is_app:
                    act["appendix_amendment"]["new_appendix"]["document"] = source_so_hieu
                    act_targets = [{
                        "target_type": "APPENDIX",
                        "appendix_number": act["appendix_amendment"]["old_appendix"]["number"],
                        "document": act["appendix_amendment"]["old_appendix"]["document"]
                    }]
                else:
                    if act["operation"] == "BAI_BO" or is_text or is_insert:
                        mapped_targets = [{
                            "target_unit_mock": t,
                            "target_context": {
                                "document": t.so_hieu_van_ban,
                                "article": {"id": None, "number": t.dieu} if t.dieu else None,
                                "clause": {"id": None, "number": t.khoan} if t.khoan else None,
                                "point": {"id": None, "number": t.diem} if t.diem else None
                            },
                            "target_level": _target_level_cua(t),
                            "replacement_level": None,
                            "replacement_path": None
                        } for t in act["targets"]]
                    else:
                        mapped_targets = match_targets(act["targets"], repl_tree, root_lvl)

                    act_targets = []
                    for m in mapped_targets:
                        build_ids_for_context(target_so_hieu, m["target_context"])
                        p_ctx = m["target_context"].get("point")
                        c_ctx = m["target_context"].get("clause")
                        a_ctx = m["target_context"].get("article")
                        t_unit = (p_ctx.get("id") if p_ctx else None) or (c_ctx.get("id") if c_ctx else None) or (a_ctx.get("id") if a_ctx else None) or m["target_unit_mock"].target_id()
                        act_targets.append({
                            "target_unit": t_unit,
                            "target_context": m["target_context"],
                            "target_level": m["target_level"],
                            "replacement_level": m["replacement_level"],
                            "replacement_path": m["replacement_path"]
                        })
                
                first_existing = act["targets"][0] if act.get("targets") else None
                created_units = (build_created_units(repl_tree, root_lvl, target_so_hieu, first_existing,
                                                     act.get("created_targets"))
                                 if is_insert and repl_tree else [])
                replacement_references = resolve_replacement_references(repl_tree, first_existing, target_so_hieu)
                final_actions.append({
                    "operation": act["operation"],
                    "anchor": act["anchor"],
                    "targets": act_targets,
                    "created_units": created_units,
                    "replacement_references": replacement_references,
                    "text_amendment": act.get("text_amendment"),
                    "appendix_amendment": act.get("appendix_amendment"),
                    "raw_instruction": act.get("raw_instruction", ""),
                    "normalized_instruction": act.get("normalized_instruction", ""),
                    "anchor_span": act.get("anchor_span"),
                    "resolution_status": "RESOLVED" if act_targets else "UNRESOLVED"
                })

            event_items.append({
                "source_unit": source_unit_id,
                "source_point": {
                    "id": source_unit_id,
                    "number": item["source_point"],
                    "implicit": item["implicit"],
                    "instruction": item["instruction"]
                },
                "replacement_root_level": root_lvl if not is_text_or_app else None,
                "replacement_tree": repl_tree if any(a["operation"] != "BAI_BO" and not a.get("text_amendment") and not a.get("appendix_amendment") for a in actions) else None,
                "actions": final_actions
            })

        if event_items:
            ev_context = {
                "article": {"id": f"{source_so_hieu.replace('/', '_')}_D{block['so']}", "number": block["so"]} if block["so"] else None,
                "clause": None,
                "point": None
            }
            events.append({
                "source_document": source_so_hieu,
                "target_document": target_so_hieu,
                "source_context": ev_context,
                "items": event_items
            })
    return events

def record_omnibus(source_file: str, source_so_hieu: str) -> list[dict]:
    from src.parser.operation import ViTri
    paragraphs = normalize_paragraphs(load_docx(source_file))
    blocks = _split_top_level_raw(paragraphs)
    cfg = next((c for c in OMNIBUS_CONFIG if c["source"] == source_so_hieu), None)
    events = []

    for block in blocks:
        target_meta = document_registry.resolve(block["tieu_de"])
        target_so_hieu = target_meta["number"] if target_meta else None
        if not target_so_hieu and cfg:
            for t in cfg["targets"]:
                if any(kw in block["tieu_de"] for kw in t["keywords"]):
                    target_so_hieu = t["document"]
                    break
        if not target_so_hieu: continue

        targets_block = operation.detect_target(block["tieu_de"], default_so_hieu=target_so_hieu)
        pars = [DoanVan(text=block["tieu_de"], dam=True)] + block["paragraphs"]
        source_items = parse_amendment_workflow(pars)
        
        event_items = []
        clause_target_context = {}
        for item in source_items:
            inst = item["instruction"] if item["instruction"] else block["tieu_de"]
            if is_non_action_container(item, inst):
                continue
            
            # Parent context resolution
            base_target = ViTri(None, None, None)
            if targets_block:
                base_target = ViTri(targets_block[0].dieu, targets_block[0].khoan, targets_block[0].diem)
            
            if item["source_point"] and item["source_clause"]:
                parent_t = clause_target_context.get(item["source_clause"])
                if parent_t:
                    base_target = ViTri(parent_t.dieu, parent_t.khoan, parent_t.diem)

            actions = parse_actions(inst, target_so_hieu)
            if not actions: continue
            
            # Merge context into actions
            for act in actions:
                for t in act["targets"]:
                    merge_vitri(t, base_target)
                for t in act.get("created_targets", []):
                    merge_vitri(t, base_target)
                if act["anchor"] and act["anchor"].get("target"):
                    a_t = act["anchor"]["target"]
                    if not a_t["article"]: a_t["article"] = base_target.dieu
                    if not a_t["clause"]: a_t["clause"] = base_target.khoan
                    for t in act["targets"]:
                        if not t.dieu and a_t["article"]: t.dieu = a_t["article"]
                        if not t.khoan and a_t["clause"]: t.khoan = a_t["clause"]

            if item["source_clause"] and not item["source_point"] and actions and actions[0]["targets"]:
                clause_target_context[item["source_clause"]] = ViTri(
                    actions[0]["targets"][0].dieu,
                    actions[0]["targets"][0].khoan,
                    actions[0]["targets"][0].diem
                )

            first_target = actions[0]["targets"][0] if actions and actions[0]["targets"] else None
            level_hint = _target_level_cua(first_target) if first_target else "ARTICLE"
            dieu_match = DIEU_TITLE_PATTERN.match(item["quote_block"])
            if dieu_match: level_hint = "ARTICLE"
            
            repl_tree, root_lvl = build_replacement_tree_and_root(item["quote_block"], level_hint)
            is_text_or_app = any(a["operation"] in ("BO_SUNG_TEXT", "BAI_BO_TEXT", "THAY_THE_TEXT", "THAY_THE_PHU_LUC")
                                 or a.get("text_amendment") or a.get("appendix_amendment") for a in actions)
            if not item["quote_block"] and actions[0]["operation"] != "BAI_BO" and not is_text_or_app: 
                continue

            source_context = {
                "article": {"id": None, "number": block["so"]} if block["so"] else None,
                "clause": {"id": None, "number": item["source_clause"]} if item["source_clause"] else None,
                "point": {"id": None, "number": item["source_point"]} if item["source_point"] else None
            }
            build_ids_for_context(source_so_hieu, source_context)
            p_ctx = source_context.get("point")
            c_ctx = source_context.get("clause")
            a_ctx = source_context.get("article")
            source_unit_id = (p_ctx.get("id") if p_ctx else None) or (c_ctx.get("id") if c_ctx else None) or (a_ctx.get("id") if a_ctx else None)

            final_actions = []
            for act in actions:
                is_text = act.get("text_amendment") is not None
                is_app = act.get("appendix_amendment") is not None
                is_insert = bool(act.get("anchor") and act["anchor"].get("relation") in ("BEFORE", "AFTER"))

                if is_app:
                    act["appendix_amendment"]["new_appendix"]["document"] = source_so_hieu
                    act_targets = [{
                        "target_type": "APPENDIX",
                        "appendix_number": act["appendix_amendment"]["old_appendix"]["number"],
                        "document": act["appendix_amendment"]["old_appendix"]["document"]
                    }]
                else:
                    if act["operation"] == "BAI_BO" or is_text or is_insert:
                        mapped_targets = [{
                            "target_unit_mock": t,
                            "target_context": {
                                "document": t.so_hieu_van_ban,
                                "article": {"id": None, "number": t.dieu} if t.dieu else None,
                                "clause": {"id": None, "number": t.khoan} if t.khoan else None,
                                "point": {"id": None, "number": t.diem} if t.diem else None
                            },
                            "target_level": _target_level_cua(t),
                            "replacement_level": None,
                            "replacement_path": None
                        } for t in act["targets"]]
                    else:
                        mapped_targets = match_targets(act["targets"], repl_tree, root_lvl)

                    act_targets = []
                    for m in mapped_targets:
                        build_ids_for_context(target_so_hieu, m["target_context"])
                        p_ctx = m["target_context"].get("point")
                        c_ctx = m["target_context"].get("clause")
                        a_ctx = m["target_context"].get("article")
                        t_unit = (p_ctx.get("id") if p_ctx else None) or (c_ctx.get("id") if c_ctx else None) or (a_ctx.get("id") if a_ctx else None) or m["target_unit_mock"].target_id()
                        act_targets.append({
                            "target_unit": t_unit,
                            "target_context": m["target_context"],
                            "target_level": m["target_level"],
                            "replacement_level": m["replacement_level"],
                            "replacement_path": m["replacement_path"]
                        })
                
                first_existing = act["targets"][0] if act.get("targets") else None
                created_units = (build_created_units(repl_tree, root_lvl, target_so_hieu, first_existing,
                                                     act.get("created_targets"))
                                 if is_insert and repl_tree else [])
                replacement_references = resolve_replacement_references(repl_tree, first_existing, target_so_hieu)
                final_actions.append({
                    "operation": act["operation"],
                    "anchor": act["anchor"],
                    "targets": act_targets,
                    "created_units": created_units,
                    "replacement_references": replacement_references,
                    "text_amendment": act.get("text_amendment"),
                    "appendix_amendment": act.get("appendix_amendment"),
                    "raw_instruction": act.get("raw_instruction", ""),
                    "normalized_instruction": act.get("normalized_instruction", ""),
                    "anchor_span": act.get("anchor_span"),
                    "resolution_status": "RESOLVED" if act_targets else "UNRESOLVED"
                })

            event_items.append({
                "source_unit": source_unit_id,
                "source_point": {
                    "id": source_unit_id,
                    "number": item["source_point"],
                    "implicit": item["implicit"],
                    "instruction": item["instruction"]
                },
                "replacement_root_level": root_lvl if not is_text_or_app else None,
                "replacement_tree": repl_tree if any(a["operation"] != "BAI_BO" and not a.get("text_amendment") and not a.get("appendix_amendment") for a in actions) else None,
                "actions": final_actions
            })
            
        if event_items:
            ev_context = {
                "article": {"id": f"{source_so_hieu.replace('/', '_')}_D{block['so']}", "number": block["so"]} if block["so"] else None,
                "clause": None,
                "point": None
            }
            events.append({
                "source_document": source_so_hieu,
                "target_document": target_so_hieu,
                "source_context": ev_context,
                "items": event_items
            })

    return events

def run_for(source_so_hieu: str, source_file: str, is_omnibus: bool) -> list[dict]:
    events = record_omnibus(source_file, source_so_hieu) if is_omnibus else record_dedicated(source_file, source_so_hieu)
    exporter.save_amendment_index(events, source_so_hieu, PARSED_DIR)
    target_docs = sorted({e["target_document"] for e in events if e["target_document"]})
    return events, target_docs
