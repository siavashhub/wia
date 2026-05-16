"""Tests for the calendar dual-query merge."""

from __future__ import annotations

from wia.mcp_clients.workiq import _has_categories, _merge_event_payloads


def _ev(title, start, *, categories=None, participants=None):
    out = {"title": title, "start": start, "end": start, "participants": participants or []}
    if categories is not None:
        out["categories"] = categories
    return out


def test_has_categories_true_for_non_empty_list():
    assert _has_categories(_ev("x", "2026-05-14T10:00", categories=["Customer"])) is True


def test_has_categories_false_for_empty_or_blank():
    assert _has_categories(_ev("x", "2026-05-14T10:00", categories=[])) is False
    assert _has_categories(_ev("x", "2026-05-14T10:00")) is False
    assert _has_categories(_ev("x", "2026-05-14T10:00", categories=["  "])) is False


def test_merge_unions_distinct_events():
    a = [_ev("Meeting A", "2026-05-14T10:00")]
    b = [_ev("Appointment B", "2026-05-14T14:00")]
    merged = _merge_event_payloads(a, b)
    titles = [e["title"] for e in merged]
    assert titles == ["Meeting A", "Appointment B"]


def test_merge_dedups_by_start_and_title():
    a = [_ev("Contoso- Azure Landing Zone", "2026-05-14T10:00")]
    b = [_ev("Contoso- Azure Landing Zone", "2026-05-14T10:00")]
    merged = _merge_event_payloads(a, b)
    assert len(merged) == 1


def test_merge_dedup_is_case_and_whitespace_insensitive():
    a = [_ev("Contoso -  Azure Landing Zone", "2026-05-14T10:00")]
    b = [_ev("contoso - azure landing zone", "2026-05-14T10:00")]
    merged = _merge_event_payloads(a, b)
    assert len(merged) == 1


def test_merge_prefers_copy_with_categories():
    # Primary has no categories, secondary does — secondary wins so the
    # Outlook category isn't lost.
    a = [_ev("Contoso- Azure Landing Zone", "2026-05-14T10:00", categories=[])]
    b = [_ev("Contoso- Azure Landing Zone", "2026-05-14T10:00", categories=["Customer"])]
    merged = _merge_event_payloads(a, b)
    assert len(merged) == 1
    assert merged[0]["categories"] == ["Customer"]


def test_merge_keeps_primary_when_secondary_has_no_categories():
    a = [_ev("Contoso- Azure Landing Zone", "2026-05-14T10:00", categories=["Customer"])]
    b = [_ev("Contoso- Azure Landing Zone", "2026-05-14T10:00", categories=[])]
    merged = _merge_event_payloads(a, b)
    assert len(merged) == 1
    assert merged[0]["categories"] == ["Customer"]


def test_merge_preserves_primary_ordering():
    a = [
        _ev("A", "2026-05-14T09:00"),
        _ev("B", "2026-05-14T10:00"),
    ]
    b = [
        _ev("C", "2026-05-14T11:00"),
        _ev("A", "2026-05-14T09:00"),
    ]
    merged = _merge_event_payloads(a, b)
    titles = [e["title"] for e in merged]
    assert titles == ["A", "B", "C"]


def test_merge_skips_non_dict_entries():
    a = ["garbage", None, _ev("A", "2026-05-14T09:00")]
    b = [None, _ev("B", "2026-05-14T10:00")]
    merged = _merge_event_payloads(a, b)
    titles = [e["title"] for e in merged]
    assert titles == ["A", "B"]
