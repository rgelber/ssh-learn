"""Tests for metadata persistence, migration, and de-duplication."""

from __future__ import annotations

from ssh_learn.paths import backup_dir, metadata_file
from ssh_learn.store import (
    atomic_write,
    backup_file,
    load_metadata,
    meaningful_entry,
    merge_duplicate_hosts,
    migrate_entry,
    save_metadata,
)


def test_save_load_roundtrip(home):
    data = {"version": 2, "hosts": {"a": {"hostname": "h", "count": 1}}}
    save_metadata(data)
    assert load_metadata()["hosts"]["a"]["hostname"] == "h"
    # File is created with owner-only permissions.
    assert (metadata_file().stat().st_mode & 0o777) == 0o600


def test_load_tolerates_garbage(home):
    metadata_file().write_text("{ not json", encoding="utf-8")
    assert load_metadata() == {"version": 2, "hosts": {}}


def test_atomic_write_is_atomic(home, tmp_path):
    target = tmp_path / ".ssh" / "thing"
    atomic_write(target, "hello")
    assert target.read_text() == "hello"
    # No leftover temp files beside it.
    leftovers = [p for p in target.parent.iterdir() if p.name.startswith(".thing")]
    assert leftovers == []


def test_migrate_entry_backfills_tags():
    entry = {"hostname": "db.prod.example.com", "remote_facts": {}}
    migrate_entry(entry)
    assert "prod" in entry["tags"]
    assert entry["manual_tags"] == []


def test_meaningful_entry_ignores_volatile_fields():
    a = {"hostname": "h", "count": 1, "last_used": "x", "alias_locked": True}
    b = {"hostname": "h", "count": 99, "last_used": "y"}
    assert meaningful_entry(a) == meaningful_entry(b)


def test_merge_duplicate_hosts_combines_short_and_fqdn():
    metadata = {
        "version": 2,
        "hosts": {
            "web1": {"hostname": "web1", "count": 1, "manual_tags": [],
                     "auto_tags": [], "tags": []},
            "web1-prod": {"hostname": "web1.prod.example.com", "count": 2,
                          "manual_tags": ["keep"], "auto_tags": [], "tags": []},
        },
    }
    merge_duplicate_hosts(metadata)
    hosts = metadata["hosts"]
    assert len(hosts) == 1
    (entry,) = hosts.values()
    assert entry["hostname"] == "web1.prod.example.com"  # concrete wins
    assert entry["count"] == 3                            # counts summed
    assert "keep" in entry["manual_tags"]                 # tags preserved


def test_merge_keeps_distinct_fqdns_apart():
    metadata = {
        "version": 2,
        "hosts": {
            "web1": {"hostname": "web1.a.com", "count": 1, "manual_tags": [],
                     "auto_tags": [], "tags": []},
            "web1-b": {"hostname": "web1.b.com", "count": 1, "manual_tags": [],
                       "auto_tags": [], "tags": []},
        },
    }
    merge_duplicate_hosts(metadata)
    assert len(metadata["hosts"]) == 2  # different machines, not merged


def test_backup_rotation(home, monkeypatch):
    import ssh_learn.store as store

    monkeypatch.setattr(store, "MAX_BACKUPS", 3)
    source = home / ".ssh" / "learned_hosts.json"
    for i in range(6):
        source.write_text(f"content {i}", encoding="utf-8")
        backup_file(source, "learned")
    kept = list(backup_dir().glob("learned.*"))
    assert len(kept) == 3
