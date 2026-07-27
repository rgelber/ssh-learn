"""Install and remove the shell integration.

`ssh-learn init` writes the zsh integration and defaults, then wires them into
~/.ssh/config and ~/.zshrc. `ssh-learn uninstall` reverses exactly those edits.
Neither touches the ssh-learn program itself -- that is managed by pip/pipx.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import shutil
import sys
from importlib import resources
from pathlib import Path

from .paths import (
    backup_dir,
    conf_dir,
    control_dir,
    defaults_file,
    learned_file,
    main_config,
    metadata_file,
    tools_file,
    zshrc,
)
from .sshcfg import validate_generated_config, write_learned_config
from .store import (
    ensure_layout,
    load_metadata,
    merge_duplicate_hosts,
    metadata_lock,
    save_metadata,
)

MANAGED_COMMENT = "# Managed includes for ssh-learn"
INCLUDE_LINE = "Include ~/.ssh/conf.d/*.conf"
ZSHRC_COMMENT = "# SSH connection learning and host picker"
SOURCE_LINE = "[[ -f ~/.ssh/ssh-tools.zsh ]] && source ~/.ssh/ssh-tools.zsh"


def _read_data(name: str) -> str:
    return (resources.files("ssh_learn.data") / name).read_text(encoding="utf-8")


def _backup(path: Path, label: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return

    backup_dir().mkdir(parents=True, exist_ok=True)
    backup_dir().chmod(0o700)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir() / f"{label}.{stamp}"
    shutil.copy2(path, target)
    target.chmod(0o600)


def _ensure_line_block(path: Path, lines: list[str], sentinel: str) -> bool:
    """Append a block of lines once, keyed by a sentinel already being present.

    Returns True when the file was modified.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    if any(line.strip() == sentinel for line in existing.splitlines()):
        return False

    prefix = "" if existing.endswith("\n") or not existing else "\n"
    path.write_text(existing + prefix + "\n" + "\n".join(lines) + "\n",
                    encoding="utf-8")
    return True


def _remove_managed_lines(path: Path) -> None:
    """Remove only the lines ssh-learn added, leaving user content intact.

    The three-line ``Host *`` / Include block in ~/.ssh/config is removed as a
    unit, so a user's own ``Host *`` section is never disturbed.
    """
    if not path.exists():
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()

        if (
            stripped == MANAGED_COMMENT
            and index + 2 < len(lines)
            and lines[index + 1].strip() == "Host *"
            and lines[index + 2].strip() == INCLUDE_LINE
        ):
            index += 3
            continue

        if stripped in (MANAGED_COMMENT, INCLUDE_LINE, ZSHRC_COMMENT, SOURCE_LINE):
            index += 1
            continue

        kept.append(lines[index])
        index += 1

    while kept and not kept[-1].strip():
        kept.pop()

    path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")


def command_init(_args: object) -> int:
    ensure_layout()

    config = main_config()
    if not config.exists():
        config.touch()
    config.chmod(0o600)

    if not zshrc().exists():
        zshrc().touch()

    _backup(config, "config")
    _backup(zshrc(), "zshrc")

    defaults_file().write_text(_read_data("00-defaults.conf"), encoding="utf-8")
    defaults_file().chmod(0o600)

    tools_file().write_text(_read_data("ssh-tools.zsh"), encoding="utf-8")
    tools_file().chmod(0o600)

    # Append the include at the END of ~/.ssh/config so options the user set
    # earlier always win (ssh takes the first value it finds). The bare
    # "Host *" resets any trailing Host/Match scope so the Include applies.
    _ensure_line_block(
        config,
        [MANAGED_COMMENT, "Host *", INCLUDE_LINE],
        sentinel=INCLUDE_LINE,
    )
    _ensure_line_block(
        zshrc(),
        [ZSHRC_COMMENT, SOURCE_LINE],
        sentinel=SOURCE_LINE,
    )

    with metadata_lock():
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        save_metadata(metadata)
        write_learned_config(metadata)

    print("ssh-learn shell integration installed.")
    print()
    print("Reload your shell:")
    print("  source ~/.zshrc")
    print()
    print("Optional interactive picker:")
    print("  brew install fzf   # or your package manager")
    print()
    print("Then just use ssh normally -- successful hosts are learned.")
    print("Run 'ssh-learn list' to see them, 'sshm' to fuzzy-pick and connect.")
    return 0


def command_uninstall(args: object) -> int:
    purge = bool(getattr(args, "purge", False))

    _backup(main_config(), "config.pre-uninstall")
    _backup(zshrc(), "zshrc.pre-uninstall")

    _remove_managed_lines(main_config())
    _remove_managed_lines(zshrc())

    for path in (tools_file(), defaults_file()):
        path.unlink(missing_ok=True)

    if control_dir().exists():
        shutil.rmtree(control_dir(), ignore_errors=True)

    if purge:
        learned_file().unlink(missing_ok=True)
        metadata_file().unlink(missing_ok=True)
        if backup_dir().exists():
            shutil.rmtree(backup_dir(), ignore_errors=True)
        with contextlib.suppress(OSError):
            conf_dir().rmdir()
        print("Removed the shell integration, learned hosts, and backups.")
    else:
        print("Removed the shell integration. Learned data was kept:")
        print(f"  {learned_file()}")
        print(f"  {metadata_file()}")

    print()
    print("Open a new shell (or run 'exec zsh') to drop the ssh wrapper.")
    print("The ssh-learn program is still installed; remove it with your")
    print("package manager (e.g. 'pipx uninstall ssh-learn').")
    return 0


def command_doctor(_args: object) -> int:
    """Report on the health of the current installation."""
    ok = True

    def check(
        label: str, condition: bool, detail: str = "", optional: bool = False
    ) -> None:
        nonlocal ok
        if condition:
            mark = "ok  "
        elif optional:
            mark = "note"
        else:
            mark = "FAIL"
        if not optional:
            ok = ok and condition
        suffix = f"  ({detail})" if detail else ""
        print(f"[{mark}] {label}{suffix}")

    check("ssh-learn on PATH", shutil.which("ssh-learn") is not None,
          shutil.which("ssh-learn") or "not found")
    check("ssh available", shutil.which("ssh") is not None)
    check("fzf available (for sshm)", shutil.which("fzf") is not None,
          optional=True)
    check("defaults config", defaults_file().exists(), str(defaults_file()))
    check("zsh integration", tools_file().exists(), str(tools_file()))

    config_text = (
        main_config().read_text(encoding="utf-8")
        if main_config().exists()
        else ""
    )
    check(
        "include wired into ~/.ssh/config",
        INCLUDE_LINE in config_text,
    )

    zshrc_text = zshrc().read_text(encoding="utf-8") if zshrc().exists() else ""
    check("source line in ~/.zshrc", SOURCE_LINE in zshrc_text)

    try:
        metadata = load_metadata()
        merge_duplicate_hosts(metadata)
        from .sshcfg import render_config

        validate_generated_config(
            render_config(metadata), sorted(metadata.get("hosts", {}))
        )
        check("learned config parses", True,
              f"{len(metadata.get('hosts', {}))} host(s)")
    except Exception as error:  # noqa: BLE001 - reported to the user
        check("learned config parses", False, str(error))

    if not ok:
        print("\nSome checks failed. Run 'ssh-learn init' to (re)install.",
              file=sys.stderr)
        return 1

    print("\nEverything looks good.")
    return 0
