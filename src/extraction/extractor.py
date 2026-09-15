"""Information Extraction Orchestrator: Runs grouped extraction with checkpoint recovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.extraction.client import GeminiRESTClient
from src.extraction.grouper import ClauseGrouper
from src.extraction.models import ClauseExtractionResult
from src.extraction.storage import ExtractionStorage

logger = logging.getLogger(__name__)


class IEOrchestrator:
    """Coordinates grouped clause preparation, LLM extraction calls, and checkpointing."""

    def __init__(
        self,
        client: GeminiRESTClient | None = None,
        model: str | None = None,
        storage: ExtractionStorage | None = None,
        parsed_dir: Path = Path("data/parsed"),
    ) -> None:
        self.client = client or GeminiRESTClient(model=model)
        self.storage = storage or ExtractionStorage()
        self.parsed_dir = parsed_dir

    def extract_document(
        self,
        document_id: str,
        sample_limit: int | None = None,
        force_refresh: bool = False,
    ) -> list[ClauseExtractionResult]:
        """Extracts legal entities and relations for a document, using checkpoints to skip finished clauses."""
        clean_doc_id = document_id.replace("/", "_")
        su_file = self.parsed_dir / f"{clean_doc_id}_semantic_units.json"
        if not su_file.exists():
            raise FileNotFoundError(f"Semantic units file not found: {su_file}")

        with open(su_file, "r", encoding="utf-8") as f:
            semantic_units = json.load(f)

        groups = ClauseGrouper.group_semantic_units(semantic_units, clean_doc_id)
        logger.info(
            "Document %s: Grouped %d semantic units into %d clauses.",
            clean_doc_id,
            len(semantic_units),
            len(groups),
        )

        pending_groups = []
        for g in groups:
            if force_refresh or not self.storage.is_clause_completed(
                clean_doc_id, g.clause_id
            ):
                pending_groups.append(g)

        logger.info(
            "Found %d pending clauses to extract (%d already completed).",
            len(pending_groups),
            len(groups) - len(pending_groups),
        )

        if sample_limit is not None and sample_limit > 0:
            pending_groups = pending_groups[:sample_limit]
            logger.info(
                "Sample limit enabled: Processing first %d clauses.",
                len(pending_groups),
            )

        results: list[ClauseExtractionResult] = []
        for i, group in enumerate(pending_groups, start=1):
            logger.info(
                "[%d/%d] Extracting clause: %s (%d points)...",
                i,
                len(pending_groups),
                group.clause_id,
                len(group.units),
            )
            prompt_text = group.to_prompt_text()
            try:
                result = self.client.extract_clause(group.clause_id, prompt_text)
                self.storage.save_clause_record(clean_doc_id, result)
                results.append(result)
                logger.info(
                    "--> Extracted %s: %d subjects, %d sanctions, %d violations",
                    group.clause_id,
                    len(result.subjects),
                    len(result.sanctions),
                    len(result.violations),
                )
            except Exception as exc:
                logger.error("Error extracting clause %s: %s", group.clause_id, exc)

        return results
