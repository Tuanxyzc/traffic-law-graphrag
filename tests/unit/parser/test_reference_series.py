import unittest

from src.parser.models import ViTri
from src.parser.reference import resolve_references

DOC = "165/2024/ND-CP"
CURRENT = ViTri(dieu="20", khoan="5", so_hieu_van_ban=DOC)


class ReferenceSeriesTests(unittest.TestCase):
    def target_ids(self, text):
        return [
            reference.gia_tri_xac_dinh.target_id()
            for reference in resolve_references(text, CURRENT, DOC)
        ]

    def test_multiple_clauses_share_current_article(self):
        self.assertEqual(
            self.target_ids(
                "quy \u0111\u1ecbnh t\u1ea1i kho\u1ea3n 1 v\u00e0 kho\u1ea3n 2 \u0110i\u1ec1u n\u00e0y"
            ),
            ["165_2024_ND-CP_D20_K1", "165_2024_ND-CP_D20_K2"],
        )

    def test_explicit_clause_article_series_shares_document_qualifier(self):
        self.assertEqual(
            self.target_ids(
                "kho\u1ea3n 1 \u0110i\u1ec1u 4, kho\u1ea3n 1 \u0110i\u1ec1u 5, kho\u1ea3n 1 \u0110i\u1ec1u 6 "
                "c\u1ee7a Ngh\u1ecb \u0111\u1ecbnh n\u00e0y"
            ),
            ["165_2024_ND-CP_D4_K1", "165_2024_ND-CP_D5_K1", "165_2024_ND-CP_D6_K1"],
        )

    def test_series_accepts_and_or_comma_connectors(self):
        self.assertEqual(
            self.target_ids(
                "kho\u1ea3n 1 \u0110i\u1ec1u 4 v\u00e0 kho\u1ea3n 2 \u0110i\u1ec1u 5 ho\u1eb7c kho\u1ea3n 3 \u0110i\u1ec1u 6 "
                "c\u1ee7a Ngh\u1ecb \u0111\u1ecbnh n\u00e0y"
            ),
            ["165_2024_ND-CP_D4_K1", "165_2024_ND-CP_D5_K2", "165_2024_ND-CP_D6_K3"],
        )

    def test_multiple_clauses_share_explicit_article_and_document(self):
        self.assertEqual(
            self.target_ids(
                "kho\u1ea3n 1, kho\u1ea3n 2, kho\u1ea3n 3 \u0110i\u1ec1u 23 "
                "c\u1ee7a Ngh\u1ecb \u0111\u1ecbnh n\u00e0y"
            ),
            ["165_2024_ND-CP_D23_K1", "165_2024_ND-CP_D23_K2", "165_2024_ND-CP_D23_K3"],
        )

    def test_mixed_point_clause_series_keeps_each_clause_boundary(self):
        text = (
            "điểm a, điểm c, điểm d, điểm đ khoản 2; "
            "điểm a, điểm d khoản 3; khoản 7; "
            "điểm đ khoản 11 Điều này"
        )
        ids = self.target_ids(text.replace("điểm", "điểm"))
        self.assertIn("165_2024_ND-CP_D20_K2_Da", ids)
        self.assertIn("165_2024_ND-CP_D20_K3_Dd", ids)
        self.assertIn("165_2024_ND-CP_D20_K7", ids)
        self.assertIn("165_2024_ND-CP_D20_K11_Dđ", ids)
        self.assertNotIn("165_2024_ND-CP_D20_K7_Da", ids)

    def test_plain_word_diem_does_not_start_structural_series(self):
        self.assertEqual(
            self.target_ids(
                "điểm cố định khác trên tuyến đường; trừ hành vi tại khoản 8 Điều này"
            ),
            ["165_2024_ND-CP_D20_K8"],
        )

    def test_cross_document_reference_does_not_capture_following_current_series(self):
        ids = self.target_ids(
            "khoản 1 Điều 77 Luật Trật tự, an toàn giao thông đường bộ và "
            "khoản 1, khoản 2, khoản 3 Điều này"
        )
        self.assertIn("165_2024_ND-CP_D20_K1", ids)
        self.assertIn("165_2024_ND-CP_D20_K2", ids)
        self.assertIn("165_2024_ND-CP_D20_K3", ids)


if __name__ == "__main__":
    unittest.main()
