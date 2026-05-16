"""Run a fresh briefing through the NEW pipeline and dump May 14 entries."""

import asyncio, logging
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main():
    from wia.core.orchestrator import build_briefing

    b = await build_briefing(week_of=date(2026, 5, 14), refresh=True)
    print(f"\nBriefing status={b.status}, entries={len(b.entries)}")
    print(f"\nAll Thursday (2026-05-14) entries:")
    for e in b.entries:
        thu = (e.daily_hours or {}).get("2026-05-14", 0)
        if thu > 0:
            print(
                f"  {e.category:<12} | {e.duration_hours:>5.2f}h | thu={thu}h | {e.impact:<6} | {e.label[:80]}"
            )
    print(f"\nSearch for Contoso/ Fabrikamacross full week:")
    for e in b.entries:
        if "Contoso" in (e.label or "") or "Fabrikam- KO" in (e.label or ""):
            print(f"  FOUND: {e.category} | {e.impact} | {e.label} | {e.daily_hours}")


asyncio.run(main())
