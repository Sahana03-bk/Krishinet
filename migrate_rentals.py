# migrate_rentals.py
"""
Run once to create the new tables the rental module needs.
It is non-destructive (creates new tables / columns only).
"""

import sqlite3
import os

DB = os.getenv("KRISHINET_DB", "krishinet.db")  # change to your DB path if needed

con = sqlite3.connect(DB)
cur = con.cursor()

# Helper to execute safely
def safe(sql):
    try:
        cur.execute(sql)
        print("OK:", sql.splitlines()[0][:60])
    except Exception as e:
        print("Skipped:", e)

# rentals table
safe("""
CREATE TABLE IF NOT EXISTS rentals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  category TEXT,
  price_per_day REAL DEFAULT 0,
  deposit REAL DEFAULT 0,
  condition TEXT,
  location TEXT,
  latitude REAL,
  longitude REAL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# rental media
safe("""
CREATE TABLE IF NOT EXISTS rental_media (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rental_id INTEGER NOT NULL,
  filename TEXT,
  media_type TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# rental requests
safe("""
CREATE TABLE IF NOT EXISTS rental_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rental_id INTEGER NOT NULL,
  requester_id INTEGER NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  requested_days INTEGER NOT NULL,
  price_offered REAL,
  status TEXT DEFAULT 'requested', -- requested / accepted / paid / rejected / cancelled / completed
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  accepted_at TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# unavailabilities
safe("""
CREATE TABLE IF NOT EXISTS rental_unavailabilities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rental_id INTEGER NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  reason TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# reviews (optional)
safe("""
CREATE TABLE IF NOT EXISTS rental_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rental_id INTEGER NOT NULL,
  reviewer_id INTEGER NOT NULL,
  rating INTEGER NOT NULL,
  comment TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# payments (optional - works offline if you don't use Stripe)
safe("""
CREATE TABLE IF NOT EXISTS rental_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id INTEGER NOT NULL,
  payer_id INTEGER NOT NULL,
  amount REAL NOT NULL,
  currency TEXT DEFAULT 'INR',
  method TEXT,
  status TEXT DEFAULT 'pending', -- pending/completed/refunded
  external_id TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# notifications table (if you already have a notifications table this will be ignored)
safe("""
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  actor_id INTEGER,
  verb TEXT,
  payload TEXT,
  is_read INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

con.commit()
con.close()
print("Migration finished. DB:", DB)
