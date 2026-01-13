# stripe_db_upgrade.py
import sqlite3
conn = sqlite3.connect("users.db")
for sql in [
  "ALTER TABLE orders ADD COLUMN gateway TEXT",
  "ALTER TABLE orders ADD COLUMN stripe_session_id TEXT",
  "ALTER TABLE orders ADD COLUMN stripe_payment_intent TEXT"
]:
    try: conn.execute(sql)
    except sqlite3.OperationalError: pass
conn.commit(); conn.close()
print("orders table upgraded for Stripe.")
