import json
from pathlib import Path

from src.parser.models import (
    Chuong,
    Diem,
    Dieu,
    DonViNguNghia,
    Khoan,
    ThamChieu,
    VanBan,
    ViTri,
)
from src.parser.validator import (
    build_global_index,
    validate,
    validate_amendment,
    validate_article_number,
    validate_clause,
    validate_duplicate,
    validate_duplicate_semantic_unit,
    validate_invalid_reference,
    validate_missing_parent,
    validate_point,
    validate_reference,
)


def test_validate_article_number_detects_gap():
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[
            Dieu(
                id="100_2024_ND-CP_D1",
                id_cha=None,
                so="1",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[],
            ),
            Dieu(
                id="100_2024_ND-CP_D3",
                id_cha=None,
                so="3",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[],
            ),
        ],
    )
    warnings = validate_article_number(vb)
    assert len(warnings) == 1
    assert "Số Điều bị thiếu" in warnings[0]


def test_validate_article_number_passes_continuous():
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[
            Dieu(
                id="100_2024_ND-CP_D1",
                id_cha=None,
                so="1",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[],
            ),
            Dieu(
                id="100_2024_ND-CP_D2",
                id_cha=None,
                so="2",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[],
            ),
        ],
    )
    assert validate_article_number(vb) == []


def test_validate_clause_detects_duplicates():
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[
            Dieu(
                id="100_2024_ND-CP_D1",
                id_cha=None,
                so="1",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[
                    Khoan(
                        id="100_2024_ND-CP_D1_K1",
                        id_cha="100_2024_ND-CP_D1",
                        so="1",
                        noi_dung="",
                        diem=[],
                    ),
                    Khoan(
                        id="100_2024_ND-CP_D1_K1_dup",
                        id_cha="100_2024_ND-CP_D1",
                        so="1",
                        noi_dung="",
                        diem=[],
                    ),
                ],
            ),
        ],
    )
    warnings = validate_clause(vb)
    assert len(warnings) == 1
    assert "TRÙNG số" in warnings[0]


