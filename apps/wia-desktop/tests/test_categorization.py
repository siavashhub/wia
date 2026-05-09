from datetime import UTC, datetime

from wia.core.categorization import (
    aggregate_entries,
    categorize,
    default_impact_for_category,
)
from wia.core.types import ActivityBlock, Confidence, Impact, Source


def _b(title, participants=(), source=Source.CALENDAR, hours=1.0):
    return ActivityBlock(
        start=datetime(2026, 4, 20, 9, 0, tzinfo=UTC),
        end=datetime(2026, 4, 20, 9, 0, tzinfo=UTC).replace(
            hour=9 + int(hours), minute=int((hours % 1) * 60)
        ),
        title=title,
        participants=list(participants),
        source=source,
        confidence=Confidence.HIGH,
    )


def test_keyword_classification():
    label, cat = categorize(_b("Sprint planning"))
    assert cat == "Internal"
    assert "Sprint planning" in label


def test_external_participant_becomes_client():
    _label, cat = categorize(
        _b("Design review", participants=["alice@client-a.com"]),
        internal_domains={"contoso.com"},
    )
    assert cat == "Client A"


def test_inferred_block_is_admin():
    block = _b("Admin / Follow-up", source=Source.INFERRED)
    _label, cat = categorize(block)
    assert cat == "Admin"


def test_aggregate_groups_by_label():
    blocks = [
        _b("Standup", hours=0.5),
        _b("Standup", hours=0.5),
        _b("Design review", hours=1.0),
    ]
    entries = aggregate_entries(blocks)
    by_label = {e.label: e.duration_hours for e in entries}
    assert any("Standup" in k for k in by_label)
    standup_hours = next(v for k, v in by_label.items() if "Standup" in k)
    assert standup_hours == 1.0


def test_default_impact_internal_admin_low():
    assert default_impact_for_category("Internal") is Impact.LOW
    assert default_impact_for_category("admin") is Impact.LOW
    assert default_impact_for_category("Design") is Impact.MEDIUM
    assert default_impact_for_category(None) is Impact.MEDIUM


def test_default_impact_organization_label_low():
    # User's own org categories also default to Low.
    assert default_impact_for_category("Microsoft", organization_label="Microsoft") is Impact.LOW
    # Case-insensitive match.
    assert default_impact_for_category("microsoft", organization_label="Microsoft") is Impact.LOW
    # Other categories untouched.
    assert default_impact_for_category("Client A", organization_label="Microsoft") is Impact.MEDIUM


def test_aggregate_assigns_default_impact():
    blocks = [
        _b("Standup"),  # → Internal → LOW
        _b("Design review"),  # → Design → MEDIUM
        _b("Microsoft sync"),  # title contains nothing matching keyword map → category "Internal"
    ]
    entries = aggregate_entries(blocks, organization_label="Microsoft")
    by_cat = {e.category: e.impact for e in entries}
    assert by_cat["Internal"] is Impact.LOW
    assert by_cat["Design"] is Impact.MEDIUM
