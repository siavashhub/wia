"""Tests for the in-app update check."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import wia.core.updates as updates_mod
from wia.core.updates import UpdateInfo, _parse_semver, check_for_updates

# ---------------------------------------------------------------------------
# _parse_semver
# ---------------------------------------------------------------------------


def test_parse_semver_plain():
    assert _parse_semver("1.2.3") == (1, 2, 3)


def test_parse_semver_with_v_prefix():
    assert _parse_semver("v1.2.3") == (1, 2, 3)


def test_parse_semver_invalid_returns_none():
    assert _parse_semver("not-a-version") is None


def test_parse_semver_empty_returns_none():
    assert _parse_semver("") is None


def test_parse_semver_prerelease_extracts_base():
    # Pre-release suffix shouldn't crash; we only care about the numeric part.
    assert _parse_semver("v1.2.3-rc1") == (1, 2, 3)


# ---------------------------------------------------------------------------
# check_for_updates — cache behaviour
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache before every test."""
    updates_mod._cache = None
    yield
    updates_mod._cache = None


def _mock_response(tag: str = "v99.0.0", html_url: str = "https://github.com/siavashhub/wia/releases/tag/v99.0.0") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"tag_name": tag, "html_url": html_url}
    return resp


@pytest.mark.asyncio
async def test_update_available_when_remote_is_newer():
    fake_resp = _mock_response(tag="v99.0.0")

    async def _fake_get(*args, **kwargs):
        return fake_resp

    with patch("wia.core.updates.__version__", "0.1.0"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_for_updates(force=True)

    assert result.update_available is True
    assert result.latest_version == "99.0.0"
    assert result.release_url == "https://github.com/siavashhub/wia/releases/tag/v99.0.0"


@pytest.mark.asyncio
async def test_no_update_when_versions_equal():
    fake_resp = _mock_response(tag="v0.1.0")

    with patch("wia.core.updates.__version__", "0.1.0"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_for_updates(force=True)

    assert result.update_available is False


@pytest.mark.asyncio
async def test_no_update_when_local_is_newer():
    fake_resp = _mock_response(tag="v0.1.0")

    with patch("wia.core.updates.__version__", "1.0.0"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_for_updates(force=True)

    assert result.update_available is False


@pytest.mark.asyncio
async def test_network_error_returns_graceful_result():
    with patch("wia.core.updates.__version__", "0.1.0"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await check_for_updates(force=True)

    assert result.update_available is False
    assert result.latest_version is None
    assert result.release_url is None


@pytest.mark.asyncio
async def test_cache_is_used_on_second_call():
    fake_resp = _mock_response(tag="v99.0.0")

    with patch("wia.core.updates.__version__", "0.1.0"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        first = await check_for_updates(force=True)
        second = await check_for_updates()  # should use cache

    assert mock_client.get.call_count == 1
    assert first.latest_version == second.latest_version


@pytest.mark.asyncio
async def test_force_bypasses_cache():
    fake_resp = _mock_response(tag="v99.0.0")

    with patch("wia.core.updates.__version__", "0.1.0"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await check_for_updates(force=True)
        await check_for_updates(force=True)

    assert mock_client.get.call_count == 2


# ---------------------------------------------------------------------------
# API endpoint integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_endpoint_returns_update_info():
    from fastapi.testclient import TestClient
    from wia.app import create_app
    from wia.storage.db import init_db

    init_db()
    app = create_app()

    cached = UpdateInfo(
        current_version="0.1.0",
        latest_version="99.0.0",
        update_available=True,
        release_url="https://github.com/siavashhub/wia/releases/tag/v99.0.0",
    )

    with patch("wia.api.updates.check_for_updates", new=AsyncMock(return_value=cached)), TestClient(app) as client:
        r = client.get("/api/updates/check")

    assert r.status_code == 200
    body = r.json()
    assert body["update_available"] is True
    assert body["latest_version"] == "99.0.0"
    assert body["current_version"] == "0.1.0"


@pytest.mark.asyncio
async def test_api_endpoint_force_param():
    from fastapi.testclient import TestClient
    from wia.app import create_app
    from wia.storage.db import init_db

    init_db()
    app = create_app()

    cached = UpdateInfo(
        current_version="0.1.0",
        latest_version=None,
        update_available=False,
        release_url=None,
    )

    mock_check = AsyncMock(return_value=cached)
    with patch("wia.api.updates.check_for_updates", new=mock_check), TestClient(app) as client:
        client.get("/api/updates/check?force=true")

    mock_check.assert_awaited_once_with(force=True)
