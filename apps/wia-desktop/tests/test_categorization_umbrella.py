"""Tests for umbrella-category title extraction in categorize()."""

from __future__ import annotations

from datetime import UTC, datetime

from wia.core.categorization import (
    _extract_category_from_title,
    aggregate_entries,
    categorize,
)
from wia.core.types import ActivityBlock, Confidence, Source


def _b(title, *, categories_display=None, participants=(), hours=1.0):
    metadata: dict[str, str] = {}
    if categories_display:
        metadata["categories_display"] = categories_display
        metadata["categories"] = "|".join(c.strip().lower() for c in categories_display.split(","))
    return ActivityBlock(
        start=datetime(2026, 5, 14, 9, 0, tzinfo=UTC),
        end=datetime(2026, 5, 14, 9, 0, tzinfo=UTC).replace(
            hour=9 + int(hours), minute=int((hours % 1) * 60)
        ),
        title=title,
        participants=list(participants),
        source=Source.CALENDAR,
        confidence=Confidence.HIGH,
        metadata=metadata,
    )


# --- _extract_category_from_title -----------------------------------


def test_extract_first_segment_for_dash_separator():
    assert _extract_category_from_title("Contoso- Azure Landing Zone ANF") == "Contoso"


def test_extract_first_segment_for_endash_separator():
    assert _extract_category_from_title("Friedfrank \u2013 ALZ planning") == "Friedfrank"


def test_extract_first_segment_for_colon_separator():
    assert _extract_category_from_title("Fabrikam: KO sync") == "Fabrikam"


def test_extract_returns_none_when_no_separator():
    assert _extract_category_from_title("Random brainstorm") is None


def test_extract_returns_none_for_empty_or_whitespace():
    assert _extract_category_from_title("") is None
    assert _extract_category_from_title("   ") is None


def test_extract_skips_stopword_first_segment():
    assert _extract_category_from_title("Weekly - Contososync") == "Contososync"


def test_extract_skips_all_stopwords_returns_none():
    # Both segments are stopwords \u2014 nothing useful to extract.
    assert _extract_category_from_title("Weekly - Sync") is None


def test_extract_rejects_overlong_segment():
    long_title = "X" * 30 + " - tail"
    # First segment too long, falls through to second which is fine.
    assert _extract_category_from_title(long_title) == "tail"


# --- categorize() integration --------------------------------------


def test_umbrella_customer_extracts_specific_code_from_title():
    block = _b("Contoso- Azure Landing Zone ANF", categories_display="Customer")
    label, cat = categorize(block, umbrella_categories=["Customer"])
    assert cat == "Contoso"
    # Label should not double-up the category name.
    assert label == "Contoso\u2013 Contoso- Azure Landing Zone ANF" or label == "Contoso- Azure Landing Zone ANF"


def test_umbrella_customer_extracts_td_from_title():
    block = _b("Fabrikam- KO", categories_display="Customer")
    _label, cat = categorize(block, umbrella_categories=["Customer"])
    assert cat == "Fabrikam"


def test_non_umbrella_category_is_used_verbatim():
    # "Suffolk" isn't an umbrella, so the Outlook tag wins as-is.
    block = _b("City of Suffolk sync", categories_display="Suffolk")
    _label, cat = categorize(block, umbrella_categories=["Customer"])
    assert cat == "Suffolk"


def test_umbrella_match_is_case_insensitive():
    block = _b("Contoso- Azure Landing Zone ANF", categories_display="customer")
    _label, cat = categorize(block, umbrella_categories=["Customer"])
    assert cat == "Contoso"


def test_umbrella_falls_back_to_external_participant_when_no_separator():
    block = _b(
        "Brainstorm",
        categories_display="Customer",
        participants=["alice@bigco.com"],
    )
    _label, cat = categorize(
        block,
        umbrella_categories=["Customer"],
        internal_domains={"contoso.com"},
    )
    assert cat == "Bigco"


def test_umbrella_falls_back_to_raw_tag_when_no_signal():
    # No separator and no external attendees \u2014 last resort: keep the
    # umbrella name rather than dropping to "Other".
    block = _b("Brainstorm", categories_display="Customer")
    _label, cat = categorize(block, umbrella_categories=["Customer"])
    assert cat == "Customer"


def test_no_umbrellas_configured_uses_outlook_tag_verbatim():
    block = _b("Contoso- Azure Landing Zone", categories_display="Customer")
    _label, cat = categorize(block, umbrella_categories=[])
    assert cat == "Customer"


# --- aggregate_entries --------------------------------------------


def test_aggregate_groups_separately_by_extracted_code():
    blocks = [
        _b("Contoso- Azure Landing Zone ANF", categories_display="Customer"),
        _b("Contoso- migration", categories_display="Customer"),
        _b("Fabrikam- KO", categories_display="Customer"),
    ]
    entries = aggregate_entries(blocks, umbrella_categories=["Customer"])
    categories = [e.category for e in entries]
    # Two distinct Contosoevents (different titles, so different labels) plus
    # one Fabrikamevent — the win is they now share the Contoso/ Fabrikambucket
    # instead of all collapsing into a single "Customer" bucket.
    assert categories.count("Contoso") == 2
    assert categories.count("Fabrikam") == 1
    assert "Customer" not in categories
    ctc_hours = sum(e.duration_hours for e in entries if e.category == "Contoso")
    assert ctc_hours == 2.0
