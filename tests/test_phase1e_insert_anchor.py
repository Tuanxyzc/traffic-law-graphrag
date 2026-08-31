import unittest
from types import SimpleNamespace

from src.parser.amendment_recorder import (
    build_created_units,
    build_replacement_tree_and_root,
    parse_actions,
    is_non_action_container,
)
from src.parser.structure import parse_khoan_list, parse_document
from src.parser.normalize import DoanVan
from src.parser.metadata_versioning import extract_header_metadata, build_effective_rules
from src.parser.canonical_id_resolver import normalize_so_hieu, canonical_document_id
from src.parser.amendment_recorder import resolve_replacement_references
from src.parser.models import ViTri
from src.parser.semantic_unit import _build_unit
from src.parser.semantic_unit import build_for_dieu_list
from src.parser.reference import resolve_references


DOC = "168/2024/ND-CP"


class InsertAnchorRegressionTests(unittest.TestCase):
    def assert_insert(self, instruction, quote, relation, existing_id, created_id):
        action = parse_actions(instruction, DOC)[0]
        existing = action["targets"][0]
        tree, root = build_replacement_tree_and_root(quote, "POINT" if existing.diem else "CLAUSE")
        created = build_created_units(tree, root, DOC, existing)

        self.assertEqual(action["anchor"]["relation"], relation)
        self.assertEqual(existing.target_id(), existing_id)
        self.assertEqual(created[0]["unit_id"], created_id)
        self.assertNotEqual(existing.target_id(), created[0]["unit_id"])
        self.assertEqual(action["raw_instruction"], instruction)
        start, end = action["anchor_span"]
        self.assertIn("trước" if relation == "BEFORE" else "sau", instruction[start:end])

    def test_insert_before_clause(self):
        self.assert_insert(
            "Bổ sung khoản 1a vào trước khoản 1 Điều 6 như sau:",
            "1a. Phạt cảnh cáo.", "BEFORE",
            "168_2024_ND-CP_D6_K1", "168_2024_ND-CP_D6_K1a",
        )

    def test_insert_after_clause(self):
        self.assert_insert(
            "Bổ sung khoản 1a vào sau khoản 1 Điều 6 như sau:",
            "1a. Phạt cảnh cáo.", "AFTER",
            "168_2024_ND-CP_D6_K1", "168_2024_ND-CP_D6_K1a",
        )

    def test_insert_before_point(self):
        self.assert_insert(
            "Bổ sung điểm c vào trước điểm d khoản 3 Điều 10 như sau:",
            "c) Nội dung mới.", "BEFORE",
            "168_2024_ND-CP_D10_K3_Dd", "168_2024_ND-CP_D10_K3_Dc",
        )

    def test_insert_after_point(self):
        self.assert_insert(
            "Bổ sung điểm c vào sau điểm b khoản 3 Điều 10 như sau:",
            "c) Nội dung mới.", "AFTER",
            "168_2024_ND-CP_D10_K3_Db", "168_2024_ND-CP_D10_K3_Dc",
        )

    def test_text_amendment_ignores_structural_words_inside_quotes(self):
        action = parse_actions(
            '5. Bổ sung cụm từ "khoản 1; điểm d," vào trước cụm từ "điểm đ" '
            'tại điểm a khoản 6 Điều 14.', DOC,
        )[0]
        self.assertEqual([t.target_id() for t in action["targets"]],
                         ["168_2024_ND-CP_D14_K6_Da"])

    def test_text_amendment_with_multiple_quoted_spans(self):
        action = parse_actions(
            '8. Bổ sung cụm từ "Điều 20 (điểm l khoản 5), Điều 21," '
            'vào trước cụm từ "Điều 29", cụm từ "; khoản 9a" '
            'vào sau cụm từ "điểm n khoản 7" tại điểm h khoản 3 Điều 47.', DOC,
        )[0]
        self.assertEqual([t.target_id() for t in action["targets"]],
                         ["168_2024_ND-CP_D47_K3_Dh"])

    def test_text_deletion_ignores_deleted_structural_phrase(self):
        action = parse_actions(
            'Bỏ cụm từ "Điểm g khoản 5;" tại điểm a khoản 1 Điều 48.', DOC,
        )[0]
        self.assertEqual([t.target_id() for t in action["targets"]],
                         ["168_2024_ND-CP_D48_K1_Da"])

    def test_numbered_amendments_survive_quote_anomalies(self):
        text = (
            '6. Bổ sung cụm từ"abc" tại Điều 21.7.\n'
            '7. Bổ sung cụm từ”xyz" tại khoản 2 Điều 8.\n'
            '8. Bổ sung cụm từ "ok" tại điểm a khoản 3 Điều 9.'
        )
        self.assertEqual([k.so for k in parse_khoan_list(text, "D1")], ["6", "7", "8"])

    def test_quote_boundary_anomaly_still_resolves_multiple_targets(self):
        action = parse_actions(
            '6. Bổ sung cụm từ”, xe vận tải nội bộ" vào sau cụm từ '
            '"xe ô tô kinh doanh vận tải" tại điểm d khoản 6 Điều 20, '
            'điểm b khoản 5 Điều 21.', DOC,
        )[0]
        self.assertEqual([t.target_id() for t in action["targets"]], [
            "168_2024_ND-CP_D20_K6_Dd",
            "168_2024_ND-CP_D21_K5_Db",
        ])

    def test_unresolved_instruction_is_not_dropped(self):
        action = parse_actions('6. Bổ sung cụm từ "abc" vào sau cụm từ "xyz".', DOC)[0]
        self.assertEqual(action["operation"], "BO_SUNG_TEXT")
        self.assertEqual(action["targets"], [])
        self.assertEqual(action["raw_instruction"],
                         '6. Bổ sung cụm từ "abc" vào sau cụm từ "xyz".')

    def test_multiple_structural_targets(self):
        action = parse_actions(
            'Sửa đổi khoản 1, khoản 3 và khoản 6 Điều 25.', DOC,
        )[0]
        self.assertEqual([t.khoan for t in action["targets"]], ["1", "3", "6"])

    def test_coordinated_actions_inherit_single_shared_article_context(self):
        actions = parse_actions(
            "2. Sửa đổi, bổ sung khoản 18 và bổ sung khoản 18a vào sau "
            "khoản 18 Điều 9 như sau:", "36/2024/QH15",
        )
        self.assertEqual(actions[0]["targets"][0].target_id(),
                         "36_2024_QH15_D9_K18")
        self.assertEqual(actions[0]["raw_instruction"],
                         "2. Sửa đổi, bổ sung khoản 18")

    def test_explicit_external_document(self):
        action = parse_actions(
            'Sửa đổi khoản 3, khoản 4 Điều 27 Nghị định số 184/2025/NĐ-CP.', DOC,
        )[0]
        self.assertEqual([t.so_hieu_van_ban for t in action["targets"]],
                         ["184/2025/ND-CP", "184/2025/ND-CP"])

    def test_article_and_clause_containers_are_non_actions(self):
        self.assertTrue(is_non_action_container(
            {"source_clause": None, "source_point": None},
            "Điều 19. Bổ sung, thay thế một số cụm từ",
        ))

    def test_mixed_grouped_locations_do_not_bleed_context(self):
        action = parse_actions(
            'Bãi bỏ khoản 7 Điều 11, khoản 3 Điều 12, khoản 4 Điều 17, '
            'Điều 18, khoản 1, khoản 3 và khoản 6 Điều 25.', DOC,
        )[0]
        self.assertEqual([t.target_id() for t in action["targets"]], [
            "168_2024_ND-CP_D11_K7",
            "168_2024_ND-CP_D12_K3",
            "168_2024_ND-CP_D17_K4",
            "168_2024_ND-CP_D18",
            "168_2024_ND-CP_D25_K1",
            "168_2024_ND-CP_D25_K3",
            "168_2024_ND-CP_D25_K6",
        ])

    def test_document_title_does_not_create_false_second_action(self):
        actions = parse_actions(
            '5. Bãi bỏ khoản 3, khoản 4 Điều 27 Nghị định số 184/2025/NĐ-CP '
            'quy định phân định thẩm quyền và sửa đổi, bổ sung một số điều của '
            'các Nghị định của Chính phủ.', DOC,
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual([t.target_id() for t in actions[0]["targets"]], [
            "184_2025_ND-CP_D27_K3",
            "184_2025_ND-CP_D27_K4",
        ])

    def test_typography_does_not_create_decimal_article(self):
        document = parse_document([
            DoanVan("Điều 25.5. Bãi bỏ khoản 1", True),
        ], DOC)
        articles = document.dieu_khong_chuong
        self.assertEqual([d.so for d in articles], ["25"])
        self.assertNotIn("25.5", [d.so for d in articles])

    def test_appendix_replacement_has_no_article_target(self):
        action = parse_actions(
            'Thay thế Phụ lục I ban hành kèm theo Nghị định số '
            '151/2024/NĐ-CP bằng Phụ lục I ban hành kèm theo Nghị định này.', DOC,
        )[0]
        self.assertEqual(action["operation"], "THAY_THE_PHU_LUC")
        self.assertEqual(action["targets"], [])
        self.assertIsNotNone(action["appendix_amendment"])

    def test_metadata_header_and_effective_rule(self):
        meta = extract_header_metadata('data/raw/168_2024_ND-CP_619502.docx')
        self.assertEqual(meta["co_quan_ban_hanh"], "CHÍNH PHỦ")
        self.assertEqual(meta["ngay_ban_hanh"], "2024-12-26")

    def test_effective_rules_ignore_dates_of_repealed_documents(self):
        article = SimpleNamespace(
            so="38", tieu_de="Hiệu lực thi hành", noi_dung="",
            khoan=[SimpleNamespace(
                so="2",
                noi_dung="Nghị định số 109/2009/NĐ-CP ngày 01 tháng 12 năm 2009 bị bãi bỏ."
            )],
        )
        document = SimpleNamespace(
            so_hieu="151/2024/ND-CP", dieu_khong_chuong=[article], chuong=[]
        )
        self.assertEqual(build_effective_rules(document)["rules"], [])

    def test_effective_end_date_is_not_a_start_date(self):
        article = SimpleNamespace(
            so="28", tieu_de="Hiệu lực thi hành", noi_dung="",
            khoan=[SimpleNamespace(
                so="2",
                noi_dung="Điều 2 của Nghị định này hết hiệu lực kể từ ngày 01 tháng 3 năm 2027."
            )],
        )
        document = SimpleNamespace(
            so_hieu="184/2025/ND-CP", dieu_khong_chuong=[article], chuong=[]
        )
        rule = build_effective_rules(document)["rules"][0]
        self.assertIsNone(rule["effective_from"])
        self.assertEqual(rule["effective_to"], "2027-03-01")
        self.assertEqual([target["unit_id"] for target in rule["targets"]],
                         ["184_2025_ND-CP_D2"])

    def test_canonical_document_aliases(self):
        self.assertEqual(normalize_so_hieu("151/2024/NĐ-CP"), "151/2024/ND-CP")
        self.assertEqual(canonical_document_id("151/2024/NĐ-CP"),
                         canonical_document_id("151/2024/ND-CP"))

    def test_replacement_reference_uses_target_context(self):
        refs = resolve_replacement_references(
            {"clause": {"number": "2", "content": "Thực hiện theo khoản này của Nghị định này."}},
            ViTri(dieu="52", khoan="2", so_hieu_van_ban="36/2024/QH15"),
            "36/2024/QH15",
        )
        documents = {r["gia_tri_xac_dinh"]["so_hieu_van_ban"] for r in refs}
        self.assertEqual(documents, {"36/2024/QH15"})

    def test_semantic_unit_reference_uses_amendment_target_context(self):
        article = SimpleNamespace(
            hieu_luc_tu=None, tieu_de="Sửa đổi Điều 12", phien_ban="goc",
            sua_doi_boi_van_ban=None,
        )
        unit = _build_unit(
            ViTri(dieu="27", khoan="4", so_hieu_van_ban="184/2025/ND-CP"),
            "184_2025_ND-CP_D27_K4", 3, "SUA_DOI",
            [ViTri(dieu="12", so_hieu_van_ban="151/2024/ND-CP")],
            "Cơ sở dữ liệu quy định tại điểm đ khoản 1 Điều này.",
            "Cơ sở dữ liệu quy định tại điểm đ khoản 1 Điều này.",
            article, None, None, "184/2025/ND-CP", None,
        )
        targets = [ref.gia_tri_xac_dinh.target_id() for ref in unit.tham_chieu]
        self.assertEqual(targets, ["151_2024_ND-CP_D12_K1_Dđ"])

    def test_omnibus_semantic_targets_are_selected_per_article(self):
        article = SimpleNamespace(
            so="7", id="118_2025_QH15_D7", trang_thai="hieu_luc",
            tieu_de="Sửa đổi, bổ sung Luật Trật tự, an toàn giao thông đường bộ",
            noi_dung="Sửa đổi khoản 1 Điều 9.", khoan=[], hieu_luc_tu=None,
            phien_ban="goc", sua_doi_boi_van_ban=None,
        )
        units = build_for_dieu_list([article], "118/2025/QH15", "Luat_gop")
        self.assertEqual(
            units[0].doi_tuong[0].so_hieu_van_ban, "36/2024/QH15"
        )

    def test_cross_document_clause_reference(self):
        refs = resolve_references(
            "theo khoản 1 Điều 64 của Luật Trật tự, an toàn giao thông đường bộ;",
            ViTri(dieu="20", khoan="6", so_hieu_van_ban="168/2024/ND-CP"),
            "168/2024/ND-CP",
        )
        self.assertEqual(
            refs[0].gia_tri_xac_dinh.target_id(), "36_2024_QH15_D64_K1"
        )

    def test_internal_absolute_clause_reference(self):
        refs = resolve_references(
            "theo khoản 3 Điều 24 của Luật này",
            ViTri(dieu="23", khoan="5", so_hieu_van_ban="35/2024/QH15"),
            "35/2024/QH15",
        )
        self.assertEqual(
            refs[0].gia_tri_xac_dinh.target_id(), "35_2024_QH15_D24_K3"
        )

    def test_point_unit_inherits_clause_amendment_target(self):
        point = SimpleNamespace(so="c", id="238_2026_ND-CP_D8_K3_Dc", noi_dung="c) Nội dung mới")
        clause = SimpleNamespace(
            so="3", id="238_2026_ND-CP_D8_K3", trang_thai="hieu_luc",
            noi_dung="3. Sửa đổi, bổ sung điểm c khoản 5 như sau:\nc) Nội dung mới",
            diem=[point], hieu_luc_tu=None,
        )
        article = SimpleNamespace(
            so="8", id="238_2026_ND-CP_D8", trang_thai="hieu_luc",
            tieu_de="Sửa đổi, bổ sung một số điểm, khoản của Điều 21",
            noi_dung="", khoan=[clause], hieu_luc_tu=None,
            phien_ban="goc", sua_doi_boi_van_ban=None,
        )
        units = build_for_dieu_list(
            [article], "238/2026/ND-CP", "NghiDinh_suaDoi",
            target_so_hieu_mac_dinh="168/2024/ND-CP",
        )
        self.assertEqual(
            units[0].doi_tuong[0].target_id(), "168_2024_ND-CP_D21_K5_Dc"
        )

    def test_title_content_are_not_merged(self):
        paragraphs = [DoanVan("Điều 1. Phạm vi điều chỉnh", True),
                      DoanVan("Nghị định này quy định chi tiết.", False)]
        parsed = parse_document(paragraphs, DOC)
        self.assertEqual(parsed.dieu_khong_chuong[0].tieu_de, "Phạm vi điều chỉnh")
        self.assertEqual(parsed.dieu_khong_chuong[0].noi_dung,
                         "Nghị định này quy định chi tiết.")
        self.assertTrue(is_non_action_container(
            {"source_clause": "6", "source_point": None},
            "6. Thay thế một số cụm từ như sau:",
        ))


if __name__ == "__main__":
    unittest.main()
