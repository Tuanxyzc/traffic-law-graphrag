from copy import deepcopy
from datetime import date
from src.versioning.version_models import CanonicalProvision, ProvisionVersion

class VersionBuilder:
    def __init__(self, structure_nodes_by_document, amendment_actions, effective_rules_by_document, resolver):
        self.structure_nodes_by_document = structure_nodes_by_document
        self.amendment_actions = amendment_actions
        self.effective_rules_by_document = effective_rules_by_document
        self.resolver = resolver
        self.provisions, self.versions = {}, {}

    @staticmethod
    def parse_date(value):
        if value is None: return None
        return value if isinstance(value, date) else date.fromisoformat(value)
    @staticmethod
    def document_id_from_unit(unit_id): return unit_id.split("_D", 1)[0]
    @staticmethod
    def level_from_node(node):
        return {"Article":"ARTICLE", "Clause":"CLAUSE", "Point":"POINT"}[node.label]

    def build_structure_index(self):
        for doc, nodes in self.structure_nodes_by_document.items():
            for n in nodes:
                if n.label in {"Article","Clause","Point"}:
                    self.provisions[n.id] = CanonicalProvision(n.id, doc, self.level_from_node(n), n.properties.get("number"))
                    self.versions[n.id] = []

    def get_document_effective_from(self, document_id):
        vals = [self.parse_date(r["effective_from"]) for r in self.effective_rules_by_document.get(document_id, [])
                if r.get("rule_type") == "GENERAL" and r.get("effective_from")]
        return min(vals) if vals else None

    def get_external_rules_for_target(self, target_unit):
        doc = self.document_id_from_unit(target_unit)
        return [r for r in self.effective_rules_by_document.get(doc, []) if r.get("rule_type")=="EXTERNAL_RULE"
                and any(t.get("unit_id") == target_unit for t in r.get("targets", []))]

    def get_provision_effective_from(self, document_id, target_unit):
        if self.get_external_rules_for_target(target_unit): return None
        rules = self.effective_rules_by_document.get(document_id, [])
        vals = [self.parse_date(r["effective_from"]) for r in rules if r.get("rule_type")=="EXPLICIT" and r.get("effective_from")
                and any(t.get("unit_id") == target_unit for t in r.get("targets", []))]
        value = min(vals) if vals else self.get_document_effective_from(document_id)
        if value is None: raise ValueError(f"Khong xac dinh duoc ngay hieu luc: {target_unit}")
        return value

    def build_initial_versions(self):
        for doc, nodes in self.structure_nodes_by_document.items():
            for n in nodes:
                if n.id not in self.provisions: continue
                external = self.get_external_rules_for_target(n.id)
                effective = self.get_provision_effective_from(doc, n.id)
                self.versions[n.id].append(ProvisionVersion(f"{n.id}_V1", n.id, effective.isoformat() if effective else None, None,
                    deepcopy(n.properties), True, None, "EXTERNAL" if external else "NORMAL", [r.get("rule_id") for r in external] or None))

    def get_current_version(self, target_unit):
        versions = self.versions.get(target_unit)
        return versions[-1] if versions else None
    def close_current_version(self, target_unit, effective_date):
        current = self.get_current_version(target_unit)
        if current is None: raise ValueError(f"Khong co version hien tai: {target_unit}")
        current.valid_to, current.is_current = effective_date.isoformat(), False
    def create_version(self, target_unit, effective_date, content, action_id):
        current = self.get_current_version(target_unit)
        if current and current.is_current: self.close_current_version(target_unit, effective_date)
        n = len(self.versions.setdefault(target_unit, [])) + 1
        self.versions[target_unit].append(ProvisionVersion(f"{target_unit}_V{n}", target_unit, effective_date.isoformat(), None, deepcopy(content), True, action_id))

    @staticmethod
    def get_replacement_for_target(item, target):
        tree, path = item.get("replacement_tree"), target.get("replacement_path")
        if tree is None or path is None: raise ValueError("SUA_DOI thieu replacement_path hoac replacement_tree")
        cur = tree
        for p in path: cur = cur[p]
        return cur

    def apply_sua_doi(self, item, action, effective_date, action_id):
        for target in action.get("targets", []):
            unit = self.resolver.resolve_unit(target.get("target_unit"))
            if unit not in self.provisions: raise ValueError(f"SUA_DOI target khong ton tai: {unit}")
            self.create_version(unit, effective_date, self.get_replacement_for_target(item, target), action_id)
    def apply_bai_bo(self, action, effective_date):
        for target in action.get("targets", []):
            unit = self.resolver.resolve_unit(target.get("target_unit"))
            if unit not in self.provisions: raise ValueError(f"BAI_BO target khong ton tai: {unit}")
            self.close_current_version(unit, effective_date)

    @staticmethod
    def get_created_unit_content(item, created):
        tree, level, number = item.get("replacement_tree"), created.get("unit_level"), str(created.get("number"))
        if tree is None: raise ValueError("BO_SUNG thieu replacement_tree")
        key = {"ARTICLE":"articles", "CLAUSE":"clauses", "POINT":"points"}.get(level)
        vals = tree.get(key, []) if key else []
        singular = {"ARTICLE":"article", "CLAUSE":"clause", "POINT":"point"}.get(level)
        if singular in tree: vals = list(vals) + [tree[singular]]
        for v in vals:
            if str(v.get("number")) == number: return v
        raise ValueError(f"Khong tim thay replacement cho created unit: {created}")

    def apply_bo_sung(self, item, action, effective_date, action_id):
        for c in action.get("created_units", []):
            unit = self.resolver.resolve_unit(c.get("unit_id"))
            if not unit or unit in self.provisions: raise ValueError(f"BO_SUNG duplicate/invalid provision: {unit}")
            self.provisions[unit] = CanonicalProvision(unit, self.document_id_from_unit(unit), c.get("unit_level"), c.get("number")); self.versions[unit] = []
            self.create_version(unit, effective_date, self.get_created_unit_content(item, c), action_id)

    def get_action_effective_date(self, source_document, source_unit, action=None):
        rules = self.effective_rules_by_document.get(source_document, [])
        if any(r.get("rule_type")=="EXTERNAL_RULE" and any(t.get("unit_id")==source_unit for t in r.get("targets", [])) for r in rules):
            raise ValueError(f"Amendment action unresolved by EXTERNAL_RULE: {source_unit}")
        vals = [self.parse_date(r["effective_from"]) for r in rules if r.get("rule_type")=="EXPLICIT" and r.get("effective_from") and any(t.get("unit_id")==source_unit for t in r.get("targets", []))]
        value = min(vals) if vals else self.get_document_effective_from(source_document)
        if value is None: raise ValueError(f"Khong xac dinh duoc ngay hieu luc amendment: {source_unit}")
        return value

    def apply_action(self, record):
        item, action = record.get("item", record), record.get("action", record)
        source_doc = self.resolver.resolve_document(record["source_document"])
        source_unit = self.resolver.resolve_unit(record["source_unit"])
        d = self.get_action_effective_date(source_doc, source_unit, action)
        op, aid = action.get("operation"), record.get("action_id")
        if op == "SUA_DOI": self.apply_sua_doi(item, action, d, aid)
        elif op == "BAI_BO": self.apply_bai_bo(action, d)
        elif op == "BO_SUNG": self.apply_bo_sung(item, action, d, aid)

    def build_amendment_timeline(self):
        entries = [(self.get_action_effective_date(self.resolver.resolve_document(r["source_document"]), self.resolver.resolve_unit(r["source_unit"]), r.get("action")), r) for r in self.amendment_actions]
        entries.sort(key=lambda x: (x[0], x[1]["action_id"]))
        return [r for _, r in entries]
    def build(self):
        self.build_structure_index(); self.build_initial_versions()
        for r in self.build_amendment_timeline(): self.apply_action(r)
        return self.provisions, self.versions
