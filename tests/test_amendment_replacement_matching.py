import unittest

from src.parser.amendment_recorder import (
    build_replacement_tree_and_root,
    parse_actions,
)
from src.parser.models import ViTri
from src.parser.structure import DIEU_TITLE_PATTERN
from src.parser.target_matcher import match_targets
from src.graph.amendment.amendment_mapper import map_amendment_item
from src.graph.validators.amendment_validator import validate_amendment_graph
from src.graph.resolver.canonical_id_resolver import CanonicalIDResolver

DOC = "36/2024/QH15"


class AmendmentReplacementMatchingTests(unittest.TestCase):
    def test_graph_validator_reports_wrong_numbered_replacement(self):
        action = {
            "operation": "SUA_DOI",
            "targets": [{
                "target_unit": "36_2024_QH15_D9_K18",
                "target_context": {
                    "document": DOC,
                    "article": {"id": "36_2024_QH15_D9", "number": "9"},
                    "clause": {"id": "36_2024_QH15_D9_K18", "number": "18"},
                    "point": None,
                },
                "target_level": "CLAUSE",
                "replacement_level": "CLAUSE",
                "replacement_path": ["clauses", 0],
            }],
            "raw_instruction": "update clause 18",
            "resolution_status": "RESOLVED",
        }
        item = {
            "source_unit": "118_2025_QH15_D7_K2",
            "source_point": {"id": "118_2025_QH15_D7_K2", "number": None},
            "replacement_tree": {
                "clauses": [{"number": "18a", "content": "wrong replacement"}]
            },
            "actions": [action],
        }
        resolver = CanonicalIDResolver()
        nodes, relationships = map_amendment_item(item, 1, resolver)

        with self.assertRaisesRegex(
            ValueError,
            r"identity mismatch.*expected number=18, actual number=18a.*path=\['clauses', 0\]",
        ):
            validate_amendment_graph(item, action, nodes, relationships, resolver)

    def test_mixed_update_and_insert_keep_distinct_clause_replacements(self):
        instruction = (
            "2. S\u1eeda \u0111\u1ed5i, b\u1ed5 sung kho\u1ea3n 18 v\u00e0 b\u1ed5 sung "
            "kho\u1ea3n 18a v\u00e0o sau kho\u1ea3n 18 \u0110i\u1ec1u 9 nh\u01b0 sau:"
        )
        actions = parse_actions(instruction, DOC)
        tree, root = build_replacement_tree_and_root(
            "18. Replacement for clause 18.\n18a. Newly inserted clause.",
            "CLAUSE",
        )

        update = match_targets(actions[0]["targets"], tree, root)[0]
        self.assertEqual(update["replacement_path"], ["clauses", 0])
        self.assertEqual([node["number"] for node in tree["clauses"]], ["18", "18a"])
        self.assertEqual(actions[1]["created_targets"][0].khoan, "18a")

    def test_numbered_node_never_falls_back_to_different_target(self):
        target = ViTri(dieu="9", khoan="18", so_hieu_van_ban=DOC)
        mapped = match_targets(
            [target],
            {"clauses": [{"number": "18a", "content": "wrong"}]},
            "CLAUSE_LIST",
        )[0]

        self.assertIsNone(mapped["replacement_path"])
        self.assertIsNone(mapped["replacement_level"])

    def test_multiple_targets_match_by_identifier_not_position(self):
        targets = [
            ViTri(dieu="10", khoan="2", diem="a", so_hieu_van_ban=DOC),
            ViTri(dieu="10", khoan="2", diem="b", so_hieu_van_ban=DOC),
        ]
        tree = {"points": [
            {"number": "b", "content": "B"},
            {"number": "a", "content": "A"},
            {"number": "c", "content": "C"},
        ]}

        mapped = match_targets(targets, tree, "POINT_LIST")
        self.assertEqual(
            [entry["replacement_path"] for entry in mapped],
            [["points", 1], ["points", 0]],
        )

    def test_unnumbered_replacements_can_still_match_by_order(self):
        targets = [
            ViTri(dieu="10", khoan="2", diem="a", so_hieu_van_ban=DOC),
            ViTri(dieu="10", khoan="2", diem="b", so_hieu_van_ban=DOC),
        ]
        tree = {"points": [
            {"number": None, "content": "A"},
            {"number": None, "content": "B"},
        ]}

        mapped = match_targets(targets, tree, "POINT_LIST")
        self.assertEqual(
            [entry["replacement_path"] for entry in mapped],
            [["points", 0], ["points", 1]],
        )

    def test_multiple_articles_match_by_number(self):
        article_word = DIEU_TITLE_PATTERN.pattern[1:].split(r"\s+")[0]
        tree, root = build_replacement_tree_and_root(
            f"{article_word} 10. Updated article\n1. First clause.\n"
            f"{article_word} 10a. Inserted article\n1. Its first clause.",
            "ARTICLE",
        )
        mapped = match_targets(
            [ViTri(dieu="10", so_hieu_van_ban=DOC)], tree, root
        )[0]

        self.assertEqual(root, "ARTICLE_LIST")
        self.assertEqual(mapped["replacement_path"], ["articles", 0])
        self.assertEqual([article["number"] for article in tree["articles"]], ["10", "10a"])

if __name__ == "__main__":
    unittest.main()
