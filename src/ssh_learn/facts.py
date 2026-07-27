"""Optional remote-fact collection and tag inference."""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from typing import Any

from .naming import sanitize_alias
from .timeutil import age_of, now_iso

DEFAULT_FACTS_TTL_DAYS = 7.0


def facts_ttl_days() -> float:
    try:
        return float(
            os.environ.get("SSH_LEARN_FACTS_TTL_DAYS", DEFAULT_FACTS_TTL_DAYS)
        )
    except ValueError:
        return DEFAULT_FACTS_TTL_DAYS


def filter_fact_ssh_args(ssh_args: list[str]) -> list[str]:
    options_with_values = {
        "-B", "-b", "-c", "-E", "-F", "-I", "-i", "-J",
        "-l", "-m", "-o", "-P", "-p", "-S",
    }
    discard_with_values = {"-D", "-L", "-R", "-W", "-w"}
    discard_flags = {"-G", "-N", "-n", "-f", "-t", "-tt", "-T"}

    filtered: list[str] = []
    index = 0

    while index < len(ssh_args):
        argument = ssh_args[index]

        if argument in discard_flags:
            index += 1
            continue

        if argument in discard_with_values:
            index += 2
            continue

        if argument in options_with_values:
            if index + 1 < len(ssh_args):
                filtered.extend((argument, ssh_args[index + 1]))
            index += 2
            continue

        if re.match(r"^-(?:p|l|i|J|F|S|o).+", argument):
            filtered.append(argument)

        index += 1

    return filtered


def facts_are_fresh(remote_facts: Any) -> bool:
    if not isinstance(remote_facts, dict) or not remote_facts:
        return False

    age = age_of(remote_facts.get("collected_at"))
    return age is not None and age <= dt.timedelta(days=facts_ttl_days())


def collect_remote_facts(
    destination: str,
    ssh_args: list[str],
) -> dict[str, Any]:
    remote_script = r'''
set -u

environment_value=""

if command -v /opt/puppetlabs/bin/facter >/dev/null 2>&1; then
    environment_value="$(
        /opt/puppetlabs/bin/facter serverfacts.environment 2>/dev/null ||
        true
    )"

    if [ -z "$environment_value" ]; then
        environment_value="$(
            /opt/puppetlabs/bin/facter environment 2>/dev/null ||
            true
        )"
    fi
elif command -v facter >/dev/null 2>&1; then
    environment_value="$(facter serverfacts.environment 2>/dev/null || true)"

    if [ -z "$environment_value" ]; then
        environment_value="$(facter environment 2>/dev/null || true)"
    fi
fi

if [ -z "$environment_value" ] &&
   command -v /opt/puppetlabs/bin/puppet >/dev/null 2>&1; then
    environment_value="$(
        /opt/puppetlabs/bin/puppet config print environment 2>/dev/null ||
        true
    )"
elif [ -z "$environment_value" ] &&
     command -v puppet >/dev/null 2>&1; then
    environment_value="$(puppet config print environment 2>/dev/null || true)"
fi

environment_value="$(
    printf '%s' "$environment_value" |
    tr '\r\n\t' '   ' |
    sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'
)"

if [ -n "$environment_value" ]; then
    printf '__ENV__\t%s\n' "$environment_value"
fi

facts_dir="/etc/puppetlabs/facts"

if [ -d "$facts_dir" ]; then
    find "$facts_dir" -maxdepth 1 -type f -print0 2>/dev/null |
    sort -z |
    while IFS= read -r -d '' fact_file; do
        fact_name="${fact_file##*/}"
        fact_value="$(
            cat "$fact_file" 2>/dev/null |
            tr '\r\n\t' '   ' |
            sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'
        )"

        if [ -n "$fact_value" ]; then
            printf '__FILE__\t%s\t%s\n' "$fact_name" "$fact_value"
        fi
    done
fi
'''

    command = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        *filter_fact_ssh_args(ssh_args),
        destination,
        "bash", "-s",
    ]

    try:
        result = subprocess.run(
            command,
            input=remote_script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    if result.returncode != 0:
        return {}

    facts: dict[str, Any] = {
        "environment": None,
        "files": {},
        "collected_at": now_iso(),
    }

    for raw_line in result.stdout.splitlines():
        parts = raw_line.split("\t")

        if len(parts) >= 2 and parts[0] == "__ENV__":
            facts["environment"] = parts[1].strip()
        elif len(parts) >= 3 and parts[0] == "__FILE__":
            name = parts[1].strip()
            value = "\t".join(parts[2:]).strip()

            if name and value:
                facts["files"][name] = value

    if not facts["environment"] and not facts["files"]:
        return {}

    return facts


def infer_hostname_tags(hostname: str) -> set[str]:
    parts = set(re.split(r"[.\-_]+", hostname.lower()))
    known = {
        "prod", "production", "dr", "npe", "dev", "development",
        "qa", "integ", "integration", "stage", "staging",
        "baja", "moab", "postgres", "postgresql", "pgds",
        "airflow", "jenkins", "gpu", "neo4j", "redis", "valkey",
        "web", "db",
    }

    tags = parts.intersection(known)

    replacements = {
        "production": "prod",
        "development": "dev",
        "integration": "integ",
        "postgresql": "postgres",
    }

    for old, new in replacements.items():
        if old in tags:
            tags.remove(old)
            tags.add(new)

    return {sanitize_alias(tag) for tag in tags if tag}


def tags_from_remote_facts(remote_facts: dict[str, Any]) -> set[str]:
    values: list[str] = []

    environment = remote_facts.get("environment")
    if environment:
        values.append(str(environment))

    files = remote_facts.get("files", {})
    if isinstance(files, dict):
        values.extend(str(value) for value in files.values())

    tags: set[str] = set()

    for value in values:
        for item in re.split(r"[\s,]+", value.strip()):
            if item:
                tag = sanitize_alias(item)
                if tag:
                    tags.add(tag)

    return tags

