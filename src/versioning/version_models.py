from dataclasses import dataclass


@dataclass
class CanonicalProvision:
    canonical_provision_id: str
    document_id: str
    level: str
    number: str | None


@dataclass
class ProvisionVersion:
    version_id: str
    canonical_provision_id: str
    valid_from: str | None
    valid_to: str | None
    content: object
    is_current: bool
    produced_by: str | None
    effective_status: str = "NORMAL"
    external_rule_ids: list[str] | None = None
