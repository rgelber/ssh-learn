"""Timestamp helpers shared across the package."""

from __future__ import annotations

import datetime as dt


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None

    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def age_of(value: str | None) -> dt.timedelta | None:
    then = parse_iso(value)

    if then is None:
        return None

    now = dt.datetime.now(then.tzinfo) if then.tzinfo else dt.datetime.now()
    return now - then


def humanize_age(value: str | None) -> str:
    age = age_of(value)

    if age is None:
        return "never"

    seconds = max(0, int(age.total_seconds()))
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400

    if seconds < 60:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if hours < 24:
        return f"{hours}h ago"
    if days < 45:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"

    return f"{days // 365}y ago"

