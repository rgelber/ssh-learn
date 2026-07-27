"""Pure-function tests for name handling and alias derivation."""

from __future__ import annotations

import pytest

from ssh_learn.naming import (
    alias_base,
    canonical_hostname,
    expand_host_args,
    generate_alias,
    host_short,
    hostnames_equivalent,
    is_fqdn,
    is_ip,
    is_short_hostname,
    normalize_host,
    resolve_alias,
    sanitize_alias,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Web-01.PROD ", "web-01.prod"),
        ("under_score", "under_score"),
        ("weird!!name", "weird-name"),
        ("---", "ssh-host"),
        ("", "ssh-host"),
    ],
)
def test_sanitize_alias(value, expected):
    assert sanitize_alias(value) == expected


def test_normalize_strips_user_and_brackets():
    assert normalize_host("deploy@[2001:db8::1]") == "2001:db8::1"
    assert normalize_host("Host.Example.COM.") == "host.example.com"


def test_ip_fqdn_short_classification():
    assert is_ip("10.0.0.1")
    assert not is_ip("host")
    assert is_fqdn("a.b.com")
    assert not is_fqdn("10.0.0.1")
    assert is_short_hostname("bastion")
    assert not is_short_hostname("a.b.com")


def test_hostnames_equivalent_short_vs_fqdn():
    assert hostnames_equivalent("web1", "web1.prod.example.com")
    assert not hostnames_equivalent("web1.a.com", "web1.b.com")
    assert not hostnames_equivalent("10.0.0.1", "10.0.0.2")


@pytest.mark.parametrize(
    "destination,hostname,expected",
    [
        ("hostname", "192.168.1.100", "hostname"),      # the reported bug
        ("web1.prod.example.com", "web1.prod.example.com", "web1"),
        ("deploy@db.internal", "10.0.0.4", "db"),
        ("198.168.1.101", "198.168.1.101", "198-168-1-101"),  # not just "10"
        ("bastion", "192.168.1.1", "bastion"),
    ],
)
def test_alias_base(destination, hostname, expected):
    assert sanitize_alias(alias_base(destination, hostname)) == expected


def test_generate_alias_disambiguates_distinct_hosts():
    hosts = {"web1": {"hostname": "web1.a.com"}}
    # Same short name, different FQDN -> must not collide onto web1.
    alias = generate_alias("web1.b.com", "web1.b.com", hosts)
    assert alias != "web1"
    assert alias.startswith("web1-")


def test_generate_alias_reuses_equivalent_host():
    hosts = {"web1": {"hostname": "web1.prod.example.com"}}
    assert generate_alias("web1", "web1.prod.example.com", hosts) == "web1"


def test_canonical_hostname_prefers_concrete_target():
    # Typed a short alias, resolved to an IP -> store the IP as HostName.
    assert canonical_hostname("10.0.0.5", None, "hostname") == "10.0.0.5"


def test_resolve_alias_prefix_and_ambiguity():
    hosts = {"webby": {"hostname": "w"}, "webster": {"hostname": "x"}}
    assert resolve_alias(hosts, "webby") == "webby"
    with pytest.raises(KeyError):
        resolve_alias(hosts, "web")  # ambiguous prefix
    with pytest.raises(KeyError):
        resolve_alias(hosts, "nope")


def test_expand_host_args_globs_across_fields():
    hosts = {
        "web1": {"hostname": "web1.prod.example.com", "tags": ["prod"]},
        "db1": {"hostname": "10.0.0.9", "tags": ["prod", "db"]},
        "cache": {"hostname": "c.dev.example.com", "tags": ["dev"]},
    }
    # A glob matches across alias, hostname, and tag.
    resolved, errors = expand_host_args(hosts, ["*prod*"])
    assert set(resolved) == {"web1", "db1"}  # web1 hostname, db1 tag
    assert errors == []

    # A plain alias glob only matches alias names.
    resolved, _ = expand_host_args(hosts, ["web*"])
    assert set(resolved) == {"web1"}

    # A non-glob word is an alias/prefix lookup, not a tag match.
    resolved, errors = expand_host_args(hosts, ["prod"])
    assert resolved == []
    assert errors  # "prod" is a tag, not an alias

    resolved, errors = expand_host_args(hosts, ["nope*"])
    assert resolved == []
    assert errors and "nope*" in errors[0]


def test_host_short():
    assert host_short("a.b.c") == "a"
    assert host_short("bastion") == "bastion"
