"""Scan history repository."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import desc, select

from wia.storage.db import get_session
from wia.storage.models import ScanHistoryRow

# Cap rows so the history table cannot grow unbounded across years of use.
MAX_ROWS = 500


def record(
    *,
    ran_at: datetime,
    week_of: str,
    trigger: str,
    status: str,
    entry_count: int = 0,
    duration_ms: int = 0,
) -> ScanHistoryRow:
    with get_session() as session:
        row = ScanHistoryRow(
            ran_at=ran_at,
            week_of=week_of,
            trigger=trigger,
            status=status,
            entry_count=entry_count,
            duration_ms=duration_ms,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        # Trim oldest rows beyond the retention cap.
        ids = session.exec(select(ScanHistoryRow.id).order_by(desc(ScanHistoryRow.ran_at))).all()
        if len(ids) > MAX_ROWS:
            for old in ids[MAX_ROWS:]:
                stale = session.get(ScanHistoryRow, old)
                if stale is not None:
                    session.delete(stale)
            session.commit()
        return row


def list_recent(limit: int = 50) -> list[ScanHistoryRow]:
    with get_session() as session:
        rows = session.exec(
            select(ScanHistoryRow).order_by(desc(ScanHistoryRow.ran_at)).limit(limit)
        ).all()
        return list(rows)


def latest() -> ScanHistoryRow | None:
    with get_session() as session:
        return session.exec(
            select(ScanHistoryRow).order_by(desc(ScanHistoryRow.ran_at)).limit(1)
        ).first()


def delete_for_week(week_of: str) -> int:
    """Remove all scan-history rows for ``week_of``. Returns the count."""
    with get_session() as session:
        rows = session.exec(select(ScanHistoryRow).where(ScanHistoryRow.week_of == week_of)).all()
        count = len(rows)
        for row in rows:
            session.delete(row)
        session.commit()
        return count
