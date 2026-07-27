"""Integration tests for the record/relabel lifecycle via the command layer."""

from __future__ import annotations

import argparse

from ssh_learn import commands, recorder
from ssh_learn.store import load_metadata, save_metadata


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def test_record_uses_typed_config_name(home, fake_ssh_config):
    # The reported bug: `ssh hostname` where HostName is an IP.
    fake_ssh_config("hostname", hostname="192.168.1.100", user="someuser")

    status, alias = recorder.record_connection("hostname", [], [])

    assert (status, alias) == ("saved", "hostname")
    entry = load_metadata()["hosts"]["hostname"]
    assert entry["hostname"] == "192.168.1.100"
    assert entry["user"] == "someuser"


def test_record_by_ip_uses_dashed_alias(home, fake_ssh_config):
    fake_ssh_config("198.168.1.101", hostname="198.168.1.101", user="admin")
    _, alias = recorder.record_connection("198.168.1.101", [], [])
    assert alias == "198-168-1-101"

def test_reconnect_is_idempotent(home, fake_ssh_config):
    fake_ssh_config("hostname", hostname="192.168.1.100", user="someuser")
    recorder.record_connection("hostname", [], [])
    status, alias = recorder.record_connection("hostname", [], [])
    assert alias == "hostname"
    assert status == "unchanged"
    assert load_metadata()["hosts"]["hostname"]["count"] == 2


def test_reconnect_by_ip_maps_back_to_named_alias(home, fake_ssh_config):
    fake_ssh_config("hostname", hostname="192.168.1.100", user="someuser")
    recorder.record_connection("hostname", [], [])
    # Now connect straight to the IP -> should reuse the existing alias.
    fake_ssh_config("someuser@192.168.1.100", hostname="192.168.1.100",
                    user="someuser")
    _, alias = recorder.record_connection("someuser@192.168.1.100", [], [])
    assert alias == "hostname"
    assert len(load_metadata()["hosts"]) == 1


def test_relabel_repairs_ip_octet_aliases(home):
    # Forge the state the old buggy version produced.
    save_metadata({"version": 2, "hosts": {
        "10": {"hostname": "192.168.1.100", "user": "someuser", "port": "22",
               "original_destination": "hostname", "count": 5,
               "manual_tags": [], "auto_tags": [], "tags": [],
               "identityfiles": [], "remote_facts": {}},
    }})
    rc = commands.command_relabel(_ns(host=[], dry_run=False, force=False))
    assert rc == 0
    hosts = load_metadata()["hosts"]
    assert "hostname" in hosts
    assert "10" not in hosts
    assert hosts["hostname"]["count"] == 5  # history preserved


def test_relabel_skips_manually_renamed(home):
    save_metadata({"version": 2, "hosts": {
        "mybox": {"hostname": "10.0.0.5", "original_destination": "10.0.0.5",
                  "port": "22", "count": 1, "manual_tags": [], "auto_tags": [],
                  "tags": [], "identityfiles": [], "remote_facts": {},
                  "alias_locked": True},
    }})
    commands.command_relabel(_ns(host=[], dry_run=False, force=False))
    assert "mybox" in load_metadata()["hosts"]  # locked name untouched

    commands.command_relabel(_ns(host=[], dry_run=False, force=True))
    assert "10-0-0-5" in load_metadata()["hosts"]  # --force overrides


def test_rename_locks_alias(home):
    save_metadata({"version": 2, "hosts": {
        "old": {"hostname": "h", "port": "22", "count": 1, "manual_tags": [],
                "auto_tags": [], "tags": [], "identityfiles": [],
                "remote_facts": {}},
    }})
    commands.command_rename(_ns(host="old", new_alias="nice"))
    assert load_metadata()["hosts"]["nice"]["alias_locked"] is True


def test_remove_and_tag_accept_globs(home, fake_ssh_config):
    for name in ("web-1", "web-2", "db-1"):
        fake_ssh_config(name, hostname=f"{name}.example.com")
        recorder.record_connection(name, [], [])

    commands.command_tag(_ns(host=["web-*"], add=["frontend"], remove=[]))
    hosts = load_metadata()["hosts"]
    assert "frontend" in hosts["web-1"]["tags"]
    assert "frontend" in hosts["web-2"]["tags"]
    assert "frontend" not in hosts["db-1"]["tags"]

    commands.command_remove(_ns(host=["web-*"], dry_run=False))
    remaining = set(load_metadata()["hosts"])
    assert remaining == {"db-1"}
