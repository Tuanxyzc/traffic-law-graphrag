from datetime import date

import pytest

from src.effective.effective_engine import evaluate_unit


# Dummy data setup
@pytest.fixture
def sample_rules():
    return [
        {
            "rule_id": "rule_general_old",
            "rule_type": "GENERAL",
            "effective_from": "2020-01-01",
            "effective_to": "2023-01-01",
            "source_unit": "decree_100",
        },
        {
            "rule_id": "rule_general_current",
            "rule_type": "GENERAL",
            "effective_from": "2023-01-01",
            "effective_to": "2026-01-01",
            "source_unit": "decree_123",
        },
        {
            "rule_id": "rule_explicit_target_A",
            "rule_type": "EXPLICIT",
            "targets": [{"unit_id": "target_A"}],
            "effective_from": "2024-01-01",
            "effective_to": None,  # Active indefinitely
            "source_unit": "circular_24",
        },
        {
            "rule_id": "rule_explicit_future",
            "rule_type": "EXPLICIT",
            "targets": [{"unit_id": "target_B"}],
            "effective_from": "2025-01-01",
            "effective_to": None,
            "source_unit": "future_law",
        },
        {
            "rule_id": "rule_external",
            "rule_type": "EXTERNAL_RULE",
            "targets": [{"unit_id": "target_C"}],
            "external_basis": "some_external_document_reference",
            "source_unit": "external_source",
        },
        {
            "rule_id": "rule_expired",
            "rule_type": "EXPLICIT",
            "targets": [{"unit_id": "target_D"}],
            "effective_from": "2018-01-01",
            "effective_to": "2020-01-01",
            "source_unit": "old_law",
        },
    ]


def test_evaluate_unit_unknown(sample_rules):
    # Trỏ vào một target_unit không có rule EXPLICIT nào,
    # VÀ giả sử không có GENERAL rules (ở đây ta truyền list rỗng để test dễ)
    from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

    resolver = CanonicalIDResolver()
    result = evaluate_unit([], "target_Z", date(2024, 6, 1), resolver)
    assert result.status == "UNKNOWN"
    assert result.rule_id is None


def test_evaluate_unit_external(sample_rules):
    # Chứa rule EXTERNAL_RULE
    from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

    resolver = CanonicalIDResolver()
    result = evaluate_unit(sample_rules, "target_C", date(2024, 6, 1), resolver)
    assert result.status == "EXTERNAL"
    assert result.rule_id == "rule_external"
    assert result.external_basis == "some_external_document_reference"


def test_evaluate_unit_active_general(sample_rules):
    # target_Z không có EXPLICIT rule, sẽ match GENERAL rule
    # 2024-06-01 nằm trong khoảng của rule_general_current (2023 - 2026)
    from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

    resolver = CanonicalIDResolver()
    result = evaluate_unit(sample_rules, "target_Z", date(2024, 6, 1), resolver)
    assert result.status == "ACTIVE"
    assert result.rule_id == "rule_general_current"


def test_evaluate_unit_active_explicit_overrides_general(sample_rules):
    # target_A có EXPLICIT rule từ 2024-01-01
    # as_of_date = 2024-06-01 -> Cả rule_general_current và rule_explicit_target_A đều active
    # Nhưng EXPLICIT ưu tiên hơn GENERAL
    from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

    resolver = CanonicalIDResolver()
    result = evaluate_unit(sample_rules, "target_A", date(2024, 6, 1), resolver)
    assert result.status == "ACTIVE"
    assert result.rule_id == "rule_explicit_target_A"


def test_evaluate_unit_not_yet_effective(sample_rules):
    # target_B có rule EXPLICIT bắt đầu từ 2025
    # Tại thời điểm 2024-06-01, rule này chưa có hiệu lực.
    # LƯU Ý: Với code hiện tại, target_B cũng bị ảnh hưởng bởi GENERAL rule (rule_general_current)
    # Tuy nhiên, nếu ta chỉ test các rule cụ thể cho target_B (không truyền general rule)
    filtered_rules = [r for r in sample_rules if r["rule_type"] != "GENERAL"]

    from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

    resolver = CanonicalIDResolver()
    result = evaluate_unit(filtered_rules, "target_B", date(2024, 6, 1), resolver)
    assert result.status == "NOT_YET_EFFECTIVE"
    assert result.effective_from == "2025-01-01"


def test_evaluate_unit_inactive(sample_rules):
    # target_D có rule hết hạn từ 2020.
    # Bỏ general rules đi để test rành mạch trạng thái INACTIVE của target_D
    filtered_rules = [r for r in sample_rules if r["rule_type"] != "GENERAL"]

    from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

    resolver = CanonicalIDResolver()
    result = evaluate_unit(filtered_rules, "target_D", date(2024, 6, 1), resolver)
    assert result.status == "INACTIVE"
    assert result.rule_id is None


def test_evaluate_unit_multiple_explicit_active(sample_rules):
    # Thêm 1 rule explicit mới đè lên rule_explicit_target_A
    rules_with_multiple_explicit = sample_rules + [
        {
            "rule_id": "rule_explicit_target_A_newer",
            "rule_type": "EXPLICIT",
            "targets": [{"unit_id": "target_A"}],
            "effective_from": "2024-05-01",
            "effective_to": None,
            "source_unit": "decree_new",
        }
    ]
    # Ngày test là 2024-06-01, cả 2 rule explicit đều thoả mãn (>= 2024-01-01 và >= 2024-05-01)
    # Hàm select_effective_rule sẽ ưu tiên rule có effective_from gần đây nhất
    from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

    resolver = CanonicalIDResolver()
    result = evaluate_unit(
        rules_with_multiple_explicit, "target_A", date(2024, 6, 1), resolver
    )
    assert result.status == "ACTIVE"
    assert result.rule_id == "rule_explicit_target_A_newer"
