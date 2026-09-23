from unittest.mock import MagicMock

from src.extraction.client import GeminiRESTClient
from src.extraction.grouper import ClauseGrouper
from src.extraction.key_manager import KeyManager
from src.extraction.models import (
    ClauseExtractionResult,
    ContextConditionIE,
    LegalSubjectIE,
    RegulatoryObjectIE,
    SanctionIE,
    SemanticRelationIE,
    VehicleTypeIE,
    ViolationIE,
    slugify,
)
from src.extraction.storage import ExtractionStorage


def test_slugify():
    assert slugify("Người điều khiển xe ô tô") == "nguoi_dieu_khien_xe_o_to"
    assert slugify("Chủ phương tiện!") == "chu_phuong_tien"
    assert slugify("") == ""


def test_pydantic_models():
    subj = LegalSubjectIE(name="Người điều khiển xe ô tô", subtype="VEHICLE_OPERATOR")
    assert subj.id == "subj_nguoi_dieu_khien_xe_o_to"

    veh = VehicleTypeIE(name="Xe ô tô", subtype="CAR")
    assert veh.id == "veh_xe_o_to"

    obj = RegulatoryObjectIE(name="Đèn tín hiệu giao thông", subtype="TRAFFIC_SIGNAL")
    assert obj.id == "obj_den_tin_hieu_giao_thong"

    cond = ContextConditionIE(description="Trên đường cao tốc", subtype="LOCATION")
    assert cond.id == "ctx_tren_duong_cao_toc"

    sanc = SanctionIE(
        subtype="FINE",
        description="Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng",
        fine_amount="18.000.000 - 20.000.000 đồng",
    )

    vio = ViolationIE(
        point_id="168_2024_ND-CP_D5_K5_Da",
        description="Không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
        modality="PROHIBITION",
        subject_name=subj.name,
        applies_to=["Xe ô tô"],
        vehicle_name=veh.name,
        object_names=[obj.name],
        condition_descriptions=[cond.description],
        exception_descriptions=["Xe ưu tiên"],
        cause_descriptions=["Gây tai nạn giao thông"],
        location_descriptions=["Trên đường cao tốc"],
        sanction_descriptions=[sanc.description],
        enforced_by="Cảnh sát giao thông",
    )

    sem_rel = SemanticRelationIE(
        source_name="Xe ô tô con",
        relation="SUBCLASS_OF",
        target_name="Xe cơ giới",
    )

    result = ClauseExtractionResult(
        clause_id="168_2024_ND-CP_D5_K5",
        subjects=[subj],
        vehicles=[veh],
        objects=[obj],
        conditions=[cond],
        sanctions=[sanc],
        violations=[vio],
        relations=[sem_rel],
    )
    assert len(result.violations) == 1
    assert result.violations[0].subject_name == "Người điều khiển xe ô tô"
    assert result.violations[0].vehicle_name == "Xe ô tô"
    assert result.violations[0].object_names == ["Đèn tín hiệu giao thông"]
    assert result.violations[0].modality == "PROHIBITION"
    assert result.violations[0].applies_to == ["Xe ô tô"]
    assert len(result.relations) == 1
    assert result.relations[0].relation == "SUBCLASS_OF"


def test_key_manager_rotation():
    keys = ["key_alpha", "key_beta", "key_gamma"]
    km = KeyManager(api_keys=keys, default_cooldown=10.0)

    # Round-robin checks
    assert km.get_key() == "key_alpha"
    # Mark alpha as rate limited -> should advance to beta
    next_key = km.mark_rate_limited("key_alpha")
    assert next_key == "key_beta"
    assert km.get_key() == "key_beta"

    # Mark beta as rate limited -> should advance to gamma
    next_key = km.mark_rate_limited("key_beta")
    assert next_key == "key_gamma"
    assert km.get_key() == "key_gamma"


