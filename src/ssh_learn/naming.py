"""Host-name normalization, alias derivation, and lookup."""

from __future__ import annotations

import fnmatch
import ipaddress
import re
from typing import Any

GLOB_CHARS = frozenset("*?[")


def sanitize_alias(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-._") or "ssh-host"


def normalize_host(value: str | None) -> str:
    if not value:
        return ""

    value = str(value).strip()

    if "@" in value:
        value = value.rsplit("@", 1)[1]

    if value.startswith("[") and "]" in value:
        value = value[1:value.index("]")]

    return value.rstrip(".").lower()


def is_ip(value: str | None) -> bool:
    if not value:
        return False

    try:
        ipaddress.ip_address(str(value).rstrip("."))
        return True
    except ValueError:
        return False


def is_fqdn(value: str | None) -> bool:
    if not value:
        return False

    value = str(value).rstrip(".")
    return "." in value and not is_ip(value)


def is_short_hostname(value: str | None) -> bool:
    value = normalize_host(value)
    return bool(value) and not is_ip(value) and "." not in value


def host_short(value: str | None) -> str:
    value = normalize_host(value)
    return value.split(".", 1)[0] if value else ""


def hostnames_equivalent(left: str | None, right: str | None) -> bool:
    left = normalize_host(left)
    right = normalize_host(right)

    if not left or not right:
        return False

    if left == right:
        return True

    if is_ip(left) or is_ip(right):
        return False

    # A short name and its FQDN are equivalent. Two different FQDNs are not.
    if is_short_hostname(left) or is_short_hostname(right):
        return host_short(left) == host_short(right)

    return False


def alias_base(destination: str, hostname: str) -> str:
    """Choose the string an alias is derived from.

    The name the user typed is the best alias. If they run `ssh hostname`,
    they think of the host as "hostname" even though it resolves to an IP,
    so the ssh_config Host alias should become the learned alias too. Only
    fall back to the resolved hostname, and use a bare IP as a last resort.
    """
    destination_host = normalize_host(destination)
    hostname = normalize_host(hostname)

    # A short name the user typed (typically an ssh_config Host alias).
    if is_short_hostname(destination_host):
        return destination_host

    # A FQDN from either source: reduce to its first label (web1.prod -> web1).
    for candidate in (destination_host, hostname):
        if is_fqdn(candidate):
            return host_short(candidate)

    # Only IP addresses are available. Keep the whole address but with dashes,
    # so it reads as an address and host_short() cannot mistake an octet for a
    # domain label (192.168.1.100 -> 192.168.1.100, not "10").
    ip_source = destination_host or hostname
    return ip_source.replace(".", "-")


def _disambiguate_alias(base: str, hostname: str, taken: set[str]) -> str:
    if base not in taken:
        return base

    for label in normalize_host(hostname).split(".")[1:]:
        candidate = sanitize_alias(f"{base}-{label}")

        if candidate not in taken:
            return candidate

    counter = 2

    while f"{base}-{counter}" in taken:
        counter += 1

    return f"{base}-{counter}"


def generate_alias(destination: str, hostname: str, hosts: dict[str, Any]) -> str:
    base = sanitize_alias(alias_base(destination, hostname))

    if base not in hosts:
        return base

    if hostnames_equivalent(hosts[base].get("hostname"), hostname):
        return base

    return _disambiguate_alias(base, hostname, set(hosts))


def find_existing_alias(
    hosts: dict[str, Any],
    destination: str,
    hostname: str,
    port: str,
) -> str | None:
    destination_host = normalize_host(destination)

    if is_short_hostname(destination_host):
        alias_candidate = sanitize_alias(destination_host)

        if alias_candidate in hosts:
            existing_port = str(hosts[alias_candidate].get("port") or "22")
            if existing_port == port:
                return alias_candidate

    for alias_name, entry in hosts.items():
        existing_port = str(entry.get("port") or "22")

        if existing_port != port:
            continue

        if hostnames_equivalent(entry.get("hostname"), hostname):
            return alias_name

    return None


def canonical_hostname(
    discovered_hostname: str,
    old_hostname: str | None,
    destination: str,
) -> str:
    destination_host = normalize_host(destination)
    discovered_hostname = normalize_host(discovered_hostname)
    old_hostname = normalize_host(old_hostname)

    if is_ip(destination_host) or is_fqdn(destination_host):
        return destination_host

    if is_ip(old_hostname) or is_fqdn(old_hostname):
        return old_hostname

    if is_ip(discovered_hostname) or is_fqdn(discovered_hostname):
        return discovered_hostname

    return discovered_hostname or old_hostname or destination_host


def resolve_alias(hosts: dict[str, Any], value: str) -> str:
    if value in hosts:
        return value

    hostname_matches = [
        alias_name
        for alias_name, entry in hosts.items()
        if hostnames_equivalent(entry.get("hostname"), value)
    ]

    if len(hostname_matches) == 1:
        return hostname_matches[0]

    prefix_matches = [
        alias_name for alias_name in hosts if alias_name.startswith(value)
    ]

    if len(prefix_matches) == 1:
        return prefix_matches[0]

    if len(hostname_matches) > 1 or len(prefix_matches) > 1:
        candidates = sorted(set(hostname_matches + prefix_matches))
        raise KeyError(f"{value} is ambiguous: {', '.join(candidates)}")

    raise KeyError(f"{value} not found")


def is_glob(value: str) -> bool:
    return bool(GLOB_CHARS.intersection(value))


def matches_pattern(alias: str, entry: dict[str, Any], pattern: str) -> bool:
    """A glob matches on the alias, the hostname, or any tag."""
    if fnmatch.fnmatch(alias, pattern):
        return True

    if fnmatch.fnmatch(normalize_host(entry.get("hostname")), pattern):
        return True

    return any(fnmatch.fnmatch(tag, pattern) for tag in entry.get("tags", []))


def expand_host_args(
    hosts: dict[str, Any],
    values: list[str],
) -> tuple[list[str], list[str]]:
    """Resolve a mix of alias names, prefixes, and glob patterns.

    Returns (resolved alias names in stable order, error messages).
    """
    resolved: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()

    def add(alias: str) -> None:
        if alias not in seen:
            seen.add(alias)
            resolved.append(alias)

    for value in values:
        if is_glob(value):
            matched = sorted(
                alias
                for alias, entry in hosts.items()
                if matches_pattern(alias, entry, value)
            )

            if not matched:
                errors.append(f"no hosts match pattern: {value}")

            for alias in matched:
                add(alias)
        else:
            try:
                add(resolve_alias(hosts, value))
            except KeyError as error:
                # resolve_alias messages are already complete
                # ("X not found" / "X is ambiguous: ...").
                errors.append(str(error.args[0]))

    return resolved, errors

