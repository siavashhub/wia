"""Work IQ status / enable endpoints.

WIA does not perform M365 sign-in itself. The ``@microsoft/workiq`` CLI
manages authentication using its own first-party Entra application (which
the tenant admin consents to once). WIA's job is just to:

- detect whether the CLI is installed and reachable,
- offer the user an "Enable Work IQ" action that triggers the CLI's own
  first-run auth flow.
"""

from __future__ import annotations

from fastapi import APIRouter

from wia.api.prefs import (
    derive_organization_label_from_domain,
    get_organization_label,
    get_user_identity,
    is_organization_auto,
    set_organization_label,
    set_user_identity,
)
from wia.mcp_clients.workiq import get_workiq_client

router = APIRouter()


@router.get("/status")
async def status() -> dict[str, str | bool | None]:
    client = get_workiq_client()
    info = await client.probe()
    return {
        "installed": info.installed,
        "ready": info.ready,
        "version": info.version,
        "message": info.message,
    }


@router.post("/enable")
async def enable() -> dict[str, str | bool | None]:
    """Trigger Work IQ's first-run auth (opens its own browser/device flow)."""
    client = get_workiq_client()
    info = await client.enable()
    return {
        "installed": info.installed,
        "ready": info.ready,
        "version": info.version,
        "message": info.message,
    }


@router.get("/identity")
async def identity(refresh: bool = False) -> dict[str, str | None]:
    """Return the signed-in M365 user behind the Work IQ CLI.

    The result is cached in user prefs after the first successful fetch
    so the UI can render the UPN immediately on subsequent loads. Pass
    ``?refresh=true`` to force a re-query.
    """
    cached_upn, cached_name = get_user_identity()
    if not refresh and cached_upn:
        return {
            "upn": cached_upn,
            "display_name": cached_name or None,
            "source": "cache",
        }

    client = get_workiq_client()
    ident = await client.fetch_user_identity()
    if ident is None:
        return {
            "upn": cached_upn or None,
            "display_name": cached_name or None,
            "source": "unavailable",
        }

    set_user_identity(ident.upn, ident.display_name)

    # Opportunistically seed the organization label from the freshly
    # fetched identity. Only auto-fill when the label is empty or was
    # previously auto-derived — never override a user-set value.
    current_org = get_organization_label()
    if not current_org or is_organization_auto():
        derived = (ident.tenant_name or "").strip()
        if not derived:
            domain = ident.upn.split("@", 1)[1] if "@" in ident.upn else ""
            derived = derive_organization_label_from_domain(domain)
        if derived and derived != current_org:
            set_organization_label(derived, auto=True)

    return {
        "upn": ident.upn,
        "display_name": ident.display_name,
        "source": ident.source,
    }
