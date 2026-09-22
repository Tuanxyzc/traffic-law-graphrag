"""Unit tests for Hybrid Retrieval Guardrail & Diversified Entity Balancing."""

from __future__ import annotations

from src.pipeline.pipeline import (
    apply_retrieval_guard,
    classify_chunk_vehicle,
    reciprocal_rank_fusion,
)
from src.rag.models import ChunkMetadata, RetrievedChunk


def _make_chunk(
    chunk_id: str,
    title: str,
    text: str,
    score: float = 0.0,
    raw_text: str | None = None,
) -> RetrievedChunk:
    metadata = ChunkMetadata(
        document_id="168_2024_ND-CP",
        dieu="1",
        tieu_de_dieu=title,
    )
    return RetrievedChunk(
        id=chunk_id,
        text=text,
        raw_text=raw_text or text,
        score=score,
        metadata=metadata,
    )


def test_classify_chunk_vehicle() -> None:
    """Test semantic vehicle classification from title and text."""
    c_car = _make_chunk(
        "car_1",
        "Xử phạt người điều khiển xe ô tô và các loại xe tương tự xe ô tô",
        "Phạt tiền từ 4.000.000 đến 6.000.000 đồng",
    )
    assert classify_chunk_vehicle(c_car) == "xe_o_to"

    c_moto = _make_chunk(
        "moto_1",
        "Xử phạt người điều khiển xe mô tô, xe gắn máy",
        "Phạt tiền từ 800.000 đến 1.000.000 đồng",
    )
    assert classify_chunk_vehicle(c_moto) == "xe_mo_to"

    c_spec = _make_chunk(
        "spec_1",
        "Xử phạt người điều khiển máy kéo, xe máy chuyên dùng",
        "Phạt tiền đối với xe máy chuyên dùng",
    )
    assert classify_chunk_vehicle(c_spec) == "xe_may_chuyen_dung"

    c_bike = _make_chunk(
        "bike_1",
        "Xử phạt người điều khiển xe đạp, xe đạp máy, xe thô sơ",
        "Phạt tiền từ 100.000 đến 200.000 đồng",
    )
    assert classify_chunk_vehicle(c_bike) == "xe_dap"

    c_ped = _make_chunk(
        "ped_1",
        "Xử phạt người đi bộ vi phạm quy tắc giao thông",
        "Phạt tiền từ 60.000 đến 100.000 đồng",
    )
    assert classify_chunk_vehicle(c_ped) == "nguoi_di_bo"

    c_anim = _make_chunk(
        "anim_1",
        "Xử phạt người điều khiển, dẫn dắt vật nuôi, điều khiển xe súc vật kéo",
        "Phạt tiền từ 150.000 đến 250.000 đồng",
    )
    assert classify_chunk_vehicle(c_anim) == "vat_nuoi"

    c_unknown = _make_chunk(
        "unk_1",
        "Hiệu lực thi hành",
        "Nghị định này có hiệu lực từ ngày 01 tháng 01 năm 2025",
    )
    assert classify_chunk_vehicle(c_unknown) is None


