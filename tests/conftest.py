"""Shared fixtures. Every test runs against an isolated temporary home."""

from __future__ import annotations

import pytest

from ssh_learn.store import ensure_layout


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point the whole tool at a throwaway home and skip remote facts."""
    monkeypatch.setenv("SSH_LEARN_HOME", str(tmp_path))
    monkeypatch.setenv("SSH_LEARN_NO_FACTS", "1")
    (tmp_path / ".ssh").mkdir(parents=True, exist_ok=True)
    ensure_layout()
    return tmp_path


@pytest.fixture
def fake_ssh_config(monkeypatch):
    """Stub `ssh -G` so record_connection is deterministic and offline.

    Returns a setter: call it with the effective config a destination should
    resolve to.
    """
    from ssh_learn import recorder

    resolved: dict[str, dict] = {}

    def fake(destination, ssh_args):
        return resolved.get(destination, {"hostname": destination, "port": "22"})

    monkeypatch.setattr(recorder, "get_effective_config", fake)

    def register(destination, **config):
        config.setdefault("port", "22")
        resolved[destination] = config

    return register
