from datetime import date

def validate_effective_rule_schema(rule: dict):

    required_fields = {
        "rule_id","rule_type", "source_document",
        "source_unit","effective_from","effective_to","status"
    }

    missing = required_fields - rule.keys()
    if missing:
        raise ValueError(f"Effective rule: {rule['rule_id']}"
            f"Missing fields: {missing}")

    return True

def parse_iso_date(value):
    if value is None:
        return None
    return date.fromisoformat(value)

def validate_effective_rule_dates(rule: dict):

    effective_from = parse_iso_date(rule.get("effective_from"))
    effective_to = parse_iso_date(rule.get("effective_to"))

    if (
        effective_from is not None and
        effective_to is not None and
        effective_to <= effective_from
    ):
        raise ValueError(f"Invalid effective interval: "
            f"{rule['rule_id']}")
    
    return True

def validate_external_rule(rule):

    if rule.get("rule_type") != "EXTERNAL_RULE":
        return True

    if not rule.get("external_basis"):
        raise ValueError(
            f"EXTERNAL_RULE missing external_basis: "
            f"{rule['rule_id']}"
        )

    if rule.get("status") != "EXTERNAL":
        raise ValueError(
            f"EXTERNAL_RULE invalid status: "
            f"{rule['rule_id']}"
        )

    return True

def validate_effective_rule_targets(rule, structure_node_index, resolver):

    target_document = resolver.resolve_document(rule.get("target_document"))
    rule_type = rule.get("rule_type")

    if target_document not in structure_node_index:
        raise ValueError("Target document not found: "
            f"{target_document}")

    if rule_type == "GENERAL":
        return True  

    elif rule_type in ("EXPLICIT", "EXTERNAL_RULE"):  

        for target in rule.get("targets",[]):
            if not target:
                raise ValueError(
                    f"Rule {rule_type} rule has no targets: "
                    f"{rule['rule_id']}")

            unit_id = resolver.resolve_unit(target.get("unit_id"))
            if not unit_id:
                raise ValueError("Target missing unit_id: "
                    f"{rule['rule_id']}")
            if unit_id not in structure_node_index:
                raise ValueError("Target unit not found: "
                    f"{unit_id} in {target_document}")
    else:
        raise ValueError("Invalid rule type: "
            f"{rule['rule_type']}")
    return True

def validate_effective_rule_duplicates(
    rules, resolver
):

    seen = set()

    for rule in rules:

        key = (
            resolver.resolve_unit(rule.get("source_unit")),
            rule.get("rule_type"),
            resolver.resolve_document(rule.get("target_document")),
            tuple(
                resolver.resolve_unit(target.get("unit_id"))
                for target in rule.get(
                    "targets",
                    []
                )
            ),
            rule.get("effective_from"),
            rule.get("effective_to"),
            rule.get("external_basis"),
        )

        if key in seen:
            raise ValueError(
                f"Duplicate effective rule: "
                f"{rule['rule_id']}"
            )

        seen.add(key)

    return True

def validate_effective_rules(
    rules,
    structure_node_index,
    resolver
):

    for rule in rules:

        validate_effective_rule_schema(
            rule
        )

        validate_effective_rule_dates(
            rule
        )

        validate_external_rule(
            rule
        )

        validate_effective_rule_targets(
            rule,
            structure_node_index,
            resolver
        )

    validate_effective_rule_duplicates(
        rules,
        resolver
    )

    return True

