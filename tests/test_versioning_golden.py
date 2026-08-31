import json
import os
from pathlib import Path

import pytest

from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver
from src.versioning.version_builder import VersionBuilder
from src.versioning.version_validator import validate_all_versions


class NodeAdapter:
    """Class bọc (wrapper) để biến JSON Semantic Unit thành dạng Object có .id, .label, .properties
    đáp ứng được interface mà VersionBuilder yêu cầu."""

    def __init__(self, item):
        self.id = item["id"]
        # Phân loại level (2: Article, 3: Clause, 4: Point)
        level_map = {2: "Article", 3: "Clause", 4: "Point"}
        self.label = level_map.get(item["level"], "Unknown")
        self.properties = item

        # Mapping số hiệu (number) từ vị trí để VersionBuilder đọc được
        vi_tri = item.get("vi_tri", {})
        if self.label == "Article":
            self.properties["number"] = vi_tri.get("dieu")
        elif self.label == "Clause":
            self.properties["number"] = vi_tri.get("khoan")
        elif self.label == "Point":
            self.properties["number"] = vi_tri.get("diem")


def load_json(filepath):
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def test_golden_case_on_real_data():
    """Test trực tiếp trên dữ liệu thật của dự án (Luật 36/2024 và Luật 118/2025)"""
    base_dir = Path("data/parsed")
    if not base_dir.exists():
        pytest.skip("Thư mục data/parsed không tồn tại, bỏ qua test golden case.")

    # Danh sách các văn bản tham gia vào test này
    # Bao gồm cả Luật 35, 36 (gốc) và 118 (sửa đổi)
    doc_ids = ["35_2024_QH15", "36_2024_QH15", "118_2025_QH15"]

    structure_nodes_by_document = {}
    effective_rules_by_document = {}
    amendment_actions = []

    semantic_index = 1
    for doc_id in doc_ids:
        # 1. Load Effective Rules
        rules_data = load_json(base_dir / f"{doc_id}_effective_rules.json")
        if rules_data:
            effective_rules_by_document[doc_id] = rules_data.get("rules", [])

        # 2. Load Structure (dùng làm các Node cấu trúc đầu vào)
        # Parse từ structure.json (chứa cây phân cấp) thay vì semantic_units
        structure_data = load_json(base_dir / f"{doc_id}_structure.json")
        if structure_data:
            nodes = []

            # Helper đệ quy để trích xuất Điều, Khoản, Điểm
            def extract_nodes(element, level_name):
                if not element:
                    return
                for item in element:
                    node_id = item.get("id")
                    if not node_id:
                        continue

                    # Xác định label dựa vào level_name
                    label_map = {"dieu": "Article", "khoan": "Clause", "diem": "Point"}
                    label = label_map.get(level_name)

                    if label:
                        # Build NodeAdapter tương đương
                        props = {
                            "id": node_id,
                            "level": 2
                            if label == "Article"
                            else 3
                            if label == "Clause"
                            else 4,
                            "number": item.get("so"),
                        }
                        # Gán thẳng các thuộc tính để khớp interface
                        adapter = type(
                            "obj",
                            (object,),
                            {"id": node_id, "label": label, "properties": props},
                        )
                        nodes.append(adapter)

                    # Đệ quy xuống cấp dưới
                    extract_nodes(item.get("khoan"), "khoan")
                    extract_nodes(item.get("diem"), "diem")

            extract_nodes(structure_data.get("dieu_khong_chuong"), "dieu")
            for chuong in structure_data.get("chuong", []):
                extract_nodes(chuong.get("dieu"), "dieu")

            structure_nodes_by_document[doc_id] = nodes

        # 3. Load Amendment Index và flatten (trải phẳng) ra thành các record
        amendment_index_path = base_dir / doc_id / "amendment_index.json"
        events = load_json(amendment_index_path)
        if events:
            for event in events:
                # Đổi 118/2025/QH15 thành 118_2025_QH15
                source_doc = event.get("source_document", "").replace("/", "_")
                for item in event.get("items", []):
                    source_unit = item["source_unit"]
                    replacement_tree = item.get("replacement_tree")
                    for idx, action in enumerate(item.get("actions", []), start=1):
                        amendment_actions.append(
                            {
                                "action_id": f"{source_unit}_SU{semantic_index}_A{idx}",
                                "source_document": source_doc,
                                "source_unit": source_unit,
                                "item": {
                                    **item,
                                    "replacement_tree": replacement_tree,
                                },
                                "action": action,
                            }
                        )
                    semantic_index += 1

    if not structure_nodes_by_document:
        pytest.skip("Không tìm thấy dữ liệu thật để chạy test.")

    # --- KHỞI TẠO BUILDER VÀ CHẠY ---
    builder = VersionBuilder(
        structure_nodes_by_document=structure_nodes_by_document,
        amendment_actions=amendment_actions,
        effective_rules_by_document=effective_rules_by_document,
        resolver=CanonicalIDResolver(),
    )
    provisions, versions = builder.build()

    # --- VALIDATE TOÀN BỘ KẾT QUẢ BẰNG VALIDATOR ---
    # Đây là dòng quan trọng nhất, đảm bảo tính đúng đắn của toàn bộ timeline
    valid_action_ids = {record["action_id"] for record in amendment_actions}
    assert validate_all_versions(versions, valid_action_ids=valid_action_ids) is True

    # --- KIỂM TRA MỘT VÀI ĐIỂM DỮ LIỆU THẬT CỤ THỂ ---
    # Luật 118/2025 sửa đổi Điểm c Khoản 1 Điều 7 của Luật 36/2024
    if "36_2024_QH15_D7_K1_Dc" in versions:
        timeline = versions["36_2024_QH15_D7_K1_Dc"]
        # Chắc chắn phải có nhiều hơn 1 phiên bản (V1 gốc + V2 sửa đổi)
        assert len(timeline) >= 2

        # Phiên bản V1 bị đóng lại bằng ngày có hiệu lực của Luật sửa đổi (thường là 01/01/2025)
        v1 = timeline[0]
        v2 = timeline[1]

        assert v1.is_current is False
        assert v2.is_current is True
        assert v1.valid_to == v2.valid_from  # Timeline liền mạch
        assert v2.produced_by in valid_action_ids
