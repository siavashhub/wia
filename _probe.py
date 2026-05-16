"""Probe Work IQ directly for May 14, 2026 calendar events."""

import asyncio, json, logging
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main():
    from wia.mcp_clients.workiq import get_workiq_client

    client = get_workiq_client()
    # Narrow window: just Thursday May 14.
    blocks = await client.fetch_calendar_blocks(date(2026, 5, 14), date(2026, 5, 14))
    print(f"\nReturned {len(blocks)} calendar blocks for 2026-05-14:")
    for b in blocks:
        cats = b.metadata.get("categories_display", "")
        sens = b.metadata.get("sensitivity", "")
        print(f"  {b.start.isoformat()} -> {b.end.isoformat()}")
        print(f"    title={b.title!r}")
        print(f"    participants={b.participants}")
        print(f"    categories={cats!r}  sensitivity={sens!r}")
    # Also try the raw tool call so we see what Copilot returned verbatim.
    print("\n--- Raw ask_work_iq response for May 14 ---")
    prompt = (
        "List EVERY event on my calendar on 2026-05-14, including events with "
        "no attendees, all-day blocks, personal time-blocks I created on my "
        "own calendar, and events tagged with Outlook categories like 'Customer'. "
        'Return ONLY JSON: {"events":[{"title":"...","start":"ISO","end":"ISO",'
        '"participants":[],"categories":[]}]}'
    )
    raw = await client._call_tool("ask_work_iq", {"question": prompt})
    print(json.dumps(raw, indent=2, default=str)[:4000])


asyncio.run(main())
