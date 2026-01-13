# migrate_payments.py
import os, json, sqlite3
DB = os.getenv("KRISHINET_DB", "users.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1) Ensure missing statuses default
c.execute("UPDATE orders SET status = 'created' WHERE status IS NULL OR status = ''")
conn.commit()

# 2) For orders marked 'paid' but missing payments, create payments rows
rows = c.execute("SELECT id, total_amount, currency, gateway, stripe_payment_intent, payment_meta FROM orders WHERE status = 'paid'").fetchall()
for r in rows:
    order_id = r["id"]
    already = c.execute("SELECT 1 FROM payments WHERE order_id = ?", (order_id,)).fetchone()
    if already:
        continue
    amount = r["total_amount"] or 0.0
    currency = r["currency"] or "INR"
    gateway = r["gateway"] or "stripe"
    pi = r["stripe_payment_intent"] or ""
    raw = r["payment_meta"] or ""
    c.execute("INSERT INTO payments (order_id, amount, currency, gateway, payment_intent, raw_meta) VALUES (?, ?, ?, ?, ?, ?)",
              (order_id, amount, currency, gateway, pi, raw))
    print("Inserted payment for order", order_id)

conn.commit()
conn.close()
print("Migration complete.")
