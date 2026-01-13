import sqlite3
DB = "users.db"

SCHEMA = """
PRAGMA foreign_keys = ON;
-- Add Stripe columns if missing (safe: check and add)
"""

def add_column_if_missing(con, table, col_def):
    col = col_def.split()[0]
    cur = con.cursor()
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        print(f"Added {col} to {table}")

if __name__ == "__main__":
    con = sqlite3.connect(DB)
    try:
        add_column_if_missing(con, "orders", "stripe_session_id TEXT")
    except Exception as e:
        print("skipping stripe_session_id:", e)
    try:
        add_column_if_missing(con, "orders", "stripe_payment_id TEXT")
    except Exception as e:
        print("skipping stripe_payment_id:", e)
    try:
        add_column_if_missing(con, "orders", "status TEXT DEFAULT 'created'")
    except Exception as e:
        print("skipping status:", e)
    con.commit()
    con.close()
    print("✅ orders table updated (stripe columns)")
