"""Command-line entry point: argument parsing and dispatch."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .commands import (
    command_list,
    command_prune,
    command_rebuild,
    command_record,
    command_relabel,
    command_remove,
    command_rename,
    command_show,
    command_tag,
    command_tags,
    command_validate,
)
from .installer import command_doctor, command_init, command_uninstall
from .store import ensure_layout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssh-learn",
        description="Record and manage successful SSH connections.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"ssh-learn {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser(
        "init", help="install the zsh integration and wire up ssh config"
    )
    init.set_defaults(function=command_init)

    uninstall = subparsers.add_parser(
        "uninstall", help="remove the shell integration (keeps learned data)"
    )
    uninstall.add_argument(
        "--purge",
        action="store_true",
        help="also delete learned hosts, metadata, and backups",
    )
    uninstall.set_defaults(function=command_uninstall)

    doctor = subparsers.add_parser(
        "doctor", help="check that the installation is healthy"
    )
    doctor.set_defaults(function=command_doctor)

    record = subparsers.add_parser(
        "record", help="record a successful connection (used by the ssh wrapper)"
    )
    record.add_argument("destination")
    record.add_argument("--ssh-arg", action="append", default=[])
    record.add_argument("--tag", action="append", default=[])
    record.set_defaults(function=command_record)

    host_args_help = (
        "one or more aliases, unique prefixes, or glob patterns "
        "(quote globs, e.g. 'web-*'); globs match aliases, hostnames, and tags"
    )

    list_parser = subparsers.add_parser("list", help="list learned hosts")
    list_parser.add_argument(
        "pattern",
        nargs="*",
        help="only hosts matching these glob patterns (quote them)",
    )
    list_parser.add_argument("--tag", help="only hosts carrying this tag")
    list_parser.add_argument(
        "--sort",
        choices=("name", "used", "count"),
        default="name",
    )
    list_parser.add_argument(
        "--names", action="store_true", help="print alias names only"
    )
    list_parser.set_defaults(function=command_list)

    show = subparsers.add_parser("show", help="show hosts as JSON")
    show.add_argument("host", nargs="+", help=host_args_help)
    show.set_defaults(function=command_show)

    remove = subparsers.add_parser("remove", help="forget hosts")
    remove.add_argument("host", nargs="+", help=host_args_help)
    remove.add_argument(
        "--dry-run",
        action="store_true",
        help="only show what would be removed",
    )
    remove.set_defaults(function=command_remove)

    rename = subparsers.add_parser("rename", help="rename a host alias")
    rename.add_argument("host")
    rename.add_argument("new_alias")
    rename.set_defaults(function=command_rename)

    relabel = subparsers.add_parser(
        "relabel",
        help="recompute aliases from the name you connect with",
    )
    relabel.add_argument(
        "host",
        nargs="*",
        help=f"{host_args_help}; omit to relabel every host",
    )
    relabel.add_argument(
        "--dry-run",
        action="store_true",
        help="only show what would be renamed",
    )
    relabel.add_argument(
        "--force",
        action="store_true",
        help="also relabel hosts you renamed by hand",
    )
    relabel.set_defaults(function=command_relabel)

    tag = subparsers.add_parser("tag", help="add or remove manual tags")
    tag.add_argument("host", nargs="+", help=host_args_help)
    tag.add_argument("--add", action="append", default=[])
    tag.add_argument("--remove", action="append", default=[])
    tag.set_defaults(function=command_tag)

    tags = subparsers.add_parser("tags", help="list all tags in use")
    tags.add_argument(
        "--names", action="store_true", help="print tag names only"
    )
    tags.set_defaults(function=command_tags)

    prune = subparsers.add_parser(
        "prune", help="forget hosts not used recently"
    )
    prune.add_argument(
        "--days",
        type=int,
        default=90,
        help="remove hosts unused for this many days (default: 90)",
    )
    prune.add_argument(
        "--dry-run",
        action="store_true",
        help="only show what would be removed",
    )
    prune.set_defaults(function=command_prune)

    rebuild = subparsers.add_parser(
        "rebuild", help="regenerate the learned SSH config from metadata"
    )
    rebuild.set_defaults(function=command_rebuild)

    validate = subparsers.add_parser(
        "validate", help="check the generated SSH config parses"
    )
    validate.set_defaults(function=command_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_layout()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    try:
        return int(args.function(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 - surfaced to the user
        print(f"ssh-learn: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
