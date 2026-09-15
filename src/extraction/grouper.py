"""Clause Grouper: Groups individual semantic units sharing (dieu, khoan) for joint extraction."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class ClauseGroup:
    """Represents a grouped clause containing one or more points."""

    clause_id: str
    document_id: str
    dieu: str
    khoan: str | None
    tieu_de_dieu: str
    units: list[dict[str, Any]]

    def to_prompt_text(self) -> str:
        """Formats the clause group into a clean, contextualized prompt text for LLM extraction."""
        lines = [
            f"VĂN BẢN: {self.document_id}",
            f"ĐIỀU {self.dieu}: {self.tieu_de_dieu}",
        ]
        if self.khoan:
            lines.append(f"KHOẢN {self.khoan}:")

        if len(self.units) == 1 and not self.units[0].get("vi_tri", {}).get("diem"):
            # Single clause without points
            u = self.units[0]
            unit_id = u.get("id", self.clause_id)
            content = u.get("noi_dung_chuan_hoa") or u.get("noi_dung") or ""
            lines.append(f"[Đơn vị ID: {unit_id}]\n{content.strip()}")
        else:
            # Multiple points sharing this clause
            lines.append("CÁC ĐIỂM QUY ĐỊNH VÀ HÀNH VI:")
            for u in self.units:
                unit_id = u.get("id", "")
                diem = u.get("vi_tri", {}).get("diem") or ""
                content = u.get("noi_dung_chuan_hoa") or u.get("noi_dung") or ""
                lines.append(
                    f"- [Đơn vị ID: {unit_id}] Điểm {diem}:\n{content.strip()}"
                )

        return "\n".join(lines)


class ClauseGrouper:
    """Groups semantic units from a document by Article and Clause."""

    @staticmethod
    def group_semantic_units(
        semantic_units: list[dict[str, Any]],
        document_id: str = "",
    ) -> list[ClauseGroup]:
        """Groups semantic units sharing the same article and clause into ClauseGroup objects."""
        groups_dict: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(
            list
        )
        tieu_de_map: dict[str, str] = {}

        for unit in semantic_units:
            vt = unit.get("vi_tri", {})
            dieu = str(vt.get("dieu") or "")
            khoan_val = vt.get("khoan")
            khoan = str(khoan_val) if khoan_val is not None else None

            if not dieu:
                continue

            doc = vt.get("so_hieu_van_ban") or document_id
            tieu_de = unit.get("tieu_de_dieu") or ""
            if tieu_de and dieu not in tieu_de_map:
                tieu_de_map[dieu] = tieu_de

            key = (dieu, khoan)
            groups_dict[key].append(unit)

        clause_groups: list[ClauseGroup] = []
        for (dieu, khoan), units in groups_dict.items():
            doc_prefix = document_id or units[0].get("vi_tri", {}).get(
                "so_hieu_van_ban", ""
            )
            doc_prefix_clean = doc_prefix.replace("/", "_").replace("-", "_")

            if khoan:
                clause_id = f"{doc_prefix_clean}_D{dieu}_K{khoan}"
            else:
                clause_id = f"{doc_prefix_clean}_D{dieu}"

            tieu_de = tieu_de_map.get(dieu, "")
            clause_groups.append(
                ClauseGroup(
                    clause_id=clause_id,
                    document_id=doc_prefix,
                    dieu=dieu,
                    khoan=khoan,
                    tieu_de_dieu=tieu_de,
                    units=units,
                )
            )

        return clause_groups
