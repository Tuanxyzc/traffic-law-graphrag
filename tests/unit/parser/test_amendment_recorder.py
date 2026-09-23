import pytest

from src.parser.amendment_recorder import (
    _target_level_cua,
    build_replacement_tree_and_root,
    is_non_action_container,
    parse_actions,
    resolve_replacement_references,
)
from src.parser.models import ViTri


def test_determine_root_level():
    assert _target_level_cua(ViTri(dieu="1", khoan="2", diem="a")) == "POINT"
    assert _target_level_cua(ViTri(dieu="1", khoan="2", diem=None)) == "CLAUSE"
    assert _target_level_cua(ViTri(dieu="1", khoan=None, diem=None)) == "ARTICLE"


@pytest.mark.parametrize(
    "quote,level,expected_root",
    [
        ("a) Nội dung điểm a", "POINT", "POINT"),
        ("1. Nội dung khoản 1\na) Điểm a", "CLAUSE", "CLAUSE"),
        ("Điều 1. Phạm vi điều chỉnh\n1. Khoản 1", "ARTICLE", "ARTICLE"),
    ],
)
def test_build_replacement_tree_and_root(quote, level, expected_root):
    tree, root = build_replacement_tree_and_root(quote, level)
    assert root == expected_root
    assert isinstance(tree, dict)


def test_parse_actions_thay_the_text():
    instruction = (
        'Thay thế cụm từ "Bộ Công an" bằng cụm từ "Bộ Giao thông vận tải" tại Điều 5'
    )
    actions = parse_actions(instruction, "100/2024/ND-CP")
    assert len(actions) == 1
    act = actions[0]
    assert act["operation"] == "THAY_THE_TEXT"
    assert act["text_amendment"]["old_text"] == "Bộ Công an"
    assert act["text_amendment"]["new_text"] == "Bộ Giao thông vận tải"


def test_parse_actions_bo_sung_text():
    instruction = 'Bổ sung cụm từ "hoặc xe máy chuyên dùng" vào sau cụm từ "xe ô tô" tại khoản 1 Điều 5'
    actions = parse_actions(instruction, "100/2024/ND-CP")
    assert len(actions) == 1
    act = actions[0]
    assert act["operation"] == "BO_SUNG_TEXT"
    assert act["text_amendment"]["text"] == "hoặc xe máy chuyên dùng"
    assert act["text_amendment"]["relation"] == "AFTER"
    assert act["text_amendment"]["anchor_text"] == "xe ô tô"


def test_parse_actions_bai_bo_text():
    instruction = 'Bãi bỏ cụm từ "trực tiếp" tại điểm a khoản 2 Điều 10'
    actions = parse_actions(instruction, "100/2024/ND-CP")
    assert len(actions) == 1
    act = actions[0]
    assert act["operation"] == "BAI_BO_TEXT"
    assert act["text_amendment"]["text"] == "trực tiếp"


def test_parse_actions_thay_the_phu_luc():
    instruction = "Thay thế Phụ lục I ban hành kèm theo Nghị định số 100/2024/NĐ-CP bằng Phụ lục II"
    actions = parse_actions(instruction, "100/2024/ND-CP")
    assert len(actions) == 1
    act = actions[0]
    assert act["operation"] == "THAY_THE_PHU_LUC"
    assert act["appendix_amendment"]["old_appendix"]["number"] == "I"
    assert act["appendix_amendment"]["new_appendix"]["number"] == "II"


def test_parse_actions_bo_sung_with_anchor():
    instruction = "Bổ sung điểm d vào sau điểm c khoản 1 Điều 5 như sau:"
    actions = parse_actions(instruction, "100/2024/ND-CP")
    assert len(actions) == 1
    act = actions[0]
    assert act["operation"] == "BO_SUNG"
    assert act["anchor"] is not None
    assert act["anchor"]["relation"] == "AFTER"


def test_is_non_action_container():
    item = {"source_point": None, "source_clause": None}
    assert (
        is_non_action_container(item, "Điều 1. Sửa đổi, bổ sung một số điều...") is True
    )


def test_resolve_replacement_references():
    texts = ["Căn cứ theo quy định tại Điều 10 Nghị định số 100/2024/NĐ-CP"]
    target = ViTri(dieu="5", khoan="1", diem=None)
    refs = resolve_replacement_references(texts, target, "100/2024/ND-CP")
    assert isinstance(refs, list)


def test_build_ids_for_context():
    from src.parser.amendment_recorder import build_ids_for_context

    ctx = {
        "article": {"number": "5"},
        "clause": {"number": "1"},
        "point": {"number": "a"},
    }
    build_ids_for_context("100/2024/ND-CP", ctx)
    assert ctx["article"]["id"] == "100_2024_ND-CP_D5"
    assert ctx["clause"]["id"] == "100_2024_ND-CP_D5_K1"
    assert ctx["point"]["id"] == "100_2024_ND-CP_D5_K1_Da"


def test_parse_amendment_workflow_and_split_top_level():
    from src.parser.amendment_recorder import (
        _split_top_level_raw,
        parse_amendment_workflow,
    )
    from src.parser.normalize import DoanVan

    paragraphs = [
        DoanVan(text="Điều 1. Sửa đổi một số điều", dam=True),
        DoanVan(text="1. Sửa đổi khoản 1 Điều 5 như sau:", dam=False),
        DoanVan(text="“1. Nội dung sửa đổi”", dam=False),
    ]
    blocks = _split_top_level_raw(paragraphs)
    assert len(blocks) == 1
    assert blocks[0]["so"] == "1"

    items = parse_amendment_workflow(paragraphs[1:])
    assert len(items) >= 1


def test_parse_actions_compound_bai_bo_text():
    instruction = (
        '12. Bỏ cụm từ "giấy chứng nhận kiểm định an toàn kỹ thuật và bảo vệ môi trường" '
        'tại điểm b, điểm d khoản 7 Điều 32, cụm từ "điểm e, điểm g khoản 7;" tại điểm đ khoản 18 Điều 32.'
    )
    actions = parse_actions(instruction, "168/2024/ND-CP")
    assert len(actions) == 2

    # Action 1: removes giấy chứng nhận kiểm định from Db, Dd K7 D32
    act1 = actions[0]
    assert act1["operation"] == "BAI_BO_TEXT"
    assert (
        act1["text_amendment"]["text"]
        == "giấy chứng nhận kiểm định an toàn kỹ thuật và bảo vệ môi trường"
    )
    assert len(act1["targets"]) == 2
    assert (
        act1["targets"][0].diem == "b"
        and act1["targets"][0].khoan == "7"
        and act1["targets"][0].dieu == "32"
    )
    assert (
        act1["targets"][1].diem == "d"
        and act1["targets"][1].khoan == "7"
        and act1["targets"][1].dieu == "32"
    )

    # Action 2: removes điểm e, điểm g khoản 7; from Dđ K18 D32
    act2 = actions[1]
    assert act2["operation"] == "BAI_BO_TEXT"
    assert act2["text_amendment"]["text"] == "điểm e, điểm g khoản 7;"
    assert len(act2["targets"]) == 1
    assert (
        act2["targets"][0].diem == "đ"
        and act2["targets"][0].khoan == "18"
        and act2["targets"][0].dieu == "32"
    )
