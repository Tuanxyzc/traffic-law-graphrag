"""Extraction Storage: Persists and checkpoints extracted entities and relations to JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.extraction.models import ClauseExtractionResult


class ExtractionStorage:
    """Manages reading, writing, and checkpointing extracted JSON records."""

    def __init__(self, output_dir: Path = Path("data/extracted")) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, document_id: str) -> Path:
        clean_name = document_id.replace("/", "_")
        return self.output_dir / f"{clean_name}_ie.json"

    def load_document_data(self, document_id: str) -> dict[str, Any]:
        """Loads existing extraction document data or returns an empty structure."""
        path = self._get_path(document_id)
        if not path.exists():
            return {
                "document_id": document_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "completed_clauses": [],
                "records": [],
            }
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "document_id": document_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "completed_clauses": [],
                "records": [],
            }

    def is_clause_completed(self, document_id: str, clause_id: str) -> bool:
        """Returns True if the clause has already been extracted in previous runs."""
        data = self.load_document_data(document_id)
        return clause_id in data.get("completed_clauses", [])

    def save_clause_record(
        self, document_id: str, result: ClauseExtractionResult
    ) -> None:
        """Appends or updates a clause extraction record and marks it completed."""
        data = self.load_document_data(document_id)
        completed = set(data.get("completed_clauses", []))
        completed.add(result.clause_id)
        data["completed_clauses"] = sorted(completed)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Update or append record
        records: list[dict[str, Any]] = data.get("records", [])
        records = [r for r in records if r.get("clause_id") != result.clause_id]
        records.append(result.model_dump())
        data["records"] = records

        path = self._get_path(document_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_all_records(self, document_id: str) -> list[ClauseExtractionResult]:
        """Loads all extracted clause records for a document."""
        data = self.load_document_data(document_id)
        return [
            ClauseExtractionResult.model_validate(r) for r in data.get("records", [])
        ]