def test_clause_grouper():
    semantic_units = [
        {
            "id": "DOC_D5_K1_Da",
            "vi_tri": {
                "dieu": "5",
                "khoan": "1",
                "diem": "a",
                "so_hieu_van_ban": "DOC",
            },
            "tieu_de_dieu": "Xử phạt xe ô tô",
            "noi_dung": "Điểm a: Bấm còi trong đô thị",
        },
        {
            "id": "DOC_D5_K1_Db",
            "vi_tri": {
                "dieu": "5",
                "khoan": "1",
                "diem": "b",
                "so_hieu_van_ban": "DOC",
            },
            "tieu_de_dieu": "Xử phạt xe ô tô",
            "noi_dung": "Điểm b: Không bật đèn xi nhan",
        },
        {
            "id": "DOC_D5_K2",
            "vi_tri": {
                "dieu": "5",
                "khoan": "2",
                "diem": None,
                "so_hieu_van_ban": "DOC",
            },
            "tieu_de_dieu": "Xử phạt xe ô tô",
            "noi_dung": "Khoản 2: Phạt tiền từ 400.000 đồng đến 600.000 đồng",
        },
    ]

    groups = ClauseGrouper.group_semantic_units(semantic_units, "DOC")
    assert len(groups) == 2

    # Group 1: Clause 1 (has 2 points)
    g1 = next(g for g in groups if g.clause_id == "DOC_D5_K1")
    assert len(g1.units) == 2
    prompt_text = g1.to_prompt_text()
    assert "ĐIỀU 5: Xử phạt xe ô tô" in prompt_text
    assert "Điểm a" in prompt_text
    assert "Điểm b" in prompt_text

    # Group 2: Clause 2 (has 1 unit without points)
    g2 = next(g for g in groups if g.clause_id == "DOC_D5_K2")
    assert len(g2.units) == 1


def test_extraction_storage(tmp_path):
    storage = ExtractionStorage(output_dir=tmp_path)
    doc_id = "TEST_DOC"

    assert not storage.is_clause_completed(doc_id, "TEST_DOC_D1_K1")

    res = ClauseExtractionResult(
        clause_id="TEST_DOC_D1_K1",
        subjects=[LegalSubjectIE(name="Người lái xe", subtype="VEHICLE_OPERATOR")],
        vehicles=[VehicleTypeIE(name="Xe ô tô", subtype="CAR")],
        objects=[RegulatoryObjectIE(name="Đèn đỏ", subtype="TRAFFIC_SIGNAL")],
        conditions=[ContextConditionIE(description="Đô thị", subtype="LOCATION")],
        sanctions=[SanctionIE(subtype="FINE", description="Phạt tiền 1 triệu")],
        violations=[
            ViolationIE(
                description="Vượt đèn đỏ",
                subject_name="Người lái xe",
                vehicle_name="Xe ô tô",
                sanction_descriptions=["Phạt tiền 1 triệu"],
            )
        ],
    )

    storage.save_clause_record(doc_id, res)
    assert storage.is_clause_completed(doc_id, "TEST_DOC_D1_K1")

    all_records = storage.get_all_records(doc_id)
    assert len(all_records) == 1
    assert all_records[0].clause_id == "TEST_DOC_D1_K1"


def test_gemini_client_with_429_rotation():
    km = KeyManager(api_keys=["key1", "key2"], default_cooldown=5.0)
    mock_session = MagicMock()

    # First call returns 429, second call returns 200 with valid JSON
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                '{"clause_id": "TEST_D1_K1", '
                                '"subjects": [{"name": "Người đi bộ", "subtype": "PEDESTRIAN"}], '
                                '"vehicles": [], '
                                '"objects": [{"name": "Vạch kẻ đường", "subtype": "TRAFFIC_SIGN"}], '
                                '"conditions": [], '
                                '"sanctions": [{"description": "Cảnh cáo", "subtype": "WARNING"}], '
                                '"violations": [{"description": "Đi sai làn", "subject_name": "Người đi bộ", "sanction_descriptions": ["Cảnh cáo"]}]}'
                            )
                        }
                    ]
                }
            }
        ]
    }

    mock_session.post.side_effect = [mock_resp_429, mock_resp_200]

    client = GeminiRESTClient(key_manager=km, session=mock_session, max_retries=3)
    result = client.extract_clause("TEST_D1_K1", "Nội dung điều khoản...")

    assert result.clause_id == "TEST_D1_K1"
    assert len(result.subjects) == 1
    assert result.subjects[0].name == "Người đi bộ"
    assert len(result.objects) == 1
    assert mock_session.post.call_count == 2
