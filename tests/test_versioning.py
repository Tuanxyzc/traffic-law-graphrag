import pytest 
from datetime import date
from src.versioning.version_builder import VersionBuilder
from src.versioning.version_models import CanonicalProvision, ProvisionVersion
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver
from src.versioning.version_validator import validate_all_versions, validate_version_timeline

class MockNode:
    def __init__(self, id, label, properties):
        self.id = id
        self.label = label
        self.properties = properties

@pytest.fixture
def mock_structure():
    return {
        "doc_1": [
            MockNode(id="doc_1_D1", label="Article", properties={"number": "1", "text": "Old text 1"}),
            MockNode(id="doc_1_D2", label="Article", properties={"number": "2", "text": "Old text 2"})
        ]
    }

@pytest.fixture
def mock_effective_rules():
    return {
        "doc_1": [{"rule_type": "GENERAL", "effective_from": "2020-01-01"}],
        "doc_2": [{"rule_type": "GENERAL", "effective_from": "2022-01-01"}]
    }

@pytest.fixture
def mock_amendment_actions():
    return [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_1",
            "operation": "SUA_DOI",
            "targets": [{"target_unit": "doc_1_D1", "replacement_path": ["articles", 0]}],
            "replacement_tree": {"articles": [{"number": "1", "text": "New text 1"}]}
        },
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D2",
            "action_id": "doc_2_D2_SU_ACTION_1",
            "operation": "BAI_BO",
            "targets": [{"target_unit": "doc_1_D2"}]
        },
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D3",
            "action_id": "doc_2_D3_SU_ACTION_1",
            "operation": "BO_SUNG",
            "created_units": [{"unit_id": "doc_1_D3", "unit_level": "ARTICLE", "number": "3"}],
            "replacement_tree": {"articles": [{"number": "3", "text": "Brand new text 3"}]}
        }
    ]

def test_version_builder_full_lifecycle(mock_structure, mock_amendment_actions, mock_effective_rules):
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=mock_amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver()
    )
    provisions, versions = builder.build()
    
    # Kiểm tra Canonical Provisions đã được tạo đủ
    assert "doc_1_D1" in provisions
    assert "doc_1_D2" in provisions
    assert "doc_1_D3" in provisions # Do lệnh BO_SUNG tự sinh ra
    
    # 1. Kiểm tra lệnh SUA_DOI (D1)
    # Phải có 2 phiên bản: V1 (cũ, đã bị chốt) và V2 (mới, đang hiện hành)
    assert len(versions["doc_1_D1"]) == 2
    v1 = versions["doc_1_D1"][0]
    v2 = versions["doc_1_D1"][1]
    
    assert v1.valid_from == "2020-01-01"
    assert v1.valid_to == "2022-01-01"
    assert v1.is_current is False
    assert v1.content["text"] == "Old text 1"
    
    assert v2.valid_from == "2022-01-01"
    assert v2.valid_to is None
    assert v2.is_current is True
    assert v2.content["text"] == "New text 1"
    
    # 2. Kiểm tra lệnh BAI_BO (D2)
    # Chỉ có 1 phiên bản V1, và đã bị chốt ngày kết thúc, không còn hiện hành
    assert len(versions["doc_1_D2"]) == 1
    v1 = versions["doc_1_D2"][0]
    assert v1.valid_from == "2020-01-01"
    assert v1.valid_to == "2022-01-01"
    assert v1.is_current is False
    
    # 3. Kiểm tra lệnh BO_SUNG (D3)
    # Tạo ra V1 mới toanh, bắt đầu từ 2022
    assert len(versions["doc_1_D3"]) == 1
    v1 = versions["doc_1_D3"][0]
    assert v1.valid_from == "2022-01-01"
    assert v1.valid_to is None
    assert v1.is_current is True
    assert v1.content["text"] == "Brand new text 3"
    
    # 4. Kiểm tra Validator: Toàn bộ timeline phải liền mạch, không lỗi
    assert validate_all_versions(versions) is True

def test_validator_detects_gap():
    # Giả lập một lỗi đứt gãy dòng thời gian (2021 -> 2022 trống)
    versions = [
        ProvisionVersion(version_id="1", canonical_provision_id="P1", valid_from="2020-01-01", valid_to="2021-01-01", content={}, is_current=False, produced_by=None),
        ProvisionVersion(version_id="2", canonical_provision_id="P1", valid_from="2022-01-01", valid_to=None, content={}, is_current=True, produced_by=None)
    ]
    with pytest.raises(ValueError, match="Timeline gap/overlap: P1"):
        validate_version_timeline("P1", versions)

def test_validator_detects_multiple_current():
    # Giả lập lỗi có tới 2 phiên bản cùng đánh dấu là current
    versions = [
        ProvisionVersion(version_id="1", canonical_provision_id="P1", valid_from="2020-01-01", valid_to="2021-01-01", content={}, is_current=True, produced_by=None),
        ProvisionVersion(version_id="2", canonical_provision_id="P1", valid_from="2021-01-01", valid_to=None, content={}, is_current=True, produced_by=None)
    ]
    with pytest.raises(ValueError, match="Multiple current versions: P1"):
        validate_version_timeline("P1", versions)

def test_validator_detects_empty():
    with pytest.raises(ValueError, match="No versions"):
        validate_version_timeline("P1", [])
