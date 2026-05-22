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
import re
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

# Microsoft 365 Copilot is non-deterministic and intermittently returns
# ``{"response": null, "error": "..."}`` for ``ask_work_iq`` — usually
# transient capacity / routing failures. Retry a couple of times with
# linear backoff before giving up so an unlucky scan doesn't wipe out
# good data from the previous run.
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0


@dataclass
class WorkIQStatus:
    installed: bool
    ready: bool
    version: str | None = None
    message: str | None = None


@dataclass
class WorkIQIdentity:
    """The signed-in M365 user behind the Work IQ CLI."""

    upn: str
    display_name: str | None = None
    tenant_name: str | None = None
    source: str = "ask_work_iq"  # which MCP tool produced this


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
        """Call an MCP tool, retrying transient Copilot errors.

        Microsoft 365 Copilot intermittently returns
        ``{"response": null, "error": "..."}`` for ``ask_work_iq``. We
        retry up to :data:`_RETRY_ATTEMPTS` times with linear backoff
        before surfacing the failure. The final (failed) payload is
        returned so :func:`_extract_events` can log it.
        """
        last_payload: Any = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            payload = await self._call_tool_once(name, arguments)
            if not _looks_like_transient_error(payload):
                return payload
            last_payload = payload
            if attempt < _RETRY_ATTEMPTS:
                err = ""
                if isinstance(payload, dict):
                    err = str(payload.get("error") or "")[:160]
                log.info(
                    "Work IQ %s returned a transient error (attempt %d/%d): %s",
                    name,
                    attempt,
                    _RETRY_ATTEMPTS,
                    err or "<no message>",
                )
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        log.warning(
            "Work IQ %s failed after %d attempts; returning last payload",
            name,
            _RETRY_ATTEMPTS,
        )
        return last_payload

    async def _call_tool_once(self, name: str, arguments: dict[str, Any]) -> Any:
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

    async def _list_tool_names(self) -> list[str]:
        """Return the names of every tool the Work IQ MCP server exposes.

        Used once at identity-discovery time so we can prefer a typed
        ``me`` / ``whoami`` tool over the natural-language ``ask_work_iq``
        when the server provides one. Failures are non-fatal — we just
        return an empty list and the caller falls back.
        """
        try:
            async with (
                self._lock,
                stdio_client(self._params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
        except Exception as exc:
            log.debug("Work IQ list_tools failed: %r", exc)
            return []
        names: list[str] = []
        for t in getattr(listed, "tools", []) or []:
            n = getattr(t, "name", None)
            if isinstance(n, str) and n:
                names.append(n)
        return names

    async def fetch_user_identity(self) -> WorkIQIdentity | None:
        """Return the signed-in user's UPN / display name / tenant.

        Strategy:

        1. Probe ``list_tools`` once. If the server exposes a typed
           identity tool (``me``, ``whoami``, ``identity``, ``user.get``,
           etc.), call it directly — fewer round-trips, no LLM in the
           loop.
        2. Otherwise, fall back to ``ask_work_iq`` with a tight whoami
           prompt that asks Microsoft 365 Copilot for its own signed-in
           account. The prompt requests strict JSON so we can parse it.

        Returns ``None`` when both paths fail (e.g. CLI not signed in).
        Callers should treat absence as a soft signal — never block a
        user flow on this.
        """
        # 1. Try a typed identity tool if one is advertised.
        candidates = ("me", "whoami", "identity", "user.get", "user_info", "userInfo")
        try:
            available = await self._list_tool_names()
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("list_tools probe raised: %r", exc)
            available = []
        chosen = next((c for c in candidates if c in available), None)
        if chosen:
            try:
                payload = await self._call_tool(chosen, {})
            except Exception as exc:
                log.warning("Work IQ %s tool failed: %r", chosen, exc)
            else:
                ident = _identity_from_payload(payload, source=chosen)
                if ident:
                    return ident

        # 2. Fall back to ask_work_iq with a strict whoami prompt.
        prompt = (
            "Who am I? Return ONLY a JSON object, no prose, no markdown fences, "
            'in this exact shape: {"upn":"<my user principal name>",'
            '"displayName":"<my full name>","tenantName":"<my organization name>"}. '
            "Use my actual signed-in Microsoft 365 account. "
            "If any field is unknown, return an empty string for it."
        )
        try:
            payload = await self._call_tool("ask_work_iq", {"question": prompt})
        except Exception as exc:
            log.warning("Work IQ whoami fetch failed: %r", exc)
            return None
        return _identity_from_payload(payload, source="ask_work_iq")

    async def fetch_calendar_blocks(self, start: date, end: date) -> list[ActivityBlock]:
        """Fetch every calendar event between [start, end] inclusive.

        Microsoft 365 Copilot's ``ask_work_iq`` is non-deterministic and
        \u2014 even with explicit instructions \u2014 frequently drops
        appointment-style events that have no attendees (or only the user
        as the sole attendee). To make sure those still show up in the
        briefing we issue **two** queries per fetch and union the
        results:

        1. The general "every event in the range" query.
        2. A narrow follow-up specifically for appointments / self-only
           blocks / focus time / personal reminders.

        Events that appear in both responses are deduplicated by
        ``(start, normalised-title)``. When two payloads describe the
        same event we keep the one whose Outlook ``categories`` /
        ``categories_display`` is populated so the user's pinned
        category isn't lost.
        """
        general_prompt = (
            f"List every event on my calendar between {start.isoformat()} 00:00 "
            f"and {end.isoformat()} 23:59 (inclusive of both endpoints). "
            "Include past, current, and future events. Include accepted, "
            "tentative, and organizer events. Include all-day events and "
            "every occurrence of recurring events whose instance falls in "
            "this range. Do NOT exclude future events or events I have "
            "not yet attended. "
            "IMPORTANT: Also include events that have NO attendees \u2014 these are "
            "personal time-blocks, focus blocks, reminders, and self-organised "
            "appointments I put on my own calendar. Return them with "
            "participants:[] (empty array). Do NOT skip them just because "
            "they have no invitees. "
            "Return ONLY a JSON object, no prose, no markdown fences, in this exact shape: "
            '{"events":[{"title":"...","start":"ISO8601","end":"ISO8601",'
            '"organizer":"email","participants":["email"],"isOnline":true,'
            '"categories":["<outlook category name>"],"sensitivity":"normal|personal|private|confidential",'
            '"isPrivate":true,'
            '"responseStatus":"accepted|tentative|declined|notResponded|organizer",'
            '"isOptional":false,"attendeeCount":0}]}. '
            "Always include the event's Outlook categories array (use [] if none). "
            "Always include the sensitivity field \u2014 it is one of normal, personal, "
            "private, or confidential. If the event is marked Private in Outlook, "
            "set sensitivity to 'private' AND set isPrivate to true. Do not omit "
            "sensitivity even if the value is 'normal'. "
            "ALWAYS include responseStatus for each event \u2014 my own response to the "
            "invitation, one of: 'accepted', 'tentative', 'declined', 'notResponded', "
            "or 'organizer' when I am the organizer. ALWAYS include isOptional (true "
            "if I was invited as an Optional attendee, false otherwise) and "
            "attendeeCount (the total number of invitees including required and "
            "optional, including me; use 0 for appointment-style events with no invitees). "
            "Use ISO 8601 timestamps with timezone offsets. "
            'If there are no events, return {"events":[]}.'
        )
        # Narrow follow-up: forces Copilot to look specifically at the
        # appointment-style entries it tends to drop from the general
        # answer. Same JSON shape so ``_extract_events`` parses both.
        self_only_prompt = (
            f"List every calendar entry on my own calendar between "
            f"{start.isoformat()} 00:00 and {end.isoformat()} 23:59 that has "
            "either NO other attendees, only me as the attendee, or is an "
            "Outlook 'appointment' (not a meeting). Include focus time, "
            "reminders, blocked personal time, and any self-organised "
            "appointment I created without inviting anyone. Include events "
            "where I am the only required attendee. Do NOT filter these out "
            "as 'not meetings' \u2014 they are valid calendar entries I want "
            "to see. "
            "Return ONLY a JSON object, no prose, no markdown fences, in this exact shape: "
            '{"events":[{"title":"...","start":"ISO8601","end":"ISO8601",'
            '"organizer":"email","participants":["email"],"isOnline":false,'
            '"categories":["<outlook category name>"],"sensitivity":"normal|personal|private|confidential",'
            '"isPrivate":true,'
            '"responseStatus":"accepted|tentative|declined|notResponded|organizer",'
            '"isOptional":false,"attendeeCount":0}]}. '
            "Always include the event's Outlook categories array (use [] if none). "
            "ALWAYS include responseStatus (for self-only appointments use 'organizer'), "
            "isOptional (false for self-only), and attendeeCount (0 for events with no "
            "other invitees). "
            "Use ISO 8601 timestamps with timezone offsets. "
            'If there are none, return {"events":[]}.'
        )

        general_events = await self._ask_for_events(general_prompt, label="general")
        self_only_events = await self._ask_for_events(self_only_prompt, label="self-only")

        merged = _merge_event_payloads(general_events, self_only_events)

        blocks: list[ActivityBlock] = []
        for ev in merged:
            try:
                blocks.append(_event_to_block(ev, source=Source.CALENDAR))
            except Exception as exc:
                log.debug("Skipping malformed event %s: %s", ev, exc)
        no_attendee = sum(1 for b in blocks if not b.participants)
        log.info(
            "Work IQ returned %d calendar events for %s..%s "
            "(general=%d, self-only=%d, %d with no attendees)",
            len(blocks),
            start,
            end,
            len(general_events),
            len(self_only_events),
            no_attendee,
        )
        return blocks

    async def _ask_for_events(self, prompt: str, *, label: str) -> list[dict[str, Any]]:
        """Run ``ask_work_iq`` and return the parsed events, swallowing failure.

        A failure in one of the two calendar queries should not abort the
        whole scan \u2014 we still want the other query's events. Errors
        are logged at WARNING.
        """
        try:
            payload = await self._call_tool("ask_work_iq", {"question": prompt})
        except Exception as exc:
            log.warning("Work IQ ask_work_iq (%s) failed: %r", label, exc, exc_info=True)
            return []
        return _extract_events(payload)

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
            "Also return whether I actively contributed: set "
            '"iParticipated" to true if I sent at least one message, '
            "posted a reaction, or joined the call audio/video; false "
            "when I only viewed / scrolled the thread. Include "
            '"messagesFromMe" (integer count of messages I sent in this '
            'thread during the window) and "messagesTotal" (integer total '
            "messages in the thread during the window) whenever you can. "
            "Return ONLY a JSON object, no prose, no markdown fences, in this exact shape: "
            '{"events":[{"title":"<short topic>","start":"ISO8601","end":"ISO8601",'
            '"participants":["email"],"iParticipated":true,"messagesFromMe":0,'
            '"messagesTotal":0}]}. '
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


def _identity_from_payload(payload: Any, *, source: str) -> WorkIQIdentity | None:
    """Parse an identity dict out of a Work IQ tool response.

    Accepts either a direct dict, a ``{"response": "<json>"}`` envelope
    (the ``ask_work_iq`` shape), or a JSON string with optional ```json
    fences. Returns ``None`` when no UPN-shaped string is found.
    """
    obj = _coerce_identity(payload)
    if not obj:
        return None
    upn = _pick_upn(obj)
    if not upn:
        return None
    display = _pick_str(obj, ("displayName", "display_name", "name"))
    tenant = _pick_str(obj, ("tenantName", "tenant_name", "organization", "org"))
    return WorkIQIdentity(
        upn=upn.strip(),
        display_name=display.strip() if display else None,
        tenant_name=tenant.strip() if tenant else None,
        source=source,
    )


def _coerce_identity(value: Any) -> dict[str, Any] | None:
    """Pull a plain dict out of nested envelopes / JSON strings."""
    if value is None:
        return None
    if isinstance(value, dict):
        # ask_work_iq wraps the real payload as a JSON string under "response".
        if "response" in value and not any(
            k in value for k in ("upn", "userPrincipalName", "mail", "email")
        ):
            return _coerce_identity(value["response"])
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return _coerce_identity(parsed)
    return None


def _pick_upn(obj: dict[str, Any]) -> str:
    """Return the first email-shaped value found among the common UPN keys."""
    for key in ("upn", "userPrincipalName", "mail", "email", "preferred_username"):
        v = obj.get(key)
        if isinstance(v, str) and "@" in v:
            return v
    return ""


def _pick_str(obj: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _looks_like_transient_error(payload: Any) -> bool:
    """Return ``True`` for Copilot's ``{response: null, error: "..."}`` envelope.

    Used by :meth:`WorkIQClient._call_tool` to decide whether to retry.
    A payload counts as transient when it carries an ``error`` field AND
    its ``response`` is missing / null / empty.
    """
    if not isinstance(payload, dict):
        return False
    if "error" not in payload:
        return False
    resp = payload.get("response")
    if resp is None:
        return True
    return isinstance(resp, str) and not resp.strip()


def _event_dedup_key(ev: dict[str, Any]) -> tuple[str, str]:
    """Stable key for deduplicating events across the two calendar queries.

    We key on ``(start, normalised-title)`` because Copilot occasionally
    reformats whitespace / casing in titles between calls but never the
    start timestamp.
    """
    start = str(ev.get("start") or "").strip()
    title = str(ev.get("title") or "").strip().lower()
    title = " ".join(title.split())
    return (start, title)


def _has_categories(ev: dict[str, Any]) -> bool:
    """True when this event payload carries Outlook categories.

    Used by the merge to pick the "richer" copy when both calendar
    queries returned the same event \u2014 the response that retained
    ``categories`` is the one whose category pinning we want to keep.
    """
    cats = ev.get("categories")
    if isinstance(cats, list) and any(isinstance(c, str) and c.strip() for c in cats):
        return True
    display = ev.get("categories_display") or ev.get("categoriesDisplay")
    return bool(isinstance(display, str) and display.strip())


def _merge_event_payloads(
    primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union two ``ask_work_iq`` event lists, keeping the richer copy on overlap.

    ``primary`` events come first in the output; events from
    ``secondary`` that aren't already keyed in ``primary`` are appended.
    When both lists describe the same event (same dedup key) we keep the
    one with populated Outlook categories so a category-stripped copy
    can't shadow a category-bearing one.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for ev in primary:
        if not isinstance(ev, dict):
            continue
        key = _event_dedup_key(ev)
        merged[key] = ev
        order.append(key)
    for ev in secondary:
        if not isinstance(ev, dict):
            continue
        key = _event_dedup_key(ev)
        existing = merged.get(key)
        if existing is None:
            merged[key] = ev
            order.append(key)
        elif _has_categories(ev) and not _has_categories(existing):
            merged[key] = ev
    return [merged[k] for k in order]


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


# --- Title normalisation ---------------------------------------------------
#
# Work IQ frequently rewrites the title of recurring Teams chats and email
# threads with a per-day parenthetical summary (e.g. ``O.U.C.H. group chat
# (Clawpilot discussion)`` on Mon, ``O.U.C.H. group chat (dashboard +
# permissions)`` on Tue), so the same conversation lands under four
# different ``(label, category)`` aggregator keys across a week. The
# aggregator already builds a per-day ``daily_hours`` dict, so we just need
# the per-day titles to collapse to a stable stem. Calendar workshops show
# a similar pattern with date/option suffixes (``... Workshop VBD| 18 May
# 8am - Wkshop 3``).
#
# Both helpers preserve the *original* title via ``metadata["original_title"]``
# so downstream consumers (e.g. the Briefing UI's "evidence" tooltip) can
# still see what Work IQ actually returned.

_CHAT_TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")
_CALENDAR_PIPE_SUFFIX_RE = re.compile(r"\s*\|\s*[^|]*\d[^|]*$")
_CALENDAR_EMPTY_PIPE_RE = re.compile(r"\s*\|\s*$")
_CALENDAR_WKSHOP_SUFFIX_RE = re.compile(
    r"\s*-\s*(?:option|wkshop|workshop|session)\s+\d+\s*$",
    re.IGNORECASE,
)


def _normalize_chat_title(title: str) -> str:
    """Strip a trailing parenthetical from a Teams / Email block title.

    Collapses e.g. ``"O.U.C.H. group chat (Clawpilot discussion)"`` to
    ``"O.U.C.H. group chat"`` so per-day Work IQ summaries of the same
    conversation aggregate into a single :class:`TimeEntry` row. We
    deliberately only strip ONE trailing group — nested or mid-string
    parens are left alone (e.g. ``"Chat with Abe (sub) about X"`` keeps
    its inner ``(sub)``).
    """
    if not title:
        return title
    stripped = _CHAT_TRAILING_PAREN_RE.sub("", title).rstrip()
    return stripped or title


def _normalize_calendar_title(title: str) -> str:
    """Strip recurring-event suffixes from a Calendar block title.

    Targets two patterns observed in real Work IQ output that cause
    the same workshop / training event to spawn one row per occurrence:

    - ``"... Workshop VBD| 18 May 8am - Wkshop 3"`` — date/time pipe
      segment containing a digit.
    - ``"... Workshop - option 2"`` / ``"... - session 1"``.

    Pipe-stripping is iterative so multi-segment titles like
    ``"A | 18 MAY 2026 | 8am - 9am | - option 1"`` collapse fully to
    ``"A"``. Returns the original title unchanged when nothing matched.
    """
    if not title:
        return title
    out = title
    for _ in range(8):  # bounded; protects against pathological input
        new = _CALENDAR_WKSHOP_SUFFIX_RE.sub("", out)
        new = _CALENDAR_PIPE_SUFFIX_RE.sub("", new)
        new = _CALENDAR_EMPTY_PIPE_RE.sub("", new)
        new = new.rstrip()
        if new == out or not new:
            break
        out = new
    return out or title


def _event_to_block(
    ev: dict[str, Any],
    *,
    source: Source = Source.CALENDAR,
    confidence: Confidence = Confidence.HIGH,
) -> ActivityBlock:
    start = _parse_dt(ev.get("start") or ev.get("startTime"))
    end = _parse_dt(ev.get("end") or ev.get("endTime"))
    raw_title = ev.get("subject") or ev.get("title")
    # Source-aware title normalisation: collapse per-day chat summaries
    # and recurring-workshop date suffixes so the aggregator can merge
    # what is conceptually the same conversation / event.
    if isinstance(raw_title, str) and raw_title.strip():
        if source in (Source.TEAMS, Source.EMAIL):
            title = _normalize_chat_title(raw_title)
        elif source is Source.CALENDAR:
            title = _normalize_calendar_title(raw_title)
        else:
            title = raw_title
    else:
        title = raw_title
    attendees = ev.get("attendees") or ev.get("participants") or []
    if attendees and isinstance(attendees[0], dict):
        attendees = [a.get("email") or a.get("address") or "" for a in attendees]
    metadata: dict[str, str] = {"id": str(ev.get("id", ""))}
    # Preserve the un-normalised title so the UI can still display what
    # Work IQ actually said, and so a future debugger can see the input.
    if isinstance(raw_title, str) and isinstance(title, str) and raw_title != title:
        metadata["original_title"] = raw_title
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
    is_private_flag = ev.get("isPrivate") is True or ev.get("is_private") is True
    if not sensitivity and is_private_flag:
        sensitivity = "private"
    if isinstance(sensitivity, str) and sensitivity.strip():
        metadata["sensitivity"] = sensitivity.strip().lower()
    if is_private_flag:
        metadata["is_private"] = "true"
    # Calendar-only attendance metadata. Drives the orchestrator's ingest-
    # time filters for "meetings I didn't attend" (declined / no-response /
    # optional + large). Stored only when present — missing keys signal
    # "unknown" to the filter so it can apply its configured default.
    response_raw = ev.get("responseStatus") or ev.get("response_status")
    if isinstance(response_raw, str) and response_raw.strip():
        # Normalise camelCase / spacing into a small fixed vocabulary.
        normalised = response_raw.strip().lower().replace(" ", "").replace("_", "")
        alias = {
            "tentativelyaccepted": "tentative",
            "none": "notresponded",
            "noresponse": "notresponded",
            "awaitingresponse": "notresponded",
            "organiser": "organizer",
        }
        metadata["response_status"] = alias.get(normalised, normalised)
    is_optional = ev.get("isOptional")
    if is_optional is None:
        is_optional = ev.get("is_optional")
    if is_optional is True:
        metadata["is_optional"] = "true"
    elif is_optional is False:
        metadata["is_optional"] = "false"
    attendee_count = ev.get("attendeeCount")
    if attendee_count is None:
        attendee_count = ev.get("attendee_count")
    if isinstance(attendee_count, int) and attendee_count >= 0:
        metadata["attendee_count"] = str(attendee_count)
    # Teams-only participation metadata. Drives the orchestrator's
    # "drop passive Teams threads" filter — a channel-style thread the
    # user only scrolled past should not eat into their week. Missing
    # keys signal "unknown" to the filter so it keeps the block.
    i_participated = ev.get("iParticipated")
    if i_participated is None:
        i_participated = ev.get("i_participated")
    if i_participated is True:
        metadata["i_participated"] = "true"
    elif i_participated is False:
        metadata["i_participated"] = "false"
    messages_from_me = ev.get("messagesFromMe")
    if messages_from_me is None:
        messages_from_me = ev.get("messages_from_me")
    if isinstance(messages_from_me, int) and messages_from_me >= 0:
        metadata["messages_from_me"] = str(messages_from_me)
    messages_total = ev.get("messagesTotal")
    if messages_total is None:
        messages_total = ev.get("messages_total")
    if isinstance(messages_total, int) and messages_total >= 0:
        metadata["messages_total"] = str(messages_total)
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
