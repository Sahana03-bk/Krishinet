# migrations/add_payment_mode.py
import sqlite3, os
DB = os.getenv("KRISHINET_DB", "krishinet.db")
conn = sqlite3.connect(DB)
c = conn.cursor()
try:
    c.execute("ALTER TABLE rental_payments ADD COLUMN mode TEXT DEFAULT 'full'")
    print("Added column rental_payments.mode")
except Exception as e:
    print("Skipped (maybe already present):", e)
conn.commit()
conn.close()
