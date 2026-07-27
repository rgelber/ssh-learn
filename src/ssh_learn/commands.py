"""Handlers for each ssh-learn subcommand."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from .naming import (
    _disambiguate_alias,
    alias_base,
    expand_host_args,
    matches_pattern,
    resolve_alias,
    sanitize_alias,
)
from .paths import learned_file
from .recorder import record_connection
from .sshcfg import render_config, validate_generated_config, write_learned_config
from .store import (
    load_metadata,
    merge_duplicate_hosts,
    metadata_lock,
    migrate_entry,
    save_metadata,
)
from .timeutil import age_of, humanize_age


def command_record(args: argparse.Namespace) -> int:
    try:
        with metadata_lock():
            status, alias_name = record_connection(
                args.destination,
                args.ssh_arg,
                args.tag,
            )
    except RuntimeError as error:
        print(f"Unable to record SSH host: {error}", file=sys.stderr)
        return 1

    if status != "unchanged":
        print(f"{status}\t{alias_name}")

    return 0


def command_list(args: argparse.Namespace) -> int:
    metadata = load_metadata()
    merge_duplicate_hosts(metadata)
    rows = []

    for alias_name, entry in metadata.get("hosts", {}).items():
        tags = entry.get("tags", [])

        if args.tag and sanitize_alias(args.tag) not in tags:
            continue

        if args.pattern and not any(
            matches_pattern(alias_name, entry, pattern)
            for pattern in args.pattern
        ):
            continue

        rows.append(
            (
                alias_name,
                entry.get("hostname", ""),
                entry.get("user", ""),
                str(entry.get("port") or "22"),
                int(entry.get("count", 0)),
                entry.get("last_used", ""),
                ",".join(tags),
            )
        )

    if args.sort == "used":
        rows.sort(key=lambda row: row[5], reverse=True)
    elif args.sort == "count":
        rows.sort(key=lambda row: row[4], reverse=True)
    else:
        rows.sort(key=lambda row: row[0])

    if args.names:
        for row in rows:
            print(row[0])
        return 0

    if not rows:
        print("No learned hosts yet. Connect somewhere with ssh first.")
        return 0

    print(
        f"{'ALIAS':<28} "
        f"{'DESTINATION':<52} "
        f"{'COUNT':>6} "
        f"{'LAST USED':<12} "
        "TAGS"
    )

    for alias_name, hostname, user, port, count, last_used, tags in rows:
        destination = f"{user}@{hostname}" if user else hostname

        if port != "22":
            destination = f"{destination}:{port}"

        print(
            f"{alias_name:<28} "
            f"{destination:<52} "
            f"{count:>6} "
            f"{humanize_age(last_used):<12} "
            f"{tags}"
        )

    return 0


def command_show(args: argparse.Namespace) -> int:
    metadata = load_metadata()
    merge_duplicate_hosts(metadata)
    hosts = metadata.get("hosts", {})

    resolved, errors = expand_host_args(hosts, args.host)

    for message in errors:
        print(f"ssh-learn show: {message}", file=sys.stderr)

    if not resolved:
        return 1

    if len(resolved) == 1:
        print(json.dumps(hosts[resolved[0]], indent=2, sort_keys=True))
    else:
        combined = {alias: hosts[alias] for alias in resolved}
        print(json.dumps(combined, indent=2, sort_keys=True))

    return 1 if errors else 0


def command_remove(args: argparse.Namespace) -> int:
    with metadata_lock():
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        hosts = metadata.get("hosts", {})

        resolved, errors = expand_host_args(hosts, args.host)

        for message in errors:
            print(f"ssh-learn remove: {message}", file=sys.stderr)

        if not resolved:
            return 1

        if args.dry_run:
            for alias_name in resolved:
                print(f"would remove: {alias_name}")
            print(
                f"{len(resolved)} host(s) would be removed. "
                "Re-run without --dry-run."
            )
            return 1 if errors else 0

        for alias_name in resolved:
            del hosts[alias_name]
            print(f"Removed SSH host: {alias_name}")

        save_metadata(metadata)
        write_learned_config(metadata)

    return 1 if errors else 0


def command_rename(args: argparse.Namespace) -> int:
    with metadata_lock():
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        hosts = metadata.get("hosts", {})

        try:
            old_alias = resolve_alias(hosts, args.host)
        except KeyError as error:
            print(f"Host not found: {error.args[0]}", file=sys.stderr)
            return 1

        new_alias = sanitize_alias(args.new_alias)

        if new_alias in hosts and new_alias != old_alias:
            print(f"Alias already exists: {new_alias}", file=sys.stderr)
            return 1

        entry = hosts.pop(old_alias)
        entry["alias_locked"] = True
        hosts[new_alias] = entry
        save_metadata(metadata)
        write_learned_config(metadata)

    print(f"Renamed {old_alias} to {new_alias}")
    return 0


def command_relabel(args: argparse.Namespace) -> int:
    with metadata_lock():
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        hosts = metadata.get("hosts", {})

        errors: list[str] = []

        if args.host:
            targets, errors = expand_host_args(hosts, args.host)
            for message in errors:
                print(f"ssh-learn relabel: {message}", file=sys.stderr)
        else:
            targets = sorted(hosts)

        renames: list[tuple[str, str]] = []
        skipped_locked: list[str] = []
        taken = set(hosts)

        for alias_name in targets:
            entry = hosts[alias_name]

            if entry.get("alias_locked") and not args.force:
                skipped_locked.append(alias_name)
                continue

            hostname = entry.get("hostname", "")
            destination = entry.get("original_destination", "") or hostname
            desired = sanitize_alias(alias_base(destination, hostname))

            if not desired or desired == alias_name:
                continue

            # Free this alias before resolving collisions so a host can keep
            # a variant of its own name.
            taken.discard(alias_name)
            final = _disambiguate_alias(desired, hostname, taken)
            taken.add(final)
            renames.append((alias_name, final))

        for alias_name in skipped_locked:
            print(
                f"skipped (manually named, use --force): {alias_name}",
                file=sys.stderr,
            )

        if not renames:
            print("All aliases already match their host names.")
            return 1 if errors else 0

        for old_alias, new_alias in renames:
            marker = "would rename" if args.dry_run else "renamed"
            print(f"{marker}: {old_alias} -> {new_alias}")

        if args.dry_run:
            print(
                f"{len(renames)} alias(es) would change. "
                "Re-run without --dry-run."
            )
            return 0

        for old_alias, new_alias in renames:
            hosts[new_alias] = hosts.pop(old_alias)

        save_metadata(metadata)
        write_learned_config(metadata)

    return 1 if errors else 0


def command_tag(args: argparse.Namespace) -> int:
    with metadata_lock():
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        hosts = metadata.get("hosts", {})

        resolved, errors = expand_host_args(hosts, args.host)

        for message in errors:
            print(f"ssh-learn tag: {message}", file=sys.stderr)

        if not resolved:
            return 1

        for alias_name in resolved:
            entry = hosts[alias_name]
            migrate_entry(entry)
            manual_tags = set(entry.get("manual_tags", []))

            for tag in args.add:
                manual_tags.add(sanitize_alias(tag))

            for tag in args.remove:
                manual_tags.discard(sanitize_alias(tag))

            auto_tags = set(entry.get("auto_tags", []))
            entry["manual_tags"] = sorted(tag for tag in manual_tags if tag)
            entry["tags"] = sorted(manual_tags | auto_tags)

            print(
                f"Updated tags for {alias_name}: "
                f"{' '.join(entry['tags'])}"
            )

        save_metadata(metadata)
        write_learned_config(metadata)

    return 1 if errors else 0


def command_tags(args: argparse.Namespace) -> int:
    metadata = load_metadata()
    merge_duplicate_hosts(metadata)

    counts: dict[str, int] = {}

    for entry in metadata.get("hosts", {}).values():
        for tag in entry.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1

    if args.names:
        for tag in sorted(counts):
            print(tag)
        return 0

    if not counts:
        print("No tags yet.")
        return 0

    width = max(len(tag) for tag in counts)

    for tag in sorted(counts):
        plural = "" if counts[tag] == 1 else "s"
        print(f"{tag:<{width}}  {counts[tag]} host{plural}")

    return 0


def command_prune(args: argparse.Namespace) -> int:
    cutoff = dt.timedelta(days=args.days)

    with metadata_lock():
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        hosts = metadata.get("hosts", {})

        stale: list[tuple[str, str]] = []

        for alias_name, entry in hosts.items():
            age = age_of(entry.get("last_used"))

            if age is None or age > cutoff:
                stale.append((alias_name, entry.get("last_used", "")))

        if not stale:
            print(f"No hosts unused for more than {args.days} days.")
            return 0

        for alias_name, last_used in sorted(stale):
            marker = "would remove" if args.dry_run else "removed"
            print(f"{marker}: {alias_name} (last used {humanize_age(last_used)})")

        if args.dry_run:
            print(f"{len(stale)} host(s) would be pruned. Re-run without --dry-run.")
            return 0

        for alias_name, _last_used in stale:
            hosts.pop(alias_name, None)

        save_metadata(metadata)
        write_learned_config(metadata)

    print(f"Pruned {len(stale)} host(s).")
    return 0


def command_rebuild(_args: argparse.Namespace) -> int:
    with metadata_lock():
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        save_metadata(metadata)
        write_learned_config(metadata)

    print(f"Rebuilt {learned_file()}")
    return 0


def command_validate(_args: argparse.Namespace) -> int:
    metadata = load_metadata()
    merge_duplicate_hosts(metadata)
    config_text = render_config(metadata)
    aliases = sorted(metadata.get("hosts", {}))
    validate_generated_config(config_text, aliases)
    print("SSH learned configuration is valid.")
    return 0

