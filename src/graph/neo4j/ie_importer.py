"""Neo4j IE Importer: Batch ingests extracted legal subjects, vehicles, violations, objects, conditions, and sanctions."""

from __future__ import annotations

import logging
from typing import Any

from src.extraction.models import ClauseExtractionResult
from src.extraction.storage import ExtractionStorage
from src.graph.neo4j.connection import Neo4jClient

logger = logging.getLogger(__name__)


class Neo4jIEImporter:
    """Batch-ingests extracted Information Extraction records into Neo4j."""

    def __init__(
        self,
        client: Neo4jClient | None = None,
        storage: ExtractionStorage | None = None,
    ) -> None:
        self.client = client
        self.storage = storage or ExtractionStorage()

    def import_document_extractions(self, document_id: str) -> dict[str, int]:
        """Imports all extracted records for a document into Neo4j."""
        records = self.storage.get_all_records(document_id)
        if not records:
            logger.warning("No extracted records found for document %s.", document_id)
            return {
                "subjects": 0,
                "vehicles": 0,
                "objects": 0,
                "conditions": 0,
                "sanctions": 0,
                "violations": 0,
                "relationships": 0,
            }

        return self.import_records(records)

    def import_records(self, records: list[ClauseExtractionResult]) -> dict[str, int]:
        """Ingests a list of ClauseExtractionResult objects into Neo4j."""
        subjects_payload: dict[str, dict[str, Any]] = {}
        vehicles_payload: dict[str, dict[str, Any]] = {}
        objects_payload: dict[str, dict[str, Any]] = {}
        conditions_payload: dict[str, dict[str, Any]] = {}
        sanctions_payload: dict[str, dict[str, Any]] = {}
        violations_payload: list[dict[str, Any]] = []

        # Behavioral relationships
        commits_rels: list[dict[str, Any]] = []
        applies_to_rels: list[dict[str, Any]] = []
        has_sanction_rels: list[dict[str, Any]] = []
        causes_rels: list[dict[str, Any]] = []
        enforced_by_rels: list[dict[str, Any]] = []

        # Normative & Conditions relationships
        under_cond_rels: list[dict[str, Any]] = []
        has_exception_rels: list[dict[str, Any]] = []
        defines_violation_rels: list[dict[str, Any]] = []
        prohibits_rels: list[dict[str, Any]] = []
        mandates_rels: list[dict[str, Any]] = []
        permits_rels: list[dict[str, Any]] = []

        # Semantic & Taxonomy relationships
        operates_rels: list[dict[str, Any]] = []
        involves_obj_rels: list[dict[str, Any]] = []
        located_at_rels: list[dict[str, Any]] = []
        subclass_of_rels: list[dict[str, Any]] = []
        comprises_rels: list[dict[str, Any]] = []
        relates_to_rels: list[dict[str, Any]] = []

        for record in records:
            # 1. Map subjects
            subj_by_name: dict[str, str] = {}
            for subj in record.subjects:
                subjects_payload[subj.id] = {
                    "id": subj.id,
                    "name": subj.name,
                    "subtype": subj.subtype,
                }
                subj_by_name[subj.name] = subj.id

            # 2. Map vehicles
            veh_by_name: dict[str, str] = {}
            for veh in record.vehicles:
                vehicles_payload[veh.id] = {
                    "id": veh.id,
                    "name": veh.name,
                    "subtype": veh.subtype,
                }
                veh_by_name[veh.name] = veh.id

            # 3. Map objects
            obj_by_name: dict[str, str] = {}
            for obj in record.objects:
                objects_payload[obj.id] = {
                    "id": obj.id,
                    "name": obj.name,
                    "subtype": obj.subtype,
                }
                obj_by_name[obj.name] = obj.id

            # 4. Map conditions
            cond_by_desc: dict[str, str] = {}
            for cond in record.conditions:
                conditions_payload[cond.id] = {
                    "id": cond.id,
                    "description": cond.description,
                    "subtype": cond.subtype,
                }
                cond_by_desc[cond.description] = cond.id

            # 5. Map sanctions
            sanc_id_by_desc: dict[str, str] = {}
            for s_idx, sanc in enumerate(record.sanctions, start=1):
                s_id = f"sanc_{record.clause_id}_{s_idx}"
                sanc_id_by_desc[sanc.description] = s_id
                sanctions_payload[s_id] = {
                    "id": s_id,
                    "description": sanc.description,
                    "subtype": sanc.subtype,
                    "fine_amount": sanc.fine_amount or "",
                    "clause_id": record.clause_id,
                }

            # 6. Map violations & slot relationships
            for v_idx, vio in enumerate(record.violations, start=1):
                v_id = f"vio_{record.clause_id}_{v_idx}"
                target_unit_id = vio.point_id or record.clause_id
                violations_payload.append(
                    {
                        "id": v_id,
                        "description": vio.description,
                        "modality": vio.modality,
                        "unit_id": target_unit_id,
                        "clause_id": record.clause_id,
                    }
                )

                # COMMITS
                matching_subj_id = subj_by_name.get(vio.subject_name)
                if matching_subj_id:
                    commits_rels.append(
                        {"subject_id": matching_subj_id, "violation_id": v_id}
                    )

                # APPLIES_TO
                for target_name in vio.applies_to:
                    applies_target_id = veh_by_name.get(
                        target_name
                    ) or subj_by_name.get(target_name)
                    if applies_target_id:
                        applies_to_rels.append(
                            {"violation_id": v_id, "target_id": applies_target_id}
                        )

                # USES_VEHICLE
                if vio.vehicle_name:
                    matching_veh_id = veh_by_name.get(vio.vehicle_name)
                    if matching_veh_id:
                        operates_rels.append(
                            {"violation_id": v_id, "vehicle_id": matching_veh_id}
                        )

                # INVOLVES_OBJECT
                for obj_name in vio.object_names:
                    matching_obj_id = obj_by_name.get(obj_name)
                    if matching_obj_id:
                        involves_obj_rels.append(
                            {"violation_id": v_id, "object_id": matching_obj_id}
                        )

                # UNDER_CONDITION
                for cond_desc in vio.condition_descriptions:
                    matching_cond_id = cond_by_desc.get(cond_desc)
                    if matching_cond_id:
                        under_cond_rels.append(
                            {"violation_id": v_id, "condition_id": matching_cond_id}
                        )

                # HAS_EXCEPTION
                for exc_desc in vio.exception_descriptions:
                    matching_exc_id = cond_by_desc.get(exc_desc)
                    if matching_exc_id:
                        has_exception_rels.append(
                            {"violation_id": v_id, "condition_id": matching_exc_id}
                        )

                # CAUSES
                for cause_desc in vio.cause_descriptions:
                    cause_target_id = cond_by_desc.get(
                        cause_desc
                    ) or sanc_id_by_desc.get(cause_desc)
                    if cause_target_id:
                        causes_rels.append(
                            {"violation_id": v_id, "target_id": cause_target_id}
                        )

                # LOCATED_AT
                for loc_desc in vio.location_descriptions:
                    loc_target_id = cond_by_desc.get(loc_desc)
                    if loc_target_id:
                        located_at_rels.append(
                            {"violation_id": v_id, "condition_id": loc_target_id}
                        )

                # HAS_SANCTION
                for sanc_desc in vio.sanction_descriptions:
                    matched_sanc_id = sanc_id_by_desc.get(sanc_desc)
                    if matched_sanc_id:
                        has_sanction_rels.append(
                            {"violation_id": v_id, "sanction_id": matched_sanc_id}
                        )

                # ENFORCED_BY
                if vio.enforced_by:
                    auth_id = subj_by_name.get(vio.enforced_by)
                    if auth_id:
                        enforced_by_rels.append(
                            {"violation_id": v_id, "subject_id": auth_id}
                        )

                # DEFINES_VIOLATION & Deontic Normative links
                defines_violation_rels.append(
                    {"unit_id": target_unit_id, "violation_id": v_id}
                )
                if vio.modality == "PROHIBITION":
                    prohibits_rels.append(
                        {"unit_id": target_unit_id, "violation_id": v_id}
                    )
                elif vio.modality == "OBLIGATION":
                    mandates_rels.append(
                        {"unit_id": target_unit_id, "violation_id": v_id}
                    )
                elif vio.modality == "PERMISSION":
                    permits_rels.append(
                        {"unit_id": target_unit_id, "violation_id": v_id}
                    )

            # 7. Map explicit semantic cross-entity relations
            for rel in record.relations:
                src_id = (
                    subj_by_name.get(rel.source_name)
                    or veh_by_name.get(rel.source_name)
                    or obj_by_name.get(rel.source_name)
                    or cond_by_desc.get(rel.source_name)
                    or sanc_id_by_desc.get(rel.source_name)
                )
                tgt_id = (
                    subj_by_name.get(rel.target_name)
                    or veh_by_name.get(rel.target_name)
                    or obj_by_name.get(rel.target_name)
                    or cond_by_desc.get(rel.target_name)
                    or sanc_id_by_desc.get(rel.target_name)
                )
                if src_id and tgt_id:
                    if rel.relation == "SUBCLASS_OF":
                        subclass_of_rels.append(
                            {"source_id": src_id, "target_id": tgt_id}
                        )
                    elif rel.relation == "COMPRISES":
                        comprises_rels.append(
                            {"source_id": src_id, "target_id": tgt_id}
                        )
                    elif rel.relation == "RELATES_TO":
                        relates_to_rels.append(
                            {"source_id": src_id, "target_id": tgt_id}
                        )
                    elif rel.relation == "ENFORCED_BY":
                        enforced_by_rels.append(
                            {"violation_id": src_id, "subject_id": tgt_id}
                        )

        total_rels = (
            len(commits_rels)
            + len(applies_to_rels)
            + len(operates_rels)
            + len(involves_obj_rels)
            + len(under_cond_rels)
            + len(has_exception_rels)
            + len(causes_rels)
            + len(located_at_rels)
            + len(has_sanction_rels)
            + len(enforced_by_rels)
            + len(defines_violation_rels)
            + len(prohibits_rels)
            + len(mandates_rels)
            + len(permits_rels)
            + len(subclass_of_rels)
            + len(comprises_rels)
            + len(relates_to_rels)
        )

        if not self.client:
            logger.info(
                "Dry-run: Client is None. Prepared %d violations, %d total relationships.",
                len(violations_payload),
                total_rels,
            )
            return {
                "subjects": len(subjects_payload),
                "vehicles": len(vehicles_payload),
                "objects": len(objects_payload),
                "conditions": len(conditions_payload),
                "sanctions": len(sanctions_payload),
                "violations": len(violations_payload),
                "relationships": total_rels,
            }

        with self.client.session() as session:
            # Merge Nodes
            if subjects_payload:
                session.run(
                    "UNWIND $batch AS row MERGE (s:LegalSubject {id: row.id}) SET s += row",
                    batch=list(subjects_payload.values()),
                )
            if vehicles_payload:
                session.run(
                    "UNWIND $batch AS row MERGE (v:VehicleType {id: row.id}) SET v += row",
                    batch=list(vehicles_payload.values()),
                )
            if objects_payload:
                session.run(
                    "UNWIND $batch AS row MERGE (o:RegulatoryObject {id: row.id}) SET o += row",
                    batch=list(objects_payload.values()),
                )
            if conditions_payload:
                session.run(
                    "UNWIND $batch AS row MERGE (c:ContextCondition {id: row.id}) SET c += row",
                    batch=list(conditions_payload.values()),
                )
            if sanctions_payload:
                session.run(
                    "UNWIND $batch AS row MERGE (s:Sanction {id: row.id}) SET s += row",
                    batch=list(sanctions_payload.values()),
                )
            if violations_payload:
                session.run(
                    "UNWIND $batch AS row MERGE (v:Violation {id: row.id}) SET v += row",
                    batch=violations_payload,
                )

            # Merge Relationships
            if commits_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (s:LegalSubject {id: row.subject_id})
                    MATCH (v:Violation {id: row.violation_id})
                    MERGE (s)-[:COMMITS]->(v)
                    """,
                    batch=commits_rels,
                )
            if applies_to_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (target {id: row.target_id})
                    MERGE (v)-[:APPLIES_TO]->(target)
                    """,
                    batch=applies_to_rels,
                )
            if operates_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (veh:VehicleType {id: row.vehicle_id})
                    MERGE (v)-[:USES_VEHICLE]->(veh)
                    """,
                    batch=operates_rels,
                )
            if involves_obj_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (o:RegulatoryObject {id: row.object_id})
                    MERGE (v)-[:INVOLVES_OBJECT]->(o)
                    """,
                    batch=involves_obj_rels,
                )
            if under_cond_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (c:ContextCondition {id: row.condition_id})
                    MERGE (v)-[:UNDER_CONDITION]->(c)
                    """,
                    batch=under_cond_rels,
                )
            if has_exception_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (c:ContextCondition {id: row.condition_id})
                    MERGE (v)-[:HAS_EXCEPTION]->(c)
                    """,
                    batch=has_exception_rels,
                )
            if causes_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (target {id: row.target_id})
                    MERGE (v)-[:CAUSES]->(target)
                    """,
                    batch=causes_rels,
                )
            if located_at_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (c:ContextCondition {id: row.condition_id})
                    MERGE (v)-[:LOCATED_AT]->(c)
                    """,
                    batch=located_at_rels,
                )
            if has_sanction_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (s:Sanction {id: row.sanction_id})
                    MERGE (v)-[:HAS_SANCTION]->(s)
                    """,
                    batch=has_sanction_rels,
                )
            if enforced_by_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (v:Violation {id: row.violation_id})
                    MATCH (s:LegalSubject {id: row.subject_id})
                    MERGE (v)-[:ENFORCED_BY]->(s)
                    """,
                    batch=enforced_by_rels,
                )
            if defines_violation_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (u {id: row.unit_id})
                    MATCH (v:Violation {id: row.violation_id})
                    MERGE (u)-[:DEFINES_VIOLATION]->(v)
                    """,
                    batch=defines_violation_rels,
                )
            if prohibits_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (u {id: row.unit_id})
                    MATCH (v:Violation {id: row.violation_id})
                    MERGE (u)-[:PROHIBITS]->(v)
                    """,
                    batch=prohibits_rels,
                )
            if mandates_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (u {id: row.unit_id})
                    MATCH (v:Violation {id: row.violation_id})
                    MERGE (u)-[:MANDATES]->(v)
                    """,
                    batch=mandates_rels,
                )
            if permits_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (u {id: row.unit_id})
                    MATCH (v:Violation {id: row.violation_id})
                    MERGE (u)-[:PERMITS]->(v)
                    """,
                    batch=permits_rels,
                )
            if subclass_of_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (src {id: row.source_id})
                    MATCH (tgt {id: row.target_id})
                    MERGE (src)-[:SUBCLASS_OF]->(tgt)
                    """,
                    batch=subclass_of_rels,
                )
            if comprises_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (src {id: row.source_id})
                    MATCH (tgt {id: row.target_id})
                    MERGE (src)-[:COMPRISES]->(tgt)
                    """,
                    batch=comprises_rels,
                )
            if relates_to_rels:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (src {id: row.source_id})
                    MATCH (tgt {id: row.target_id})
                    MERGE (src)-[:RELATES_TO]->(tgt)
                    """,
                    batch=relates_to_rels,
                )

        logger.info(
            "Ingested IE entities: %d subjects, %d vehicles, %d objects, %d conditions, %d violations, %d sanctions with %d relationships.",
            len(subjects_payload),
            len(vehicles_payload),
            len(objects_payload),
            len(conditions_payload),
            len(violations_payload),
            len(sanctions_payload),
            total_rels,
        )
        return {
            "subjects": len(subjects_payload),
            "vehicles": len(vehicles_payload),
            "objects": len(objects_payload),
            "conditions": len(conditions_payload),
            "sanctions": len(sanctions_payload),
            "violations": len(violations_payload),
            "relationships": total_rels,
        }
