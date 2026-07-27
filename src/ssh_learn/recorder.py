"""Turn a successful connection into a learned host."""

from __future__ import annotations

import os
from pathlib import Path

from .facts import (
    collect_remote_facts,
    facts_are_fresh,
    infer_hostname_tags,
    tags_from_remote_facts,
)
from .naming import (
    canonical_hostname,
    find_existing_alias,
    generate_alias,
    normalize_host,
    sanitize_alias,
)
from .sshcfg import get_effective_config, write_learned_config
from .store import (
    load_metadata,
    meaningful_entry,
    merge_duplicate_hosts,
    migrate_entry,
    save_metadata,
)
from .timeutil import now_iso


def record_connection(
    destination: str,
    ssh_args: list[str],
    custom_tags: list[str],
) -> tuple[str, str]:
    effective = get_effective_config(destination, ssh_args)
    metadata = load_metadata()
    merge_duplicate_hosts(metadata)
    hosts = metadata["hosts"]

    discovered_hostname = normalize_host(effective.get("hostname"))
    user = effective.get("user")
    port = str(effective.get("port") or "22")
    proxyjump = effective.get("proxyjump")

    alias_name = find_existing_alias(
        hosts,
        destination,
        discovered_hostname,
        port,
    )

    if alias_name is None:
        alias_name = generate_alias(destination, discovered_hostname, hosts)

    is_new = alias_name not in hosts
    old_entry = hosts.get(alias_name, {})
    migrate_entry(old_entry)

    hostname = canonical_hostname(
        discovered_hostname,
        old_entry.get("hostname"),
        destination,
    )

    # Refresh remote facts only when they are missing or stale, so repeat
    # connections to a known host record instantly.
    old_facts = old_entry.get("remote_facts", {})

    if os.environ.get("SSH_LEARN_NO_FACTS") or facts_are_fresh(old_facts):
        remote_facts = old_facts
    else:
        remote_facts = collect_remote_facts(destination, ssh_args) or old_facts

    identities = effective.get("identityfile", [])
    if isinstance(identities, str):
        identities = [identities]

    saved_identities: list[str] = []

    for identity in identities:
        expanded = Path(os.path.expanduser(identity))

        if expanded.exists() and identity not in saved_identities:
            saved_identities.append(identity)

    manual_tags = set(old_entry.get("manual_tags", []))
    manual_tags.update(sanitize_alias(tag) for tag in custom_tags if tag)

    auto_tags = infer_hostname_tags(hostname)
    if isinstance(remote_facts, dict):
        auto_tags.update(tags_from_remote_facts(remote_facts))

    all_tags = manual_tags | auto_tags

    new_entry = {
        "hostname": hostname,
        "user": user,
        "port": port,
        "proxyjump": (
            proxyjump
            if proxyjump and str(proxyjump).lower() != "none"
            else None
        ),
        "identityfiles": saved_identities,
        "manual_tags": sorted(tag for tag in manual_tags if tag),
        "auto_tags": sorted(tag for tag in auto_tags if tag),
        "tags": sorted(tag for tag in all_tags if tag),
        "first_seen": old_entry.get("first_seen", now_iso()),
        "last_used": now_iso(),
        "count": int(old_entry.get("count", 0)) + 1,
        "original_destination": destination,
        "remote_facts": remote_facts,
    }

    if old_entry.get("alias_locked"):
        new_entry["alias_locked"] = True

    changed = meaningful_entry(old_entry) != meaningful_entry(new_entry)
    hosts[alias_name] = new_entry

    save_metadata(metadata)
    write_learned_config(metadata)

    if is_new:
        return "saved", alias_name

    if changed:
        return "updated", alias_name

    return "unchanged", alias_name

