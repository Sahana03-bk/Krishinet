import sqlite3, os

DB = "users.db"
if not os.path.exists(DB):
    print("ERROR: users.db not found in", os.getcwd())
    exit(1)

con = sqlite3.connect(DB)
cur = con.cursor()

print("=== USERS ===")
for row in cur.execute("SELECT id, name, email FROM users ORDER BY id;"):
    print(row)

print("\n=== FOLLOW rows ===")
for row in cur.execute("SELECT id, follower_id, target_id, datetime(created_at) FROM follow ORDER BY id DESC LIMIT 20;"):
    print(row)

con.close()
