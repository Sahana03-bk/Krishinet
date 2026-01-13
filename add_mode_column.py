# add_mode_column.py  (run once in your project root)
import sqlite3, os
DB = os.getenv("KRISHINET_DB", "users.db")
conn = sqlite3.connect(DB)
cur = conn.cursor()
try:
    cur.execute("ALTER TABLE rental_payments ADD COLUMN mode TEXT DEFAULT 'full'")
    conn.commit()
    print("Column 'mode' added to rental_payments.")
except Exception as e:
    print("Skipped (maybe already exists):", e)
conn.close()
