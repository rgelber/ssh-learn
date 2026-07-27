"""The learned-hosts metadata store: load, save, lock, migrate."""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .facts import infer_hostname_tags, tags_from_remote_facts
from .naming import host_short, is_fqdn, is_ip, normalize_host, sanitize_alias
from .paths import (
    backup_dir,
    conf_dir,
    control_dir,
    learned_file,
    lock_file,
    metadata_file,
    ssh_dir,
)
from .timeutil import now_iso

MAX_BACKUPS = 10


def ensure_layout() -> None:
    for directory in (ssh_dir(), conf_dir(), control_dir(), backup_dir()):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)

    if not learned_file().exists():
        learned_file().touch()

    learned_file().chmod(0o600)


@contextlib.contextmanager
def metadata_lock() -> Iterator[None]:
    """Serialize writers so concurrent recordings cannot clobber each other."""
    with open(lock_file(), "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_metadata() -> dict[str, Any]:
    if not metadata_file().exists():
        return {"version": 2, "hosts": {}}

    try:
        data = json.loads(metadata_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "hosts": {}}

    if not isinstance(data, dict):
        data = {}

    if not isinstance(data.get("hosts"), dict):
        data["hosts"] = {}

    data["version"] = 2
    return data


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)

        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def save_metadata(data: dict[str, Any]) -> None:
    atomic_write(
        metadata_file(),
        json.dumps(data, indent=2, sort_keys=True) + "\n",
    )


def backup_file(path: Path, prefix: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = backup_dir() / f"{prefix}.{stamp}"
    shutil.copy2(path, backup)
    backup.chmod(0o600)

    backups = sorted(
        backup_dir().glob(f"{prefix}.*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )

    for old_backup in backups[MAX_BACKUPS:]:
        with contextlib.suppress(OSError):
            old_backup.unlink()


def meaningful_entry(entry: dict[str, Any]) -> dict[str, Any]:
    ignored = {
        "count",
        "first_seen",
        "last_used",
        "original_destination",
        "alias_locked",
    }

    cleaned = {
        key: value
        for key, value in entry.items()
        if key not in ignored
    }

    remote_facts = cleaned.get("remote_facts")

    if isinstance(remote_facts, dict):
        remote_facts = dict(remote_facts)
        remote_facts.pop("collected_at", None)
        cleaned["remote_facts"] = remote_facts

    return cleaned


def migrate_entry(entry: dict[str, Any]) -> None:
    if not isinstance(entry.get("manual_tags"), list):
        entry["manual_tags"] = []

    if not isinstance(entry.get("auto_tags"), list):
        remote_facts = entry.get("remote_facts", {})
        hostname = normalize_host(entry.get("hostname"))
        auto_tags = infer_hostname_tags(hostname)
        if isinstance(remote_facts, dict):
            auto_tags.update(tags_from_remote_facts(remote_facts))
        entry["auto_tags"] = sorted(auto_tags)

    combined = set(entry.get("manual_tags", []))
    combined.update(entry.get("auto_tags", []))
    entry["tags"] = sorted(sanitize_alias(tag) for tag in combined if tag)


def merge_duplicate_hosts(metadata: dict[str, Any]) -> None:
    hosts = metadata.get("hosts", {})

    for entry in hosts.values():
        migrate_entry(entry)

    groups: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}

    for alias_name, entry in list(hosts.items()):
        short = host_short(entry.get("hostname"))
        port = str(entry.get("port") or "22")

        if short:
            groups.setdefault((short, port), []).append((alias_name, entry))

    for (short, _port), entries in groups.items():
        if len(entries) < 2:
            continue

        concrete_hosts = {
            normalize_host(entry.get("hostname"))
            for _alias, entry in entries
            if is_fqdn(normalize_host(entry.get("hostname")))
            or is_ip(normalize_host(entry.get("hostname")))
        }

        # Do not merge two distinct FQDNs/IPs that happen to share a short name.
        if len(concrete_hosts) > 1:
            continue

        canonical_alias = short if short in hosts else min(
            (alias for alias, _entry in entries),
            key=lambda value: (len(value), value),
        )

        hostname_candidates: list[str] = []

        for _alias, entry in entries:
            for candidate in (
                entry.get("hostname"),
                entry.get("original_destination"),
            ):
                normalized = normalize_host(candidate)
                if is_fqdn(normalized) or is_ip(normalized):
                    hostname_candidates.append(normalized)

        canonical_host = (
            max(
                hostname_candidates,
                key=lambda value: (is_fqdn(value), value.count("."), len(value)),
            )
            if hostname_candidates
            else short
        )

        base = dict(hosts.get(canonical_alias, entries[0][1]))
        manual_tags: set[str] = set()
        auto_tags: set[str] = set()
        identityfiles: list[str] = []
        count = 0
        first_seen: list[str] = []
        last_used: list[str] = []
        newest_facts: dict[str, Any] = {}

        for _alias, entry in entries:
            manual_tags.update(entry.get("manual_tags", []))
            auto_tags.update(entry.get("auto_tags", []))
            count += int(entry.get("count", 0))

            for identity in entry.get("identityfiles", []):
                if identity not in identityfiles:
                    identityfiles.append(identity)

            if entry.get("first_seen"):
                first_seen.append(entry["first_seen"])

            if entry.get("last_used"):
                last_used.append(entry["last_used"])

            facts = entry.get("remote_facts")
            if isinstance(facts, dict) and facts:
                newest_facts = facts

        base["hostname"] = canonical_host
        base["manual_tags"] = sorted(manual_tags)
        base["auto_tags"] = sorted(auto_tags)
        base["tags"] = sorted(manual_tags | auto_tags)
        base["identityfiles"] = identityfiles
        base["count"] = count
        base["first_seen"] = min(first_seen) if first_seen else now_iso()
        base["last_used"] = max(last_used) if last_used else now_iso()

        if newest_facts:
            base["remote_facts"] = newest_facts

        hosts[canonical_alias] = base

        for alias_name, _entry in entries:
            if alias_name != canonical_alias:
                hosts.pop(alias_name, None)

