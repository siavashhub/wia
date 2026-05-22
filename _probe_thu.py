"""One-shot probe — explains the Thursday Admin / Follow-up balloon."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import platformdirs

db = Path(platformdirs.user_data_dir("WIA", "WIA")) / "wia.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row

# Find the week id that contains 2026-05-21 (Thursday)
week_iso = "2026-05-18"

rows = con.execute(
    "SELECT id, label, category, duration_hours, daily_hours, source_block_ids, "
    "sources, user_edited, manual FROM time_entry WHERE week_of=? ORDER BY duration_hours DESC",
    (week_iso,),
).fetchall()

print(f"=== {week_iso} — all entries (duration desc) ===")
total = 0.0
thu_total = 0.0
for r in rows:
    dh = json.loads(r["daily_hours"] or "{}")
    thu = dh.get("2026-05-21", 0)
    total += r["duration_hours"]
    thu_total += thu
    marker = " <-- THU>2h" if thu >= 2 else ""
    print(
        f"  id={r['id']:>4} {r['category']:<14} | "
        f"{(r['label'] or '')[:60]:<60} | "
        f"total={r['duration_hours']:>5.2f}h thu={thu:>5.2f}h "
        f"edited={r['user_edited']} manual={r['manual']}"
        f"{marker}"
    )

print(f"\nWeek total: {total:.2f}h | Thursday total: {thu_total:.2f}h")

# Focus on Admin/Follow-up specifically
print("\n=== Admin / Follow-up row(s) ===")
for r in rows:
    if (r["label"] or "").lower().endswith("follow-up") or "follow-up" in (r["label"] or "").lower():
        dh = json.loads(r["daily_hours"] or "{}")
        print(f"  id={r['id']} label={r['label']!r} category={r['category']!r}")
        print(f"    total={r['duration_hours']:.2f}h")
        print("    daily_hours:")
        for k in sorted(dh):
            print(f"      {k}: {dh[k]:.2f}h")
        print(f"    source_block_ids={r['source_block_ids'][:200]!r}")
        print(f"    sources={r['sources']!r}")
        print(f"    user_edited={r['user_edited']} manual={r['manual']}")

# Show all blocks on Thursday from the activity_block table (likely empty
# in this build, but checks the assumption).
print("\n=== activity_block rows for week (likely empty) ===")
ab = con.execute(
    "SELECT COUNT(*), MIN(start), MAX(start) FROM activity_block WHERE week_of=?",
    (week_iso,),
).fetchone()
print(f"  count={ab[0]} min_start={ab[1]} max_start={ab[2]}")
