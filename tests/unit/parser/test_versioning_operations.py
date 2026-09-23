import pytest

from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver
from src.versioning.version_builder import VersionBuilder


class MockNode:
    def __init__(self, id, label, properties):
        self.id = id
        self.label = label
        self.properties = properties


@pytest.fixture
def mock_structure():
    return {
        "doc_1": [
            MockNode(
                id="doc_1_D1",
                label="Article",
                properties={
                    "number": "1",
                    "text": "Người điều khiển xe ô tô phải có bằng lái.",
                },
            ),
            MockNode(
                id="doc_1_D2",
                label="Article",
                properties={
                    "number": "2",
                    "text": "Người lái xe trực tiếp điều khiển phương tiện.",
                },
            ),
            MockNode(
                id="doc_1_D3",
                label="Article",
                properties={
                    "number": "3",
                    "text": "phải chấp hành hiệu lệnh của cảnh sát giao thông.",
                },
            ),
        ]
    }


@pytest.fixture
def mock_effective_rules():
    return {
        "doc_1": [{"rule_type": "GENERAL", "effective_from": "2020-01-01"}],
        "doc_2": [{"rule_type": "GENERAL", "effective_from": "2022-01-01"}],
    }


def test_version_builder_thay_the_text(mock_structure, mock_effective_rules):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_1",
            "action": {
                "operation": "THAY_THE_TEXT",
                "targets": [{"target_unit": "doc_1_D1"}],
                "text_amendment": {
                    "unit_type": "PHRASE",
                    "old_text": "bằng lái",
                    "new_text": "giấy phép lái xe",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()

    assert "doc_1_D1" in provisions
    assert len(versions["doc_1_D1"]) == 2
    v1 = versions["doc_1_D1"][0]
    v2 = versions["doc_1_D1"][1]

    assert v1.is_current is False
    assert v1.valid_to == "2022-01-01"
    assert v1.content["text"] == "Người điều khiển xe ô tô phải có bằng lái."

    assert v2.is_current is True
    assert v2.valid_from == "2022-01-01"
    assert v2.content["text"] == "Người điều khiển xe ô tô phải có giấy phép lái xe."
    assert v2.produced_by == "doc_2_D1_SU_ACTION_1"


def test_version_builder_bo_sung_text_after(mock_structure, mock_effective_rules):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_2",
            "action": {
                "operation": "BO_SUNG_TEXT",
                "targets": [{"target_unit": "doc_1_D1"}],
                "text_amendment": {
                    "unit_type": "PHRASE",
                    "text": "hoặc xe máy chuyên dùng",
                    "relation": "AFTER",
                    "anchor_text": "xe ô tô",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()

    v2 = versions["doc_1_D1"][1]
    assert (
        v2.content["text"]
        == "Người điều khiển xe ô tô hoặc xe máy chuyên dùng phải có bằng lái."
    )


def test_version_builder_bo_sung_text_before(mock_structure, mock_effective_rules):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_3",
            "action": {
                "operation": "BO_SUNG_TEXT",
                "targets": [{"target_unit": "doc_1_D3"}],
                "text_amendment": {
                    "unit_type": "PHRASE",
                    "text": "Người tham gia giao thông",
                    "relation": "BEFORE",
                    "anchor_text": "phải chấp hành",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()

    v2 = versions["doc_1_D3"][1]
    assert (
        v2.content["text"]
        == "Người tham gia giao thông phải chấp hành hiệu lệnh của cảnh sát giao thông."
    )


def test_version_builder_bai_bo_text(mock_structure, mock_effective_rules):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_4",
            "action": {
                "operation": "BAI_BO_TEXT",
                "targets": [{"target_unit": "doc_1_D2"}],
                "text_amendment": {
                    "unit_type": "WORD",
                    "text": "trực tiếp",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()

    v2 = versions["doc_1_D2"][1]
    assert v2.content["text"] == "Người lái xe điều khiển phương tiện."


def test_version_builder_thay_the_phu_luc(mock_structure, mock_effective_rules):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_5",
            "action": {
                "operation": "THAY_THE_PHU_LUC",
                "targets": [{"target_unit": "doc_1_PLI"}],
                "appendix_amendment": {
                    "old_appendix": {"number": "I", "document": "doc_1"},
                    "new_appendix": {"number": "II", "document": "doc_2"},
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()

    assert "doc_1_PLI" in provisions
    assert provisions["doc_1_PLI"].level == "APPENDIX"
    assert len(versions["doc_1_PLI"]) == 2
    v1 = versions["doc_1_PLI"][0]
    v2 = versions["doc_1_PLI"][1]

    assert v1.is_current is False
    assert v1.valid_to == "2022-01-01"
    assert v1.content["number"] == "I"

    assert v2.is_current is True
    assert v2.valid_from == "2022-01-01"
    assert v2.content["number"] == "II"
    assert v2.content["source_document"] == "doc_2"


def test_version_builder_warn_and_skip_missing_old_text(
    mock_structure, mock_effective_rules
):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_ERR",
            "action": {
                "operation": "THAY_THE_TEXT",
                "targets": [{"target_unit": "doc_1_D1"}],
                "text_amendment": {
                    "unit_type": "PHRASE",
                    "old_text": "chuoi khong he ton tai",
                    "new_text": "abc",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()
    # Unmatched target is skipped with warning, so only V1 remains
    assert len(versions["doc_1_D1"]) == 1
    assert versions["doc_1_D1"][0].is_current is True


def test_version_builder_warn_and_skip_missing_anchor(
    mock_structure, mock_effective_rules
):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_ERR2",
            "action": {
                "operation": "BO_SUNG_TEXT",
                "targets": [{"target_unit": "doc_1_D1"}],
                "text_amendment": {
                    "unit_type": "PHRASE",
                    "text": "abc",
                    "relation": "AFTER",
                    "anchor_text": "anchor khong ton tai",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()
    assert len(versions["doc_1_D1"]) == 1


def test_version_builder_warn_and_skip_missing_delete_text(
    mock_structure, mock_effective_rules
):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_ERR3",
            "action": {
                "operation": "BAI_BO_TEXT",
                "targets": [{"target_unit": "doc_1_D1"}],
                "text_amendment": {
                    "unit_type": "WORD",
                    "text": "tu ngu khong co",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()
    assert len(versions["doc_1_D1"]) == 1


def test_version_builder_fail_fast_target_not_found(
    mock_structure, mock_effective_rules
):
    amendment_actions = [
        {
            "source_document": "doc_2",
            "source_unit": "doc_2_D1",
            "action_id": "doc_2_D1_SU_ACTION_ERR4",
            "action": {
                "operation": "THAY_THE_TEXT",
                "targets": [{"target_unit": "doc_1_NON_EXISTENT"}],
                "text_amendment": {
                    "unit_type": "WORD",
                    "old_text": "abc",
                    "new_text": "xyz",
                },
            },
        }
    ]
    builder = VersionBuilder(
        structure_nodes_by_document=mock_structure,
        amendment_actions=amendment_actions,
        effective_rules_by_document=mock_effective_rules,
        resolver=CanonicalIDResolver(),
    )
    with pytest.raises(ValueError, match="THAY_THE_TEXT target khong ton tai"):
        builder.build()
