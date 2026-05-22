"""WIA MCP server — exposes briefing/entries/actions/export over stdio.

Allows GitHub Copilot in VS Code (or any MCP client) to query WIA via tools:

- ``get_weekly_briefing(week_of: str | null) -> Briefing``
- ``list_time_entries(week_of: str | null) -> TimeEntry[]``
- ``list_actions(week_of: str | null, include_resolved: bool) -> Action[]``
- ``update_action(action_id: int, status: str, ...) -> Action``
- ``export_entries_csv(week_of: str | null) -> string``
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from wia.api.export import _entries_csv
from wia.core.orchestrator import build_briefing
from wia.core.types import ActionStatus, ActionUpdate
from wia.storage import actions as actions_repo
from wia.storage import entries as entries_repo
from wia.storage.db import init_db

log = logging.getLogger(__name__)

server: Server = Server("wia")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_weekly_briefing",
            description="Generate or retrieve the WIA weekly briefing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "week_of": {
                        "type": "string",
                        "description": "Any ISO date within the target week (e.g. 2026-04-20). Defaults to current week.",
                    },
                    "refresh": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="list_time_entries",
            description="List the WIA time entries for a given week.",
            inputSchema={
                "type": "object",
                "properties": {
                    "week_of": {"type": "string", "description": "ISO date of the week's Monday."}
                },
            },
        ),
        Tool(
            name="export_entries_csv",
            description="Return time entries as CSV text for the given week.",
            inputSchema={
                "type": "object",
                "properties": {"week_of": {"type": "string"}},
            },
        ),
        Tool(
            name="list_actions",
            description=(
                "List WIA Actions (suggested follow-ups, decision notes, ...). "
                "By default hides resolved (dismissed/completed) actions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "week_of": {
                        "type": "string",
                        "description": "ISO date within the target week. Omit for all weeks.",
                    },
                    "include_resolved": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="update_action",
            description=(
                "Transition an action: status in [accepted, snoozed, dismissed, completed]. "
                "For snoozed, supply snoozed_until (ISO 8601). For dismissed, supply optional reason."
            ),
            inputSchema={
                "type": "object",
                "required": ["action_id", "status"],
                "properties": {
                    "action_id": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "enum": ["accepted", "snoozed", "dismissed", "completed"],
                    },
                    "snoozed_until": {
                        "type": "string",
                        "description": "ISO 8601 timestamp; required when status='snoozed'.",
                    },
                    "dismissed_reason": {"type": "string"},
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get_weekly_briefing":
        week_of = arguments.get("week_of")
        refresh = bool(arguments.get("refresh", False))
        any_day = date.fromisoformat(week_of) if week_of else None
        briefing = await build_briefing(week_of=any_day, refresh=refresh)
        return [TextContent(type="text", text=briefing.model_dump_json(indent=2))]

    if name == "list_time_entries":
        week_of = arguments.get("week_of")
        entries = entries_repo.list_entries(week_of=week_of)
        payload = "[" + ",".join(e.model_dump_json() for e in entries) + "]"
        return [TextContent(type="text", text=payload)]

    if name == "export_entries_csv":
        return [TextContent(type="text", text=_entries_csv(arguments.get("week_of")))]

    if name == "list_actions":
        week_of = arguments.get("week_of")
        statuses: list[ActionStatus] | None = None
        if not bool(arguments.get("include_resolved", False)):
            statuses = [
                ActionStatus.SUGGESTED,
                ActionStatus.ACCEPTED,
                ActionStatus.SNOOZED,
            ]
        actions = actions_repo.list_actions(week_of=week_of, statuses=statuses)
        payload = "[" + ",".join(a.model_dump_json() for a in actions) + "]"
        return [TextContent(type="text", text=payload)]

    if name == "update_action":
        action_id = int(arguments["action_id"])
        status = ActionStatus(arguments["status"])
        snoozed_until_raw = arguments.get("snoozed_until")
        snoozed_until = datetime.fromisoformat(snoozed_until_raw) if snoozed_until_raw else None
        update = ActionUpdate(
            status=status,
            snoozed_until=snoozed_until,
            dismissed_reason=arguments.get("dismissed_reason"),
        )
        updated = actions_repo.update_action(action_id, update)
        if updated is None:
            raise ValueError(f"action {action_id} not found")
        return [TextContent(type="text", text=updated.model_dump_json(indent=2))]

    raise ValueError(f"unknown tool {name!r}")


async def _serve() -> None:
    init_db()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def run() -> None:
    """Console entry point: ``wia-mcp``."""
    logging.basicConfig(level="INFO")
    asyncio.run(_serve())


if __name__ == "__main__":
    run()
