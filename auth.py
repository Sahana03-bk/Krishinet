# auth.py
import sqlite3
from functools import wraps
from flask import g, session, redirect, url_for, flash, current_app

def get_db():
    """Return sqlite3 connection attached to flask.g using current_app config."""
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db

def login_required(view):
    """Simple decorator to require login (redirects to /login)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped
