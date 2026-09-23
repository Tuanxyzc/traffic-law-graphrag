from unittest.mock import MagicMock

from src.extraction.models import (
    ClauseExtractionResult,
    ContextConditionIE,
    LegalSubjectIE,
    RegulatoryObjectIE,
    SanctionIE,
    SemanticRelationIE,
    VehicleTypeIE,
    ViolationIE,
)
from src.graph.neo4j.ie_importer import Neo4jIEImporter


def test_ie_importer_dry_run():
    importer = Neo4jIEImporter(client=None)

    subj_operator = LegalSubjectIE(
        name="Người điều khiển ô tô", subtype="VEHICLE_OPERATOR"
    )
    subj_csgt = LegalSubjectIE(name="Cảnh sát giao thông", subtype="AUTHORITY")
    veh_car = VehicleTypeIE(name="Xe ô tô", subtype="CAR")
    veh_motor = VehicleTypeIE(name="Xe cơ giới", subtype="CAR")
    obj_signal = RegulatoryObjectIE(
        name="Đèn tín hiệu giao thông", subtype="TRAFFIC_SIGNAL"
    )
    cond_highway = ContextConditionIE(
        description="Trên đường cao tốc", subtype="LOCATION"
    )
    cond_priority = ContextConditionIE(
        description="Xe ưu tiên đang làm nhiệm vụ", subtype="EXCEPTION"
    )
    cond_accident = ContextConditionIE(
        description="Gây tai nạn giao thông", subtype="OTHER"
    )
    sanc_fine = SanctionIE(
        subtype="FINE",
        description="Phạt tiền 18 đến 20 triệu",
        fine_amount="18-20M",
    )

    vio = ViolationIE(
        point_id="DOC_D5_K5_Da",
        description="Không chấp hành tín hiệu đèn giao thông",
        modality="PROHIBITION",
        subject_name="Người điều khiển ô tô",
        applies_to=["Xe ô tô"],
        vehicle_name="Xe ô tô",
        object_names=["Đèn tín hiệu giao thông"],
        condition_descriptions=["Trên đường cao tốc"],
        exception_descriptions=["Xe ưu tiên đang làm nhiệm vụ"],
        cause_descriptions=["Gây tai nạn giao thông"],
        location_descriptions=["Trên đường cao tốc"],
        sanction_descriptions=["Phạt tiền 18 đến 20 triệu"],
        enforced_by="Cảnh sát giao thông",
    )

    sem_subclass = SemanticRelationIE(
        source_name="Xe ô tô",
        relation="SUBCLASS_OF",
        target_name="Xe cơ giới",
    )
    sem_comprises = SemanticRelationIE(
        source_name="Xe cơ giới",
        relation="COMPRISES",
        target_name="Xe ô tô",
    )
    sem_relates = SemanticRelationIE(
        source_name="Đèn tín hiệu giao thông",
        relation="RELATES_TO",
        target_name="Trên đường cao tốc",
    )

    record = ClauseExtractionResult(
        clause_id="DOC_D5_K5",
        subjects=[subj_operator, subj_csgt],
        vehicles=[veh_car, veh_motor],
        objects=[obj_signal],
        conditions=[cond_highway, cond_priority, cond_accident],
        sanctions=[sanc_fine],
        violations=[vio],
        relations=[sem_subclass, sem_comprises, sem_relates],
    )

    stats = importer.import_records([record])
    assert stats["subjects"] == 2
    assert stats["vehicles"] == 2
    assert stats["objects"] == 1
    assert stats["conditions"] == 3
    assert stats["sanctions"] == 1
    assert stats["violations"] == 1
    # Check relationships:
    # COMMITS (1), APPLIES_TO (1), USES_VEHICLE (1), INVOLVES_OBJECT (1),
    # UNDER_CONDITION (1), HAS_EXCEPTION (1), CAUSES (1), LOCATED_AT (1),
    # HAS_SANCTION (1), ENFORCED_BY (1), DEFINES_VIOLATION (1), PROHIBITS (1),
    # SUBCLASS_OF (1), COMPRISES (1), RELATES_TO (1)
    # Total = 15 relationships!
    assert stats["relationships"] == 15


def test_ie_importer_with_mock_session():
    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_client.session.return_value.__enter__.return_value = mock_session

    importer = Neo4jIEImporter(client=mock_client)

    record = ClauseExtractionResult(
        clause_id="DOC_D5_K5",
        subjects=[
            LegalSubjectIE(name="Người điều khiển ô tô", subtype="VEHICLE_OPERATOR")
        ],
        vehicles=[VehicleTypeIE(name="Xe ô tô", subtype="CAR")],
        objects=[],
        conditions=[],
        sanctions=[SanctionIE(subtype="FINE", description="Phạt tiền 18 đến 20 triệu")],
        violations=[
            ViolationIE(
                point_id="DOC_D5_K5_Da",
                description="Vượt đèn đỏ",
                modality="PROHIBITION",
                subject_name="Người điều khiển ô tô",
                vehicle_name="Xe ô tô",
                sanction_descriptions=["Phạt tiền 18 đến 20 triệu"],
            )
        ],
    )

    stats = importer.import_records([record])
    assert stats["subjects"] == 1
    assert stats["violations"] == 1
    assert mock_session.run.call_count >= 1
