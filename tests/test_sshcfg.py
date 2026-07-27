"""Tests for ssh -G parsing, config rendering, and validation."""

from __future__ import annotations

import pytest

from ssh_learn.sshcfg import (
    parse_ssh_g,
    render_config,
    validate_generated_config,
)


def test_parse_ssh_g_keeps_safe_options_only():
    output = "\n".join([
        "hostname 10.0.0.1",
        "user deploy",
        "port 2222",
        "proxyjump bastion",
        "identityfile ~/.ssh/id_ed25519",
        "identityfile none",
        "localforward 8080 localhost:80",   # temporary -> dropped
        "proxycommand nc %h %p",            # unsafe -> dropped
    ])
    parsed = parse_ssh_g(output)
    assert parsed["hostname"] == "10.0.0.1"
    assert parsed["user"] == "deploy"
    assert parsed["port"] == "2222"
    assert parsed["proxyjump"] == "bastion"
    assert parsed["identityfile"] == ["~/.ssh/id_ed25519"]  # 'none' skipped
    assert "localforward" not in parsed
    assert "proxycommand" not in parsed


def test_render_config_includes_non_default_fields():
    metadata = {"hosts": {
        "box": {
            "hostname": "10.0.0.5", "user": "me", "port": "2200",
            "proxyjump": "jump", "identityfiles": ["~/.ssh/k"],
            "tags": ["prod"], "last_used": "2026-01-01", "count": 4,
        }
    }}
    text = render_config(metadata)
    assert "Host box" in text
    assert "HostName 10.0.0.5" in text
    assert "Port 2200" in text
    assert "ProxyJump jump" in text
    assert "IdentityFile ~/.ssh/k" in text


def test_render_config_omits_default_port():
    metadata = {"hosts": {
        "box": {"hostname": "h", "port": "22", "tags": [], "count": 1}
    }}
    assert "Port " not in render_config(metadata)


def test_validate_accepts_good_config(home):
    metadata = {"hosts": {
        "box": {"hostname": "10.0.0.1", "tags": [], "count": 1}
    }}
    validate_generated_config(render_config(metadata), ["box"])  # no raise


def test_validate_rejects_broken_config(home):
    broken = "Host box\n    Port notanumber\n"
    with pytest.raises(RuntimeError):
        validate_generated_config(broken, ["box"])
