"""Tests for the Copilot transient-error retry helper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from wia.mcp_clients import workiq as workiq_mod
from wia.mcp_clients.workiq import WorkIQClient, _looks_like_transient_error


def test_looks_like_transient_error_response_none():
    assert _looks_like_transient_error({"response": None, "error": "boom"}) is True


def test_looks_like_transient_error_response_blank():
    assert _looks_like_transient_error({"response": "   ", "error": "boom"}) is True


def test_looks_like_transient_error_with_real_response():
    assert _looks_like_transient_error({"response": "ok", "error": "warn"}) is False


def test_looks_like_transient_error_no_error_key():
    assert _looks_like_transient_error({"response": None}) is False


def test_looks_like_transient_error_non_dict():
    assert _looks_like_transient_error(None) is False
    assert _looks_like_transient_error("oops") is False
    assert _looks_like_transient_error([]) is False


@pytest.mark.asyncio
async def test_call_tool_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(workiq_mod, "_RETRY_BACKOFF_SECONDS", 0.0)

    client = WorkIQClient.__new__(WorkIQClient)
    client._lock = __import__("asyncio").Lock()

    bad = {"response": None, "error": "transient"}
    good = {"response": '{"events": []}'}
    mock = AsyncMock(side_effect=[bad, bad, good])
    with patch.object(WorkIQClient, "_call_tool_once", mock):
        result = await client._call_tool("ask_work_iq", {"question": "x"})
    assert result is good
    assert mock.await_count == 3


@pytest.mark.asyncio
async def test_call_tool_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(workiq_mod, "_RETRY_BACKOFF_SECONDS", 0.0)

    client = WorkIQClient.__new__(WorkIQClient)
    client._lock = __import__("asyncio").Lock()

    bad = {"response": None, "error": "still transient"}
    mock = AsyncMock(return_value=bad)
    with patch.object(WorkIQClient, "_call_tool_once", mock):
        result = await client._call_tool("ask_work_iq", {"question": "x"})
    assert result is bad
    assert mock.await_count == workiq_mod._RETRY_ATTEMPTS
