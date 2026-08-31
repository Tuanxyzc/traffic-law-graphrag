import json
import tempfile
import unittest
from pathlib import Path

from src.parser import corpus_postprocessor


class CorpusPostprocessorTests(unittest.TestCase):
    def test_semantic_clause_aggregates_child_point_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc_dir = root / "118_2025_QH15"
            doc_dir.mkdir()
            events = [{
                "source_document": "118/2025/QH15",
                "items": [
                    {"source_unit": "118_2025_QH15_D7_K1_Da", "actions": [{
                        "operation": "SUA_DOI", "targets": [{"target_context": {
                            "document": "36/2024/QH15", "article": {"number": "7"},
                            "clause": {"number": "1"}, "point": {"number": "c"},
                        }}],
                    }]},
                    {"source_unit": "118_2025_QH15_D7_K1_Db", "actions": [{
                        "operation": "SUA_DOI", "targets": [{"target_context": {
                            "document": "36/2024/QH15", "article": {"number": "7"},
                            "clause": {"number": "1"}, "point": {"number": "h"},
                        }}],
                    }]},
                ],
            }]
            (doc_dir / "amendment_index.json").write_text(json.dumps(events), encoding="utf-8")
            semantic_path = root / "118_2025_QH15_semantic_units.json"
            semantic_path.write_text(json.dumps([{
                "id": "118_2025_QH15_D7_K1", "hanh_dong": "SUA_DOI", "doi_tuong": [],
            }]), encoding="utf-8")
            corpus_postprocessor.sync_semantic_amendments(root)
            unit = json.loads(semantic_path.read_text(encoding="utf-8"))[0]
            self.assertEqual([x["diem"] for x in unit["doi_tuong"]], ["c", "h"])

    def test_backfill_marks_target_and_parent_article(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            structure = {
                "so_hieu": "1/2024/ND-CP",
                "dieu_khong_chuong": [{
                    "id": "1_2024_ND-CP_D2", "trang_thai": "hieu_luc",
                    "khoan": [{"id": "1_2024_ND-CP_D2_K1", "trang_thai": "hieu_luc"}],
                }],
            }
            (root / "1_2024_ND-CP_structure.json").write_text(
                json.dumps(structure), encoding="utf-8"
            )
            (root / "1_2024_ND-CP_semantic_units.json").write_text(
                json.dumps([{"id": "1_2024_ND-CP_D2_K1"}]), encoding="utf-8"
            )
            edges = [{
                "source": "2_2025_ND-CP_D1", "target": "1_2024_ND-CP_D2_K1",
                "relation": "BAI_BO", "source_document": "2/2025/ND-CP",
            }]
            corpus_postprocessor.backfill_original_documents(root, edges)
            result = json.loads(
                (root / "1_2024_ND-CP_structure.json").read_text(encoding="utf-8")
            )
            article = result["dieu_khong_chuong"][0]
            self.assertEqual(article["trang_thai"], "da_sua_doi")
            self.assertEqual(article["khoan"][0]["trang_thai"], "bai_bo")


if __name__ == "__main__":
    unittest.main()