def test_validate_point_detects_duplicates():
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[
            Dieu(
                id="100_2024_ND-CP_D1",
                id_cha=None,
                so="1",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[
                    Khoan(
                        id="100_2024_ND-CP_D1_K1",
                        id_cha="100_2024_ND-CP_D1",
                        so="1",
                        noi_dung="",
                        diem=[
                            Diem(
                                id="D1",
                                id_cha="100_2024_ND-CP_D1_K1",
                                so="a",
                                noi_dung="",
                            ),
                            Diem(
                                id="D2",
                                id_cha="100_2024_ND-CP_D1_K1",
                                so="a",
                                noi_dung="",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    warnings = validate_point(vb)
    assert len(warnings) == 1
    assert "Điểm bị TRÙNG số" in warnings[0]


def test_validate_duplicate_ids():
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[
            Dieu(
                id="DUP_ID",
                id_cha=None,
                so="1",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[
                    Khoan(id="DUP_ID", id_cha="DUP_ID", so="1", noi_dung="", diem=[]),
                ],
            ),
        ],
    )
    warnings = validate_duplicate(vb)
    assert len(warnings) == 1
    assert "TRÙNG id" in warnings[0]


def test_validate_missing_parent():
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[
            Chuong(
                id="100_2024_ND-CP_C1",
                so="I",
                tieu_de="Chuong I",
                dieu=[
                    Dieu(
                        id="100_2024_ND-CP_D1",
                        id_cha="NON_EXISTENT_PARENT",
                        so="1",
                        tieu_de="",
                        so_hieu_van_ban="100/2024/ND-CP",
                        noi_dung="",
                        khoan=[],
                    )
                ],
            )
        ],
        dieu_khong_chuong=[],
    )
    warnings = validate_missing_parent(vb)
    assert len(warnings) == 1
    assert "không tồn tại" in warnings[0]


def test_validate_reference_missing_doc():
    unit = DonViNguNghia(
        id="U1",
        vi_tri=ViTri("1", None, None, "100/2024/ND-CP"),
        hanh_dong="GIU_NGUYEN",
        level=3,
        doi_tuong=[],
        tham_chieu=[
            ThamChieu(
                loai="van_ban_nay",
                van_ban_goc="luat nay",
                gia_tri_xac_dinh=ViTri("5", None, None, None),
                quan_he="THAM_CHIEU",
            )
        ],
        noi_dung_goc="",
        noi_dung_chuan_hoa="",
        noi_dung="",
    )
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[],
    )
    warnings = validate_reference(vb, [unit])
    assert len(warnings) == 1
    assert "không resolve được văn bản" in warnings[0]


def test_validate_duplicate_semantic_unit():
    u1 = DonViNguNghia(
        id="U1",
        vi_tri=ViTri("1", None, None, "100/2024/ND-CP"),
        hanh_dong="GIU_NGUYEN",
        level="ARTICLE",
        doi_tuong=[],
        tham_chieu=[],
        noi_dung_goc="Noi dung A",
        noi_dung_chuan_hoa="Noi dung A",
        noi_dung="Noi dung A",
    )
    u2 = DonViNguNghia(
        id="U2",
        vi_tri=ViTri("2", None, None, "100/2024/ND-CP"),
        hanh_dong="GIU_NGUYEN",
        level="ARTICLE",
        doi_tuong=[],
        tham_chieu=[],
        noi_dung_goc="Noi dung A",
        noi_dung_chuan_hoa="Noi dung A",
        noi_dung="Noi dung A",
    )
    warnings = validate_duplicate_semantic_unit([u1, u2])
    assert len(warnings) == 1
    assert "trùng nội dung" in warnings[0]


def test_validate_invalid_reference():
    unit = DonViNguNghia(
        id="U1",
        vi_tri=ViTri("1", None, None, "100/2024/ND-CP"),
        hanh_dong="GIU_NGUYEN",
        level=3,
        doi_tuong=[],
        tham_chieu=[
            ThamChieu(
                loai="cheo_van_ban",
                van_ban_goc="Dieu 99 Luat 35",
                gia_tri_xac_dinh=ViTri("99", None, None, "35/2024/QH15"),
                quan_he="THAM_CHIEU",
            )
        ],
        noi_dung_goc="",
        noi_dung_chuan_hoa="",
        noi_dung="",
    )
    index = {"35/2024/QH15": {"35_2024_QH15_D1", "35_2024_QH15_D2"}}
    warnings = validate_invalid_reference([unit], index)
    assert len(warnings) == 1
    assert "KHÔNG tồn tại" in warnings[0]


def test_build_global_index_and_composite_validate(tmp_path: Path):
    doc_json = tmp_path / "35_2024_QH15_structure.json"
    doc_json.write_text(
        json.dumps(
            {
                "so_hieu": "35/2024/QH15",
                "dieu_khong_chuong": [
                    {
                        "id": "35_2024_QH15_D1",
                        "khoan": [{"id": "35_2024_QH15_D1_K1", "diem": []}],
                    }
                ],
                "chuong": [],
            }
        ),
        encoding="utf-8",
    )
    corrupt_json = tmp_path / "corrupt_structure.json"
    corrupt_json.write_text("{corrupt: json}", encoding="utf-8")

    index = build_global_index(str(tmp_path))
    assert "35/2024/QH15" in index
    assert "35_2024_QH15_D1" in index["35/2024/QH15"]

    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[
            Dieu(
                id="100_2024_ND-CP_D1",
                id_cha=None,
                so="1",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[],
            )
        ],
    )
    warnings = validate(vb, units=[], index_so_hieu_to_ids=index)
    assert warnings == []


def test_validate_amendment():
    events = [
        {
            "items": [
                {
                    "actions": [
                        {
                            "operation": "SUA_DOI",
                            "targets": [
                                {
                                    "target_unit": "35_2024_QH15_D1",
                                    "replacement_path": None,
                                    "target_level": "ARTICLE",
                                    "replacement_level": "CLAUSE",
                                },
                                {
                                    "target_unit": "35_2024_QH15_D1",
                                    "replacement_path": "path/1",
                                    "target_level": "ARTICLE",
                                    "replacement_level": "ARTICLE",
                                },
                            ],
                        },
                        {
                            "operation": "BAI_BO",
                            "targets": [
                                {
                                    "target_unit": "35_2024_QH15_D2",
                                    "replacement_path": "should_not_exist",
                                }
                            ],
                        },
                    ]
                }
            ]
        }
    ]
    warnings = validate_amendment(events)
    assert len(warnings) >= 3
