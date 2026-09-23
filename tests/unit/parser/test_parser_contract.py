import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.parser import __main__ as parser_main


class TestParserContract:
    def test_missing_input_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(parser_main, "RAW_DIR", str(tmp_path))

        assert parser_main.run_one("missing.docx", "1/2024/ND-CP") is False

    def test_run_one_exports_required_artifacts_deterministically(
        self, monkeypatch, tmp_path
    ):
        raw_dir = tmp_path / "raw"
        parsed_dir = tmp_path / "parsed"
        raw_dir.mkdir()
        parsed_dir.mkdir()
        filename = "fixture.docx"
        (raw_dir / filename).write_bytes(b"fixture")

        document = SimpleNamespace(
            dieu_khong_chuong=[],
            chuong=[],
            so_hieu="1/2024/ND-CP",
        )
        units = [SimpleNamespace(id="1_2024_ND-CP_D1")]

        monkeypatch.setattr(parser_main, "RAW_DIR", str(raw_dir))
        monkeypatch.setattr(parser_main, "PARSED_DIR", str(parsed_dir))
        monkeypatch.setattr(parser_main.normalize, "load_docx", lambda _: [])
        monkeypatch.setattr(
            parser_main.normalize, "normalize_paragraphs", lambda value: value
        )
        monkeypatch.setattr(
            parser_main.structure, "parse_document", lambda *args, **kwargs: document
        )
        monkeypatch.setattr(parser_main.scope_resolver, "apply", lambda value: value)
        monkeypatch.setattr(
            parser_main.semantic_unit, "build", lambda *args, **kwargs: units
        )
        monkeypatch.setattr(
            parser_main.validator, "build_global_index", lambda *args, **kwargs: {}
        )
        monkeypatch.setattr(
            parser_main.validator, "validate", lambda *args, **kwargs: []
        )
        monkeypatch.setattr(
            parser_main.metadata_versioning, "extract_header_metadata", lambda _: {}
        )
        monkeypatch.setattr(
            parser_main.metadata_versioning,
            "save_effective_rules",
            lambda *args, **kwargs: {
                "rules": [{"rule_type": "GENERAL", "effective_from": "2024-01-01"}]
            },
        )
        monkeypatch.setattr(parser_main, "VAN_BAN_SCOPE", {})
        monkeypatch.setattr(parser_main, "AMENDMENT_TARGET_FALLBACK", {})
        monkeypatch.setattr(parser_main, "DOCUMENT_REGISTRY", {})

        def write_json(path, payload):
            Path(path).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

        def save_structure(*args, filename_override=None, **kwargs):
            suffix = filename_override or "1_2024_ND-CP_structure.json"
            write_json(
                parsed_dir / suffix,
                {"so_hieu": "1/2024/ND-CP", "dieu_khong_chuong": [], "chuong": []},
            )

        monkeypatch.setattr(parser_main.exporter, "save_structure", save_structure)
        monkeypatch.setattr(
            parser_main.exporter,
            "save_semantic_units",
            lambda *args, **kwargs: write_json(
                parsed_dir / "1_2024_ND-CP_semantic_units.json", [{"id": units[0].id}]
            ),
        )
        monkeypatch.setattr(
            parser_main.exporter,
            "save_reference_index",
            lambda *args, **kwargs: write_json(
                parsed_dir / "1_2024_ND-CP_reference_index.json", []
            ),
        )
        monkeypatch.setattr(
            parser_main.exporter,
            "save_metadata",
            lambda *args, **kwargs: write_json(
                parsed_dir / "1_2024_ND-CP_metadata.json",
                {"canonical_document_id": "1_2024_ND-CP"},
            ),
        )

        assert parser_main.run_one(filename, "1/2024/ND-CP") is True
        first_run = {path.name: path.read_bytes() for path in parsed_dir.glob("*.json")}
        assert {
            "1_2024_ND-CP_structure.json",
            "1_2024_ND-CP_semantic_units.json",
            "1_2024_ND-CP_reference_index.json",
        } <= set(first_run)
        assert (
            json.loads(first_run["1_2024_ND-CP_structure.json"])["so_hieu"]
            == "1/2024/ND-CP"
        )
        assert (
            json.loads(first_run["1_2024_ND-CP_semantic_units.json"])[0]["id"]
            == "1_2024_ND-CP_D1"
        )
        assert json.loads(first_run["1_2024_ND-CP_reference_index.json"]) == []

        assert parser_main.run_one(filename, "1/2024/ND-CP") is True
        second_run = {
            path.name: path.read_bytes() for path in parsed_dir.glob("*.json")
        }
        assert second_run == first_run

    @pytest.mark.parametrize(
        ("warning", "expected"),
        [
            ("[1] TRÙNG id: value", True),
            ("[1] id_cha 'missing' không tồn tại", True),
            ("non-blocking diagnostic", False),
        ],
    )
    def test_serious_warning_policy(self, warning, expected):
        assert parser_main._is_serious_warning(warning) is expected

    def test_run_fails_when_corpus_audit_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr(parser_main, "PARSED_DIR", str(tmp_path))
        monkeypatch.setattr(
            parser_main, "FILE_SO_HIEU_MAP", {"fixture.docx": "1/2024/ND-CP"}
        )
        monkeypatch.setattr(parser_main, "run_one", lambda *args: True)
        monkeypatch.setattr(parser_main.corpus_postprocessor, "run", lambda *args: None)
        monkeypatch.setattr(
            parser_main.corpus_audit,
            "run",
            lambda *args: {"all_pass": False, "issue_1": {"pass": False}},
        )

        assert parser_main.run() is False
