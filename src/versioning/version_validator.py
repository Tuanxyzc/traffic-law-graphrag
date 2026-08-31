def validate_version_timeline(provision_id, versions, valid_action_ids=None):
    if not versions:
        raise ValueError(f"No versions: {provision_id}")
    seen, current_count = set(), 0
    for index, version in enumerate(versions):
        if version.version_id in seen:
            raise ValueError(f"Duplicate version_id: {version.version_id}")
        seen.add(version.version_id)
        current_count += bool(version.is_current)
        if version.effective_status not in {"NORMAL", "EXTERNAL"}:
            raise ValueError(f"Invalid effective_status: {version.version_id}")
        if version.effective_status == "EXTERNAL" and not version.external_rule_ids:
            raise ValueError(
                f"EXTERNAL version missing external_rule_ids: {version.version_id}"
            )
        if (
            valid_action_ids is not None
            and version.produced_by is not None
            and version.produced_by not in valid_action_ids
        ):
            raise ValueError(f"Invalid produced_by: {version.version_id}")
        if index:
            previous = versions[index - 1]
            if (
                previous.valid_from
                and version.valid_from
                and previous.valid_from > version.valid_from
            ):
                raise ValueError(f"Timeline not sorted: {provision_id}")
            if (
                previous.valid_to is not None
                and version.valid_from is not None
                and previous.valid_to != version.valid_from
            ):
                raise ValueError(f"Timeline gap/overlap: {provision_id}")
    if current_count > 1:
        raise ValueError(f"Multiple current versions: {provision_id}")
    return True


def validate_all_versions(versions_by_provision, valid_action_ids=None):
    all_ids = set()
    for provision_id, versions in versions_by_provision.items():
        for version in versions:
            if version.version_id in all_ids:
                raise ValueError(f"Duplicate version_id: {version.version_id}")
            all_ids.add(version.version_id)
        validate_version_timeline(provision_id, versions, valid_action_ids)
    return True
