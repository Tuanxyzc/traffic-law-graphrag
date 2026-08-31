from dataclasses import dataclass
from datetime import date


@dataclass
class EffectiveResult:
    status: str
    rule_id: str | None
    target_unit: str
    effective_from: str | None
    effective_to: str | None
    source_unit: str | None
    external_basis: str | None


def parse_iso_date(value):
    if value is None:
        return None
    return date.fromisoformat(value)


def is_rule_active(rule: dict, as_of_date: date) -> bool:

    effective_from = parse_iso_date(rule.get("effective_from"))
    effective_to = parse_iso_date(rule.get("effective_to"))

    if effective_from is None and effective_to is None:
        return False

    if effective_from is not None and as_of_date < effective_from:
        return False

    if effective_to is not None and as_of_date >= effective_to:
        return False

    return True


def get_applicable_rules(
    rules: list[dict], target_unit: str, as_of_date: date, resolver
):

    applicable = []

    for rule in rules:
        if not is_rule_active(rule, as_of_date):
            continue

        rule_type = rule.get("rule_type")

        # GENERAL
        if rule_type == "GENERAL":
            applicable.append(rule)
            continue

        for target in rule.get("targets", []):
            if resolver.resolve_unit(target.get("unit_id")) == target_unit:
                applicable.append(rule)
                break

    return applicable


def select_effective_rule(applicable_rules):

    if not applicable_rules:
        return None

    explicit_rules = [
        rule for rule in applicable_rules if rule.get("rule_type") == "EXPLICIT"
    ]

    if explicit_rules:
        return max(explicit_rules, key=lambda r: r.get("effective_from") or "")

    general_rules = [
        rule for rule in applicable_rules if rule.get("rule_type") == "GENERAL"
    ]

    if general_rules:
        return max(general_rules, key=lambda r: r.get("effective_from") or "")

    return applicable_rules[0]


def get_rules_for_target(rules, target_unit, resolver):
    matched = []

    for rule in rules:
        if rule.get("rule_type") == "GENERAL":
            matched.append(rule)
            continue

        for target in rule.get("targets", []):
            if resolver.resolve_unit(target.get("unit_id")) == target_unit:
                matched.append(rule)
                break

    return matched


def evaluate_unit(rules, target_unit, as_of_date, resolver):

    target_rules = get_rules_for_target(rules, target_unit, resolver)

    external_rules = [r for r in target_rules if r.get("rule_type") == "EXTERNAL_RULE"]

    if external_rules:
        return EffectiveResult(
            status="EXTERNAL",
            rule_id=external_rules[0]["rule_id"],
            target_unit=target_unit,
            effective_from=None,
            effective_to=None,
            source_unit=external_rules[0].get("source_unit"),
            external_basis=external_rules[0].get("external_basis"),
        )

    active_rules = [r for r in target_rules if is_rule_active(r, as_of_date)]

    if active_rules:
        rule = select_effective_rule(active_rules)

        return EffectiveResult(
            status="ACTIVE",
            rule_id=rule["rule_id"],
            target_unit=target_unit,
            effective_from=rule.get("effective_from"),
            effective_to=rule.get("effective_to"),
            source_unit=rule.get("source_unit"),
            external_basis=None,
        )

    dated_rules = [r for r in target_rules if (r.get("rule_type") != "EXTERNAL_RULE")]

    if dated_rules:
        earliest = min(
            (
                parse_iso_date(r.get("effective_from"))
                for r in dated_rules
                if r.get("effective_from")
            ),
            default=None,
        )

        if earliest is not None and as_of_date < earliest:
            return EffectiveResult(
                status="NOT_YET_EFFECTIVE",
                rule_id=None,
                target_unit=target_unit,
                effective_from=earliest.isoformat(),
                effective_to=None,
                source_unit=None,
                external_basis=None,
            )

        return EffectiveResult(
            status="INACTIVE",
            rule_id=None,
            target_unit=target_unit,
            effective_from=None,
            effective_to=None,
            source_unit=None,
            external_basis=None,
        )

    return EffectiveResult(
        status="UNKNOWN",
        rule_id=None,
        target_unit=target_unit,
        effective_from=None,
        effective_to=None,
        source_unit=None,
        external_basis=None,
    )
