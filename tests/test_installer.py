"""Tests for the shell-integration installer and the CLI entry point."""

from __future__ import annotations

import argparse

from ssh_learn import installer
from ssh_learn.cli import main
from ssh_learn.paths import (
    defaults_file,
    learned_file,
    main_config,
    metadata_file,
    tools_file,
    zshrc,
)


def _init(home):
    (home / ".zshrc").touch()
    installer.command_init(argparse.Namespace())


def test_init_writes_files_and_wires_config(home):
    main_config().write_text("Host existing\n    HostName x\n", encoding="utf-8")
    _init(home)

    assert tools_file().exists()
    assert defaults_file().exists()
    assert installer.INCLUDE_LINE in main_config().read_text()
    assert installer.SOURCE_LINE in zshrc().read_text()
    # Managed include goes at the end, after the user's content.
    assert main_config().read_text().index("Host existing") < \
        main_config().read_text().index(installer.INCLUDE_LINE)


def test_init_is_idempotent(home):
    _init(home)
    _init(home)
    assert main_config().read_text().count(installer.INCLUDE_LINE) == 1
    assert zshrc().read_text().count(installer.SOURCE_LINE) == 1


def test_uninstall_preserves_user_host_star(home):
    main_config().write_text(
        "Host jump\n    HostName j\n\nHost *\n    ForwardAgent no\n",
        encoding="utf-8",
    )
    _init(home)
    installer.command_uninstall(argparse.Namespace(purge=False))

    text = main_config().read_text()
    assert "ForwardAgent no" in text          # user's own Host * survives
    assert installer.INCLUDE_LINE not in text  # managed lines gone
    assert installer.MANAGED_COMMENT not in text


def test_uninstall_keeps_data_purge_removes_it(home):
    _init(home)
    metadata_file().write_text('{"version":2,"hosts":{}}', encoding="utf-8")

    installer.command_uninstall(argparse.Namespace(purge=False))
    assert metadata_file().exists()  # kept

    _init(home)
    installer.command_uninstall(argparse.Namespace(purge=True))
    assert not metadata_file().exists()  # purged
    assert not learned_file().exists()


def test_cli_version(home, capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["--version"])
    assert "ssh-learn" in capsys.readouterr().out


def test_cli_list_empty(home, capsys):
    assert main(["list"]) == 0
    assert "No learned hosts" in capsys.readouterr().out


def test_cli_doctor_after_init(home):
    _init(home)
    assert main(["doctor"]) == 0
