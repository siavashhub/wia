import os, sqlite3, json

db = os.path.expandvars(r"%LOCALAPPDATA%\WIA\WIA\wia.db")
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row

print("--- scan_history (last 8) ---")
for r in c.execute(
    "SELECT ran_at, week_of, trigger, status, entry_count, duration_ms FROM scan_history ORDER BY ran_at DESC LIMIT 8"
):
    print(f"  {r[0]} | week={r[1]} | {r[2]:<9} | {r[3]:<25} | entries={r[4]} | {r[5]}ms")

print("\n--- All May-14 entries for week 2026-05-11 ---")
for r in c.execute(
    "SELECT label, category, duration_hours, daily_hours, confidence, impact FROM time_entry WHERE week_of='2026-05-11'"
):
    try:
        dh = json.loads(r[3] or "{}")
    except Exception:
        dh = {}
    if "2026-05-14" in dh:
        thu = dh.get("2026-05-14", 0)
        print(f"  {r[1]:<12} | {r[2]:>5.2f}h | thu={thu}h | {r[5]:<6} | {r[0][:65]}")

print("\n--- Search for CTC / AVS / ANF / TD-KO in any label across ALL weeks ---")
for r in c.execute(
    "SELECT week_of, label, category FROM time_entry WHERE label LIKE '%CTC%' OR label LIKE '%AVS%' OR label LIKE '%ANF%' OR label LIKE '%TD - KO%' OR label LIKE '%TD-KO%'"
):
    print(f"  week={r[0]} | {r[2]:<12} | {r[1]}")

print("\n--- activity_block rows for week 2026-05-11 ---")
n = c.execute("SELECT COUNT(*) FROM activity_block WHERE week_of='2026-05-11'").fetchone()[0]
print(f"  count={n}")
