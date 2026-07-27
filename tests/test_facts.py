"""Tests for remote-fact freshness, ssh-arg filtering, and tag inference."""

from __future__ import annotations

import datetime as dt

from ssh_learn.facts import (
    facts_are_fresh,
    filter_fact_ssh_args,
    infer_hostname_tags,
    tags_from_remote_facts,
)
from ssh_learn.timeutil import now_iso


def test_facts_are_fresh():
    assert facts_are_fresh({"collected_at": now_iso()})
    old = (dt.datetime.now().astimezone() - dt.timedelta(days=30)).isoformat()
    assert not facts_are_fresh({"collected_at": old})
    assert not facts_are_fresh({})
    assert not facts_are_fresh(None)


def test_filter_fact_ssh_args_keeps_connection_options():
    args = ["-p", "2222", "-i", "~/.ssh/k", "-L", "8080:localhost:80", "-N"]
    filtered = filter_fact_ssh_args(args)
    assert "-p" in filtered and "2222" in filtered
    assert "-i" in filtered and "~/.ssh/k" in filtered
    # Port-forward and no-command flags are dropped for the fact probe.
    assert "-L" not in filtered
    assert "-N" not in filtered


def test_infer_hostname_tags():
    # Tokens are matched whole, so use standalone label components.
    tags = infer_hostname_tags("web-prod-postgres.example.com")
    assert "prod" in tags
    assert "postgres" in tags
    assert infer_hostname_tags("db-postgresql.example.com") >= {"postgres"}


def test_tags_from_remote_facts():
    facts = {"environment": "production dr", "files": {"role": "web,db"}}
    tags = tags_from_remote_facts(facts)
    assert {"production", "dr", "web", "db"} <= tags
