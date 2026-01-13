import sqlite3, os

db_path = os.path.join(os.path.dirname(__file__), "users.db")
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON;")

try:
    conn.execute("ALTER TABLE rental_payments ADD COLUMN mode TEXT DEFAULT 'full';")
    conn.commit()
    print("✅ Added rental_payments.mode column successfully.")
except Exception as e:
    print("⚠️ Could not add column (maybe already exists):", e)

conn.close()
