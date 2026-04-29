from datetime import UTC, date
from unittest.mock import AsyncMock, patch

import pytest
from wia.core.orchestrator import build_briefing
from wia.core.types import ActivityBlock, Confidence, Source
from wia.storage.db import init_db


@pytest.fixture(autouse=True)
def _db():
    init_db()


@pytest.mark.asyncio
async def test_build_briefing_with_mocked_workiq():
    from datetime import datetime

    fake_blocks = [
        ActivityBlock(
            start=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
            end=datetime(2026, 4, 20, 11, 0, tzinfo=UTC),
            title="Sprint planning",
            participants=["a@contoso.com"],
            source=Source.CALENDAR,
            confidence=Confidence.HIGH,
        )
    ]

    with patch("wia.core.orchestrator.get_workiq_client") as mock_get:
        client = AsyncMock()
        client.fetch_calendar_blocks = AsyncMock(return_value=fake_blocks)
        mock_get.return_value = client

        briefing = await build_briefing(week_of=date(2026, 4, 22), refresh=True)

    assert briefing.status == "ok"
    assert briefing.week_start == "2026-04-20"
    assert briefing.totals.total_hours > 0
    assert any("Sprint planning" in e.label for e in briefing.entries)
