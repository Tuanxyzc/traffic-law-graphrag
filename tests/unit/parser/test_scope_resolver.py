from unittest.mock import patch

from src.parser.models import Chuong, Dieu, VanBan
from src.parser.scope_resolver import apply


def test_scope_resolver_mode_all():
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
    with patch(
        "src.parser.scope_resolver.SCOPE_CONFIG",
        {"100/2024/ND-CP": {"scope_mode": "ALL"}},
    ):
        res = apply(vb)
        assert len(res.dieu_khong_chuong) == 1
        assert res.dieu_khong_chuong[0].so == "1"


def test_scope_resolver_mode_selected():
    vb = VanBan(
        so_hieu="100/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[
            Chuong(
                id="C1",
                so="I",
                tieu_de="Chuong 1",
                dieu=[
                    Dieu(
                        id="100_2024_ND-CP_D1",
                        id_cha="C1",
                        so="1",
                        tieu_de="",
                        so_hieu_van_ban="100/2024/ND-CP",
                        noi_dung="",
                        khoan=[],
                    ),
                    Dieu(
                        id="100_2024_ND-CP_D2",
                        id_cha="C1",
                        so="2",
                        tieu_de="",
                        so_hieu_van_ban="100/2024/ND-CP",
                        noi_dung="",
                        khoan=[],
                    ),
                ],
            ),
            Chuong(
                id="C2",
                so="II",
                tieu_de="Chuong 2",
                dieu=[
                    Dieu(
                        id="100_2024_ND-CP_D3",
                        id_cha="C2",
                        so="3",
                        tieu_de="",
                        so_hieu_van_ban="100/2024/ND-CP",
                        noi_dung="",
                        khoan=[],
                    )
                ],
            ),
        ],
        dieu_khong_chuong=[
            Dieu(
                id="100_2024_ND-CP_D4",
                id_cha=None,
                so="4",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[],
            ),
            Dieu(
                id="100_2024_ND-CP_D5",
                id_cha=None,
                so="5",
                tieu_de="",
                so_hieu_van_ban="100/2024/ND-CP",
                noi_dung="",
                khoan=[],
            ),
        ],
    )
    mock_config = {
        "100/2024/ND-CP": {
            "scope_mode": "SELECTED",
            "selected_articles": ["1", "4"],
        }
    }
    with patch("src.parser.scope_resolver.SCOPE_CONFIG", mock_config):
        res = apply(vb)
        assert len(res.chuong) == 1
        assert res.chuong[0].id == "C1"
        assert len(res.chuong[0].dieu) == 1
        assert res.chuong[0].dieu[0].so == "1"
        assert len(res.dieu_khong_chuong) == 1
        assert res.dieu_khong_chuong[0].so == "4"


def test_scope_resolver_fallback_default():
    vb = VanBan(
        so_hieu="UNKNOWN/2024/ND-CP",
        ten="Test",
        loai="NghiDinh",
        chuong=[],
        dieu_khong_chuong=[
            Dieu(
                id="UNKNOWN_D1",
                id_cha=None,
                so="1",
                tieu_de="",
                so_hieu_van_ban="UNKNOWN/2024/ND-CP",
                noi_dung="",
                khoan=[],
            )
        ],
    )
    with patch("src.parser.scope_resolver.SCOPE_CONFIG", {}):
        res = apply(vb)
        assert len(res.dieu_khong_chuong) == 1
