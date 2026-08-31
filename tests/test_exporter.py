import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.parser.exporter import save_reference_index
from src.parser.models import ThamChieu, ViTri


class ReferenceIndexExporterTests(unittest.TestCase):
    def test_duplicate_edges_are_exported_once(self):
        reference = ThamChieu(
            loai="dieu_tuyet_doi_nay",
            van_ban_goc="Điều 20 Nghị định này",
            gia_tri_xac_dinh=ViTri(dieu="20", so_hieu_van_ban="236/2026/ND-CP"),
            quan_he="THAM_CHIEU",
        )
        unit = SimpleNamespace(
            id="236_2026_ND-CP_D8",
            tham_chieu=[reference, reference],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            path = save_reference_index([unit], "236/2026/ND-CP", output_dir)
            edges = json.loads(Path(path).read_text(encoding="utf-8"))

        self.assertEqual(
            edges,
            [
                {
                    "source": "236_2026_ND-CP_D8",
                    "target": "236_2026_ND-CP_D20",
                    "relation": "THAM_CHIEU",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