def test_apply_retrieval_guard_purges_conflicting_chunks() -> None:
    """Test that chunks violating must-not-have terms while lacking must-have terms are purged."""
    chunk_traffic_light_moto = _make_chunk(
        "light_moto",
        "Xử phạt người điều khiển xe mô tô",
        "Không chấp hành hiệu lệnh của đèn tín hiệu giao thông bị phạt từ 4.000.000 đồng đến 6.000.000 đồng",
    )
    chunk_controller_car = _make_chunk(
        "ctrl_car",
        "Xử phạt người điều khiển xe ô tô",
        "Không chấp hành hiệu lệnh của người điều khiển giao thông bị phạt từ 6.000.000 đồng đến 8.000.000 đồng",
    )
    chunk_controller_moto = _make_chunk(
        "ctrl_moto",
        "Xử phạt người điều khiển xe mô tô",
        "Không chấp hành hiệu lệnh của người điều khiển giao thông bị phạt từ 4.000.000 đồng đến 6.000.000 đồng",
    )
    chunk_sign_bike = _make_chunk(
        "sign_bike",
        "Xử phạt người điều khiển xe đạp",
        "Không chấp hành hiệu lệnh biển báo hiệu, vạch kẻ đường bị phạt 100.000 đồng",
    )

    all_chunks = [
        chunk_traffic_light_moto,
        chunk_controller_car,
        chunk_controller_moto,
        chunk_sign_bike,
    ]

    cleaned = apply_retrieval_guard(
        all_chunks,
        must_have_terms=["người điều khiển giao thông"],
        must_not_have_terms=["đèn tín hiệu", "biển báo hiệu", "vạch kẻ đường"],
    )

    # Only the 2 controller chunks should remain
    assert len(cleaned) == 2
    cleaned_ids = [c.id for c in cleaned]
    assert "ctrl_car" in cleaned_ids
    assert "ctrl_moto" in cleaned_ids
    assert "light_moto" not in cleaned_ids
    assert "sign_bike" not in cleaned_ids


def test_apply_retrieval_guard_fallback_when_no_must_have_matches() -> None:
    """Test graceful fallback returning all chunks when no candidate satisfies must-have terms."""
    chunk1 = _make_chunk("c1", "Title 1", "Một quy định giao thông bất kỳ")
    chunk2 = _make_chunk("c2", "Title 2", "Một quy định khác")
    all_chunks = [chunk1, chunk2]

    # must_have_terms not found in any chunk
    result = apply_retrieval_guard(
        all_chunks,
        must_have_terms=["người điều khiển giao thông"],
        must_not_have_terms=["đèn tín hiệu"],
    )
    assert len(result) == 2
    assert result == all_chunks


def test_apply_retrieval_guard_no_constraints() -> None:
    """Test that chunks are unchanged if no constraints provided."""
    chunk1 = _make_chunk("c1", "Title 1", "Text 1")
    assert apply_retrieval_guard([chunk1], None, None) == [chunk1]
    assert apply_retrieval_guard([], ["term"], ["term2"]) == []


def test_diversified_reciprocal_rank_fusion_balances_target_entities() -> None:
    """Test that diversified RRF balances target vehicle entities in top-k."""
    # Suppose BM25 gives high scores to 3 short bike chunks
    bike_1 = _make_chunk("bike_1", "Xử phạt người đi xe đạp", "Xe đạp vi phạm quy tắc 1")
    bike_2 = _make_chunk("bike_2", "Xử phạt người đi xe đạp", "Xe đạp vi phạm quy tắc 2")
    bike_3 = _make_chunk("bike_3", "Xử phạt người đi xe đạp", "Xe đạp vi phạm quy tắc 3")

    # Moderate score for moto and car
    moto_1 = _make_chunk(
        "moto_1", "Xử phạt người điều khiển xe mô tô", "Xe mô tô không chấp hành hiệu lệnh"
    )
    car_1 = _make_chunk(
        "car_1", "Xử phạt người điều khiển xe ô tô", "Xe ô tô không chấp hành hiệu lệnh"
    )

    # Input list ranked: bike_1, bike_2, bike_3, moto_1, car_1
    ranked_list = [bike_1, bike_2, bike_3, moto_1, car_1]

    # Without target_entities, top-3 would be bike_1, bike_2, bike_3
    standard_top3 = reciprocal_rank_fusion([ranked_list], top_k=3)
    assert [c.id for c in standard_top3] == ["bike_1", "bike_2", "bike_3"]

    # WITH target_entities=["xe_o_to", "xe_mo_to"], car and moto must be selected!
    diversified_top3 = reciprocal_rank_fusion(
        [ranked_list],
        top_k=3,
        target_entities=["xe_o_to", "xe_mo_to"],
    )
    div_ids = [c.id for c in diversified_top3]

    assert len(diversified_top3) == 3
    assert "car_1" in div_ids
    assert "moto_1" in div_ids
    # The 3rd slot should be filled by the highest remaining candidate (bike_1)
    assert "bike_1" in div_ids
