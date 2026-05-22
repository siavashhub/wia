"""Tests that ``additional_internal_domains`` flows into categorization.

This is the hotfix/0.3.1 fix for the "Github" client bucket: when a
Microsoft user attends a meeting with @github.com attendees, the
categorizer was treating GitHub as an external client. Adding
github.com to ``additional_internal_domains`` (seeded by default for
Microsoft users) makes the meeting collapse to ``Internal`` instead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from wia.core.categorization import categorize
from wia.core.orchestrator import _build_internal_domains
from wia.core.types import ActivityBlock, Confidence, Source


def _block(participants: list[str]) -> ActivityBlock:
    return ActivityBlock(
        start=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        end=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
        title="APEX Micro-Hack",
        participants=participants,
        source=Source.CALENDAR,
        confidence=Confidence.HIGH,
    )


def test_github_attendee_becomes_client_without_union():
    # Baseline: with only microsoft.com as internal, an @github.com
    # attendee trips the external-domain rule and the meeting gets
    # bucketed as a "Github" client.
    _label, cat = categorize(
        _block(["alice@microsoft.com", "bob@github.com"]),
        internal_domains={"microsoft.com"},
    )
    assert cat == "Github"


def test_github_attendee_collapses_to_internal_with_union():
    # With the hotfix: github.com is in ``additional_internal_domains``
    # so the meeting is all-internal and collapses to the Internal bucket.
    _label, cat = categorize(
        _block(["alice@microsoft.com", "bob@github.com"]),
        internal_domains={"microsoft.com", "github.com"},
    )
    assert cat == "Internal"


def test_build_internal_domains_unions_additional():
    domains = _build_internal_domains(
        "Microsoft",
        blocks=[],
        additional_domains=["github.com", "xbox.com"],
    )
    assert "microsoft.com" in domains
    assert "github.com" in domains
    assert "xbox.com" in domains


def test_build_internal_domains_normalises_additional():
    domains = _build_internal_domains(
        "Microsoft",
        blocks=[],
        additional_domains=["@GitHub.com", "  XBOX.COM "],
    )
    assert "github.com" in domains
    assert "xbox.com" in domains


def test_external_non_internal_domain_still_wins_as_client():
    # github.com is internal, but a real third-party attendee still
    # makes this a client meeting.
    _label, cat = categorize(
        _block(["alice@microsoft.com", "bob@github.com", "carol@acme-corp.com"]),
        internal_domains={"microsoft.com", "github.com"},
    )
    # Acme wins — the heuristic strips "-corp" suffix and Title-cases.
    assert cat.lower().startswith("acme")
