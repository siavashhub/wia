"""Work IQ MCP client.

Spawns the Work IQ MCP server (``@microsoft/workiq mcp``) over stdio and
exposes typed wrappers for the tools WIA needs in V1 (calendar / meeting
queries scoped to a week range).

Authentication is handled entirely by the Work IQ CLI itself (using its
first-party Entra app). WIA never sees tokens; it only spawns the CLI
process which prompts the user to sign in on first run if needed.

V1 contract (subject to confirmation against Work IQ MCP tool schemas):

- ``calendar.list`` (or equivalent) returning meetings with start/end/title/
  participants for a date range.

This client normalizes the response into ``ActivityBlock`` objects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from wia.config import get_settings
from wia.core.types import ActivityBlock, Confidence, Source

log = logging.getLogger(__name__)


@dataclass
class WorkIQStatus:
    installed: bool
    ready: bool
    version: str | None = None
    message: str | None = None


def _resolve_command(command: str) -> str | None:
    """Resolve a command name to its absolute executable path.

    On Windows, ``shutil.which`` finds ``.cmd``/``.bat``/``.ps1`` shims that
    ``asyncio.create_subprocess_exec`` cannot launch directly without going
    through the shell. We just use the resolved path.
    """
    return shutil.which(command)


async def _run(executable: str, args: list[str], *, timeout: float) -> tuple[int, bytes, bytes]:
    """Run a command, returning ``(returncode, stdout, stderr)``.

    Uses ``create_subprocess_shell`` on Windows when the resolved path is a
    ``.cmd``/``.bat``/``.ps1`` shim, otherwise ``create_subprocess_exec``.
    """
    lower = executable.lower()
    if lower.endswith((".cmd", ".bat")):
        # cmd.exe shims
        cmdline = subprocess_quote([executable, *args])
        proc = await asyncio.create_subprocess_shell(
            cmdline,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    elif lower.endswith(".ps1"):
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode or 0, stdout or b"", stderr or b""


def subprocess_quote(parts: list[str]) -> str:
    """Quote a Windows command line for cmd.exe."""
    out = []
    for p in parts:
        if any(ch in p for ch in ' \t"&|<>^'):
            out.append('"' + p.replace('"', '\\"') + '"')
        else:
            out.append(p)
    return " ".join(out)


class WorkIQClient:
    """Async wrapper around the Work IQ MCP server."""

    def __init__(self) -> None:
        s = get_settings()
        # Resolve to absolute path so ``.cmd``/``.ps1`` shims work on Windows.
        # Fall back to the bare command name if not found on PATH; the probe
        # will surface a clear error to the UI in that case.
        resolved = _resolve_command(s.workiq_command) or s.workiq_command
        lower = resolved.lower()
        if lower.endswith((".cmd", ".bat")):
            # Windows ``.cmd`` shims need to go through ``cmd.exe /c`` so that
            # stdio pipes are wired correctly for the long-running MCP server.
            self._params = StdioServerParameters(
                command="cmd.exe",
                args=["/c", resolved, *s.workiq_args],
            )
        elif lower.endswith(".ps1"):
            self._params = StdioServerParameters(
                command="powershell.exe",
                args=[
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    resolved,
                    *s.workiq_args,
                ],
            )
        else:
            self._params = StdioServerParameters(command=resolved, args=list(s.workiq_args))
        self._lock = asyncio.Lock()

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Open a fresh stdio session, call the tool, parse the result.

        We open a session per call for V1 simplicity; can be pooled later.
        """
        async with (
            self._lock,
            stdio_client(self._params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(name, arguments=arguments)

        # MCP results carry text content; assume JSON payload from the tool.
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return None

    async def fetch_calendar_blocks(self, start: date, end: date) -> list[ActivityBlock]:
        """Fetch every calendar event between [start, end] inclusive.

        We deliberately ask for *all* events (past, future, accepted,
        tentative, declined, all-day, recurring) so the briefing reflects
        the user's intent — including future days of the current week
        that haven't happened yet. Work IQ's MCP server only exposes a
        single natural-language tool (``ask_work_iq``) backed by Microsoft
        365 Copilot, so we coerce a JSON-shaped answer and parse it.
        """
        prompt = (
            f"List every event on my calendar between {start.isoformat()} 00:00 "
            f"and {end.isoformat()} 23:59 (inclusive of both endpoints). "
            "Include past, current, and future events. Include accepted, "
            "tentative, and organizer events. Include all-day events and "
            "every occurrence of recurring events whose instance falls in "
            "this range. Do NOT exclude future events or events I have "
            "not yet attended. "
            "Return ONLY a JSON object, no prose, no markdown fences, in this exact shape: "
            '{"events":[{"title":"...","start":"ISO8601","end":"ISO8601",'
            '"organizer":"email","participants":["email"],"isOnline":true,'
            '"categories":["<outlook category name>"],"sensitivity":"normal|personal|private|confidential"}]}. '
            "Include the event's Outlook categories array (empty array if none) "
            "and its sensitivity (one of normal, personal, private, confidential). "
            "Use ISO 8601 timestamps with timezone offsets. "
            'If there are no events, return {"events":[]}.'
        )
        try:
            payload = await self._call_tool("ask_work_iq", {"question": prompt})
        except Exception as exc:
            log.warning("Work IQ ask_work_iq failed: %r", exc, exc_info=True)
            raise

        events = _extract_events(payload)
        blocks: list[ActivityBlock] = []
        for ev in events:
            try:
                blocks.append(_event_to_block(ev, source=Source.CALENDAR))
            except Exception as exc:
                log.debug("Skipping malformed event %s: %s", ev, exc)
        log.info("Work IQ returned %d calendar events for %s..%s", len(blocks), start, end)
        return blocks

    async def fetch_teams_blocks(self, start: date, end: date) -> list[ActivityBlock]:
        """Fetch Teams chat / call signals between [start, end] inclusive.

        We ask for substantive 1:1 and group chat conversations and ad-hoc
        calls. Each chat thread is summarised as a single time block sized
        by total active engagement during the period, with participants
        and a short topic title.
        """
        prompt = (
            f"List my Teams chat threads and ad-hoc call sessions with "
            f"meaningful activity between {start.isoformat()} 00:00 and "
            f"{end.isoformat()} 23:59 (inclusive). For each thread or call, "
            "estimate the total active minutes I spent (reading + writing + "
            "talking) and pick a representative start/end timestamp. "
            "Return ONLY a JSON object, no prose, no markdown fences, in this exact shape: "
            '{"events":[{"title":"<short topic>","start":"ISO8601","end":"ISO8601",'
            '"participants":["email"]}]}. '
            "Use ISO 8601 timestamps with timezone offsets. "
            'If there is no Teams activity, return {"events":[]}.'
        )
        try:
            payload = await self._call_tool("ask_work_iq", {"question": prompt})
        except Exception as exc:
            log.warning("Work IQ Teams fetch failed: %r", exc, exc_info=True)
            raise

        events = _extract_events(payload)
        blocks: list[ActivityBlock] = []
        for ev in events:
            try:
                blocks.append(
                    _event_to_block(ev, source=Source.TEAMS, confidence=Confidence.MEDIUM)
                )
            except Exception as exc:
                log.debug("Skipping malformed Teams event %s: %s", ev, exc)
        log.info("Work IQ returned %d Teams blocks for %s..%s", len(blocks), start, end)
        return blocks

    async def fetch_email_blocks(self, start: date, end: date) -> list[ActivityBlock]:
        """Fetch email-driven work sessions between [start, end] inclusive.

        We ask Work IQ to cluster substantive email threads into work blocks
        — i.e. periods where I was actively reading or replying to a
        thread. Bulk newsletters and notifications should be excluded.
        """
        prompt = (
            f"List my substantive email threads I actively read or replied to "
            f"between {start.isoformat()} 00:00 and {end.isoformat()} 23:59 "
            "(inclusive). Exclude bulk newsletters, calendar invites, "
            "automated notifications, and unread spam. For each thread, "
            "estimate the total active minutes I spent and pick a "
            "representative start/end timestamp. "
            "Return ONLY a JSON object, no prose, no markdown fences, in this exact shape: "
            '{"events":[{"title":"<thread subject>","start":"ISO8601","end":"ISO8601",'
            '"participants":["email"]}]}. '
            "Use ISO 8601 timestamps with timezone offsets. "
            'If there is no email activity, return {"events":[]}.'
        )
        try:
            payload = await self._call_tool("ask_work_iq", {"question": prompt})
        except Exception as exc:
            log.warning("Work IQ email fetch failed: %r", exc, exc_info=True)
            raise

        events = _extract_events(payload)
        blocks: list[ActivityBlock] = []
        for ev in events:
            try:
                blocks.append(
                    _event_to_block(ev, source=Source.EMAIL, confidence=Confidence.MEDIUM)
                )
            except Exception as exc:
                log.debug("Skipping malformed email event %s: %s", ev, exc)
        log.info("Work IQ returned %d email blocks for %s..%s", len(blocks), start, end)
        return blocks

    async def probe(self) -> WorkIQStatus:
        """Quick check: is the Work IQ CLI installed and signed in?

        Runs ``@microsoft/workiq --version`` and treats success as ``ready``.
        On first run, the CLI may print sign-in instructions; this probe
        intentionally does not trigger interactive auth.
        """
        s = get_settings()
        executable = _resolve_command(s.workiq_command)
        if executable is None:
            return WorkIQStatus(
                installed=False,
                ready=False,
                message=f"{s.workiq_command!r} not found on PATH. Install Node.js 18+.",
            )
        try:
            rc, stdout, stderr = await _run(
                executable, [*s.workiq_cli_args, "--version"], timeout=60
            )
        except TimeoutError:
            return WorkIQStatus(installed=True, ready=False, message="Work IQ probe timed out.")
        except Exception as exc:
            return WorkIQStatus(installed=False, ready=False, message=str(exc))

        version = stdout.decode("utf-8", errors="replace").strip() or None
        if rc == 0:
            return WorkIQStatus(installed=True, ready=True, version=version)
        return WorkIQStatus(
            installed=True,
            ready=False,
            version=version,
            message=stderr.decode("utf-8", errors="replace").strip()
            or "Work IQ is installed but not signed in. Click Enable Work IQ.",
        )

    async def enable(self) -> WorkIQStatus:
        """Trigger the Work IQ CLI's first-run auth flow.

        Runs ``workiq ask`` with a no-op question; on first launch the CLI
        prints a device-code URL or pops its own browser window. We stream
        output so the user sees the sign-in prompt; success means the CLI
        produced any output without erroring.
        """
        s = get_settings()
        executable = _resolve_command(s.workiq_command)
        if executable is None:
            return WorkIQStatus(
                installed=False,
                ready=False,
                message=f"{s.workiq_command!r} not found. Install Node.js 18+.",
            )
        try:
            rc, _stdout, stderr = await _run(
                executable, [*s.workiq_cli_args, "ask", "-q", "ping"], timeout=300
            )
        except TimeoutError:
            return WorkIQStatus(
                installed=True,
                ready=False,
                message="Sign-in timed out. Try again — a browser window may have opened.",
            )
        except Exception as exc:
            return WorkIQStatus(installed=True, ready=False, message=str(exc))

        if rc == 0:
            return WorkIQStatus(installed=True, ready=True, message="Work IQ is enabled.")
        return WorkIQStatus(
            installed=True,
            ready=False,
            message=(stderr or b"").decode("utf-8", errors="replace").strip()
            or "Work IQ failed to authenticate.",
        )


def _extract_events(payload: Any) -> list[dict[str, Any]]:
    """Normalise an ``ask_work_iq`` response to a list of event dicts.

    The Work IQ MCP returns ``{"response": "<json string>", "conversationId": ...}``
    where ``response`` is itself a JSON string. We try a few shapes:

    1. ``payload["response"]`` parsed as JSON (the documented contract)
    2. ``payload`` directly if it already has ``events``
    3. ``payload`` if it's a bare list

    Markdown code fences are stripped before JSON parsing because the model
    occasionally adds ```json fences despite the instructions.
    """
    if payload is None:
        return []

    candidates: list[Any] = []
    if isinstance(payload, dict):
        if "response" in payload:
            candidates.append(payload["response"])
        if "events" in payload:
            candidates.append(payload)
    candidates.append(payload)

    for cand in candidates:
        events = _coerce_events(cand)
        if events is not None:
            return events
    log.warning("Work IQ response did not contain events: %r", str(payload)[:500])
    return []


def _coerce_events(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list):
        return [e for e in value if isinstance(e, dict)]
    if isinstance(value, dict):
        events = value.get("events")
        if isinstance(events, list):
            return [e for e in events if isinstance(e, dict)]
        return None
    if isinstance(value, str):
        text = value.strip()
        # Strip ```json ... ``` fences if present.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return _coerce_events(json.loads(text))
        except json.JSONDecodeError:
            return None
    return None


def _event_to_block(
    ev: dict[str, Any],
    *,
    source: Source = Source.CALENDAR,
    confidence: Confidence = Confidence.HIGH,
) -> ActivityBlock:
    start = _parse_dt(ev.get("start") or ev.get("startTime"))
    end = _parse_dt(ev.get("end") or ev.get("endTime"))
    title = ev.get("subject") or ev.get("title")
    attendees = ev.get("attendees") or ev.get("participants") or []
    if attendees and isinstance(attendees[0], dict):
        attendees = [a.get("email") or a.get("address") or "" for a in attendees]
    metadata: dict[str, str] = {"id": str(ev.get("id", ""))}
    # Outlook categories — stored as a ``|``-joined lowercase string so the
    # orchestrator can do a cheap substring/membership check without re-
    # parsing JSON. Empty when the event has no categories.
    categories = ev.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    cat_norm = [str(c).strip() for c in categories if str(c).strip()]
    if cat_norm:
        metadata["categories"] = "|".join(c.lower() for c in cat_norm)
        metadata["categories_display"] = ", ".join(cat_norm)
    # Sensitivity (Outlook): normal | personal | private | confidential.
    # Some sources may provide ``isPrivate`` instead.
    sensitivity = ev.get("sensitivity")
    if not sensitivity and ev.get("isPrivate") is True:
        sensitivity = "private"
    if isinstance(sensitivity, str) and sensitivity.strip():
        metadata["sensitivity"] = sensitivity.strip().lower()
    return ActivityBlock(
        start=start,
        end=end,
        title=title,
        participants=[a for a in attendees if a],
        source=source,
        confidence=confidence,
        metadata=metadata,
    )


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict):  # {"dateTime": "...", "timeZone": "..."}
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Cannot parse datetime from {value!r}")


@lru_cache(maxsize=1)
def get_workiq_client() -> WorkIQClient:
    return WorkIQClient()
