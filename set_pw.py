# set_pw.py
import sqlite3, os
DB = "users.db"
if not os.path.exists(DB):
    print("users.db not found")
    raise SystemExit(1)
con = sqlite3.connect(DB)
cur = con.cursor()
# change these:
USER_ID = 12
NEW_PW = "testpass123"
cur.execute("UPDATE users SET password = ? WHERE id = ?", (NEW_PW, USER_ID))
con.commit()
con.close()
print(f"Set password for user {USER_ID} -> {NEW_PW}")
