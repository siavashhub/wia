"""Tests for the Work IQ identity payload parser."""

from __future__ import annotations

from wia.mcp_clients.workiq import WorkIQIdentity, _identity_from_payload


def test_identity_from_direct_dict() -> None:
    ident = _identity_from_payload(
        {"upn": "alice@microsoft.com", "displayName": "Alice", "tenantName": "Microsoft"},
        source="me",
    )
    assert ident == WorkIQIdentity(
        upn="alice@microsoft.com",
        display_name="Alice",
        tenant_name="Microsoft",
        source="me",
    )


def test_identity_from_ask_work_iq_response_envelope() -> None:
    payload = {
        "response": '{"upn":"bob@contoso.com","displayName":"Bob","tenantName":"Contoso"}',
        "conversationId": "abc",
    }
    ident = _identity_from_payload(payload, source="ask_work_iq")
    assert ident is not None
    assert ident.upn == "bob@contoso.com"
    assert ident.display_name == "Bob"
    assert ident.tenant_name == "Contoso"


def test_identity_handles_markdown_fences() -> None:
    payload = '```json\n{"upn":"c@d.com"}\n```'
    ident = _identity_from_payload(payload, source="ask_work_iq")
    assert ident is not None
    assert ident.upn == "c@d.com"
    assert ident.display_name is None


def test_identity_accepts_alternate_keys() -> None:
    ident = _identity_from_payload(
        {"userPrincipalName": "x@y.com", "name": "Xavier", "organization": "Acme"},
        source="me",
    )
    assert ident is not None
    assert ident.upn == "x@y.com"
    assert ident.display_name == "Xavier"
    assert ident.tenant_name == "Acme"


def test_identity_returns_none_without_upn() -> None:
    assert _identity_from_payload({"displayName": "Nobody"}, source="me") is None
    assert _identity_from_payload(None, source="me") is None
    assert _identity_from_payload("not json", source="me") is None
