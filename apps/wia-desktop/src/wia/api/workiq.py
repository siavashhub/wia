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
