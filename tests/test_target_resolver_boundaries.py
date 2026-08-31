import unittest

from src.parser.operation import detect_target

DOC = "36/2024/QH15"


class TargetResolverBoundaryTests(unittest.TestCase):
    def resolve(self, text):
        return [
            (target.dieu, target.khoan, target.diem)
            for target in detect_target(text, DOC)
        ]

    def test_point_does_not_cross_repeated_clause_label(self):
        self.assertEqual(
            self.resolve(
                "t\u1ea1i \u0111i\u1ec3m b kho\u1ea3n 4 v\u00e0 kho\u1ea3n 5 \u0110i\u1ec1u 30"
            ),
            [("30", "4", "b"), ("30", "5", None)],
        )

    def test_point_does_not_cross_comma_or_or_boundary(self):
        self.assertEqual(
            self.resolve(
                "\u0111i\u1ec3m b kho\u1ea3n 4, kho\u1ea3n 5 ho\u1eb7c kho\u1ea3n 6 \u0110i\u1ec1u 30"
            ),
            [("30", "4", "b"), ("30", "5", None), ("30", "6", None)],
        )

    def test_explicit_repeated_point_still_applies_to_each_clause(self):
        self.assertEqual(
            self.resolve(
                "\u0111i\u1ec3m b kho\u1ea3n 4 v\u00e0 \u0111i\u1ec3m b kho\u1ea3n 5 \u0110i\u1ec1u 30"
            ),
            [("30", "4", "b"), ("30", "5", "b")],
        )

    def test_unlabeled_clause_continuation_keeps_shared_point(self):
        self.assertEqual(
            self.resolve("\u0111i\u1ec3m b kho\u1ea3n 4 v\u00e0 5 \u0110i\u1ec1u 30"),
            [("30", "4", "b"), ("30", "5", "b")],
        )

    def test_article_at_end_is_shared_by_both_groups(self):
        targets = detect_target(
            "\u0111i\u1ec3m b kho\u1ea3n 4 v\u00e0 kho\u1ea3n 5 \u0110i\u1ec1u 30", DOC
        )
        self.assertEqual(
            [target.target_id() for target in targets],
            [
                "36_2024_QH15_D30_K4_Db",
                "36_2024_QH15_D30_K5",
            ],
        )

    def test_point_does_not_cross_semicolon_to_standalone_clause(self):
        self.assertEqual(
            self.resolve(
                "\u0111i\u1ec3m a kho\u1ea3n 6; kho\u1ea3n 7; \u0111i\u1ec3m b kho\u1ea3n 9 \u0110i\u1ec1u 6"
            ),
            [("6", "6", "a"), ("6", "7", None), ("6", "9", "b")],
        )


if __name__ == "__main__":
    unittest.main()
