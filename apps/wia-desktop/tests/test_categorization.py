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


def test_default_impact_high_keyword_overrides_low():
    # Keyword match on label promotes to HIGH even when the category would
    # otherwise default to LOW (Internal / Admin / org).
    assert (
        default_impact_for_category(
            "Internal",
            label="Internal – Launch readiness",
            high_impact_keywords=["launch"],
        )
        is Impact.HIGH
    )
    # Case-insensitive substring.
    assert (
        default_impact_for_category(
            "Microsoft",
            organization_label="Microsoft",
            label="Microsoft – CEO briefing",
            high_impact_keywords=["CEO"],
        )
        is Impact.HIGH
    )
    # No match → falls back to category default.
    assert (
        default_impact_for_category(
            "Internal",
            label="Internal – Standup",
            high_impact_keywords=["launch"],
        )
        is Impact.LOW
    )
    # Empty keywords list is a no-op.
    assert (
        default_impact_for_category("Design", label="Design – Launch", high_impact_keywords=[])
        is Impact.MEDIUM
    )


def test_aggregate_high_impact_keyword_promotes_entry():
    blocks = [
        _b("Standup"),  # Internal → LOW normally
        _b("Project Atlas launch sync"),  # Internal → would be LOW, but matches keyword
        _b("Design review"),  # Design → MEDIUM
    ]
    entries = aggregate_entries(
        blocks,
        organization_label="Microsoft",
        high_impact_keywords=["launch"],
    )
    by_label = {e.label: e.impact for e in entries}
    launch_entries = [imp for label, imp in by_label.items() if "launch" in label.lower()]
    assert launch_entries and all(i is Impact.HIGH for i in launch_entries)
    # Standup remains LOW.
    standup_entries = [imp for label, imp in by_label.items() if "Standup" in label]
    assert standup_entries and all(i is Impact.LOW for i in standup_entries)


def _bcat(title, categories, participants=(), hours=1.0):
    """Build a calendar block with a ``|``-joined lowercase categories
    metadata string, matching what the Work IQ MCP client emits."""
    b = _b(title, participants=participants, source=Source.CALENDAR, hours=hours)
    b.metadata["categories"] = "|".join(c.lower() for c in categories)
    return b


def test_aggregate_high_impact_category_promotes_entry():
    # A calendar block tagged with a high-impact Outlook category gets
    # promoted to HIGH even when its category would otherwise be LOW.
    blocks = [
        _bcat("Standup", categories=["Customer"]),  # Internal → LOW, but flagged
        _b("Design review"),  # Design → MEDIUM
    ]
    entries = aggregate_entries(
        blocks,
        organization_label="Microsoft",
        high_impact_categories=["customer"],
    )
    standup = next(e for e in entries if "Standup" in e.label)
    assert standup.impact is Impact.HIGH
    design = next(e for e in entries if "Design" in e.label)
    assert design.impact is Impact.MEDIUM


def test_aggregate_high_impact_category_case_insensitive():
    blocks = [_bcat("Sync", categories=["customer"])]
    entries = aggregate_entries(blocks, high_impact_categories=["Customer"])
    assert entries[0].impact is Impact.HIGH


def test_aggregate_high_impact_category_no_match_keeps_default():
    blocks = [_bcat("Standup", categories=["internal"])]
    entries = aggregate_entries(blocks, high_impact_categories=["customer"])
    assert entries[0].impact is Impact.LOW

