"""Resolve the on-disk locations ssh-learn reads and writes.

Paths are computed on each call rather than frozen at import, so tests (and
users who want an alternate location) can redirect the whole tool by setting
SSH_LEARN_HOME to stand in for the home directory.
"""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    override = os.environ.get("SSH_LEARN_HOME")

    if override:
        return Path(override).expanduser()

    return Path.home()


def ssh_dir() -> Path:
    return home() / ".ssh"


def conf_dir() -> Path:
    return ssh_dir() / "conf.d"


def control_dir() -> Path:
    return ssh_dir() / "control"


def backup_dir() -> Path:
    return ssh_dir() / "backups"


def learned_file() -> Path:
    return conf_dir() / "90-learned.conf"


def defaults_file() -> Path:
    return conf_dir() / "00-defaults.conf"


def metadata_file() -> Path:
    return ssh_dir() / "learned_hosts.json"


def lock_file() -> Path:
    return ssh_dir() / ".ssh-learn.lock"


def tools_file() -> Path:
    return ssh_dir() / "ssh-tools.zsh"


def main_config() -> Path:
    return ssh_dir() / "config"


def zshrc() -> Path:
    return home() / ".zshrc"
