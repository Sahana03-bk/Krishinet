# migrate_add_raw_meta.py
import sqlite3
import os
from pathlib import Path

DB = os.getenv("KRISHINET_DB", "users.db")
DB_PATH = os.path.join(os.path.dirname(__file__), DB) if not os.path.isabs(DB) else DB

def table_has_column(conn, table, column):
    cur = conn.execute(f"PRAGMA table_info({table});")
    cols = [r[1] for r in cur.fetchall()]
    return column in cols

def main():
    print("DB path:", DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        if not table_has_column(conn, "rental_payments", "raw_meta"):
            print("Adding column 'raw_meta' to rental_payments ...")
            conn.execute("ALTER TABLE rental_payments ADD COLUMN raw_meta TEXT DEFAULT '{}';")
            conn.commit()
            print("Column added.")
        else:
            print("Column 'raw_meta' already exists. Nothing to do.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
