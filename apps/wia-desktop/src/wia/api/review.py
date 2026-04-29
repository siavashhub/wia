"""Review endpoints — monthly / annual aggregation over saved entries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from wia.core import review as review_core
from wia.core.types import Review

router = APIRouter()


@router.get("")
async def get_review(period: str) -> Review:
    """Return a Review for ``period`` (``YYYY-MM`` or ``YYYY``)."""
    try:
        kind, year, month = review_core.parse_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if kind == "month":
        assert month is not None
        return review_core.build_monthly_review(year, month)
    return review_core.build_yearly_review(year)
