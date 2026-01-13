# routes_profile.py
import json
import calendar
from io import BytesIO
from datetime import datetime
from flask import Blueprint, render_template, request, session, current_app, abort, send_file, jsonify, url_for

# import get_db/login_required with fallback to avoid circular imports
# Prefer auth.py so we don't import app at module-import time (avoids circular import)
try:
    from auth import get_db, login_required
except Exception:
    try:
        # fallback only if auth.py missing
        from app import get_db, login_required
    except Exception:
        raise RuntimeError("get_db/login_required not found. Ensure auth.py exports them or adjust imports.")

profile_bp = Blueprint("profile", __name__, url_prefix="/farmer")


@profile_bp.route("/<int:owner_id>")
def owner_profile(owner_id):
    """Show public profile / stats for owner."""
    db = get_db()
    owner_row = db.execute(
        "SELECT id, name, profile_photo, district, city, state FROM users WHERE id = ?",
        (owner_id,),
    ).fetchone()
    if not owner_row:
        abort(404)

    # coerce sqlite Row -> dict safely
    owner = {k: owner_row[k] for k in owner_row.keys()}

    # stats
    stats_row = db.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM rentals WHERE owner_id = ?) AS total_listings,
          (SELECT COUNT(*) FROM rental_requests rr JOIN rentals r ON rr.rental_id = r.id
             WHERE r.owner_id = ? AND rr.status='completed') AS completed_bookings,
          (SELECT ROUND(AVG(rv.rating),2) FROM rental_reviews rv JOIN rentals r2 ON rv.rental_id = r2.id
             WHERE r2.owner_id = ?) AS avg_rating,
          (SELECT COUNT(rv.id) FROM rental_reviews rv JOIN rentals r3 ON rv.rental_id = r3.id
             WHERE r3.owner_id = ?) AS rating_count
        """,
        (owner_id, owner_id, owner_id, owner_id),
    ).fetchone()
    stats = dict(stats_row) if stats_row else {}

    # average response time
    resp_row = db.execute(
        """
        SELECT AVG(strftime('%s', rr.accepted_at) - strftime('%s', rr.created_at)) AS avg_resp_secs
        FROM rental_requests rr JOIN rentals r ON rr.rental_id = r.id
        WHERE r.owner_id = ? AND rr.accepted_at IS NOT NULL
        """,
        (owner_id,),
    ).fetchone()

    earnings_row = db.execute(
        """
        SELECT COALESCE(SUM(p.amount),0) AS total_earned
        FROM rental_payments p
        JOIN rental_requests rr ON p.request_id = rr.id
        JOIN rentals r ON rr.rental_id = r.id
        WHERE r.owner_id = ? AND p.status = 'completed'
        """,
        (owner_id,),
    ).fetchone()
    earnings = float(earnings_row["total_earned"]) if earnings_row and earnings_row["total_earned"] is not None else 0.0

    recent_rows = db.execute(
        """
        SELECT rr.*, r.title AS rental_title, u.name AS renter_name
        FROM rental_requests rr
        JOIN rentals r ON rr.rental_id = r.id
        JOIN users u ON rr.requester_id = u.id
        WHERE r.owner_id = ?
        ORDER BY rr.created_at DESC LIMIT 12
        """,
        (owner_id,),
    ).fetchall()
    recent = [dict(r) for r in recent_rows] if recent_rows else []

    # followers / following counts
    try:
        followers_row = db.execute("SELECT COUNT(*) AS cnt FROM follow WHERE target_id = ?", (owner_id,)).fetchone()
        followers = int(followers_row["cnt"]) if followers_row and "cnt" in followers_row.keys() else (followers_row[0] if followers_row else 0)
    except Exception:
        followers = 0
    try:
        following_row = db.execute("SELECT COUNT(*) AS cnt FROM follow WHERE follower_id = ?", (owner_id,)).fetchone()
        following = int(following_row["cnt"]) if following_row and "cnt" in following_row.keys() else (following_row[0] if following_row else 0)
    except Exception:
        following = 0

    # who current logged-in user follows (so template shows initial follow state)
    uid = session.get("user_id")
    following_set = set()
    if uid:
        try:
            rows = db.execute("SELECT target_id FROM follow WHERE follower_id = ?", (uid,)).fetchall()
            # rows may be sqlite3.Row or tuples
            following_set = {(r["target_id"] if hasattr(r, "keys") and "target_id" in r.keys() else r[0]) for r in rows}
        except Exception:
            following_set = set()

    def human_time(seconds):
        try:
            s = int(seconds or 0)
        except Exception:
            return "—"
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s//60}m"
        if s < 86400:
            return f"{s//3600}h"
        return f"{s//86400}d"

    is_owner = (uid is not None and uid == owner_id)

    return render_template(
        "farmer/profile.html",
        owner=owner,
        stats=stats,
        avg_response=human_time(resp_row["avg_resp_secs"] if resp_row else None),
        earnings=earnings,
        recent=recent,
        followers=followers,
        following=following,
        following_set=following_set,
        is_owner=is_owner,
    )


@profile_bp.route("/payments")
@login_required
def my_payments():
    """
    Show payments page (both sides):
      - Owner: payments received for rentals owned by the user (earned)
      - Renter: payments made by the user (paid)
    This route name is profile.my_payments (blueprint 'profile') so your templates'
    url_for('profile.my_payments') will work.
    """
    db = get_db()
    uid = session["user_id"]

    # Earned payments (owner view)
    earned_rows = db.execute(
        """
        SELECT p.id, p.request_id, p.payer_id, p.amount, p.currency, p.method, p.status, p.external_id, p.created_at,
               r.title as rental_title, rr.start_date, rr.end_date
        FROM rental_payments p
        JOIN rental_requests rr ON rr.id = p.request_id
        JOIN rentals r ON r.id = rr.rental_id
        WHERE r.owner_id = ?
        ORDER BY p.created_at DESC
        """,
        (uid,),
    ).fetchall()

    # Paid payments (renter view)
    paid_rows = db.execute(
        """
        SELECT p.id, p.request_id, p.payer_id, p.amount, p.currency, p.method, p.status, p.external_id, p.created_at,
               rr.start_date, rr.end_date, r.title as rental_title, u_owner.name as owner_name
        FROM rental_payments p
        JOIN rental_requests rr ON p.request_id = rr.id
        JOIN rentals r ON rr.rental_id = r.id
        LEFT JOIN users u_owner ON r.owner_id = u_owner.id
        WHERE p.payer_id = ?
        ORDER BY p.created_at DESC
        """,
        (uid,),
    ).fetchall()

    # Convert rows to plain dicts for templates
    earned = [dict(x) for x in earned_rows] if earned_rows else []
    paid = [dict(x) for x in paid_rows] if paid_rows else []

    def safe_amount(x):
        try:
            return float(x) if x is not None else 0.0
        except Exception:
            return 0.0

    total_earned = sum([safe_amount(x.get("amount")) for x in earned]) if earned else 0.0
    total_paid = sum([safe_amount(x.get("amount")) for x in paid]) if paid else 0.0

    return render_template(
        "rental/payments.html",
        earned=earned,
        paid=paid,
        total_earned=total_earned,
        total_paid=total_paid,
    )


@profile_bp.route("/earnings-data/<int:owner_id>", endpoint="earnings_data_api")
@login_required
def earnings_data_api(owner_id):
    """Return monthly earnings timeseries for owner (JSON)."""
    uid = session.get("user_id")
    if uid is None or uid != owner_id:
        return jsonify({"error": "forbidden"}), 403

    db = get_db()
    owner = db.execute("SELECT id FROM users WHERE id = ?", (owner_id,)).fetchone()
    if not owner:
        return jsonify({"labels": [], "data": []})

    rows = db.execute(
        """
        SELECT strftime('%Y-%m', p.created_at) AS ym, COALESCE(SUM(p.amount),0) AS total
        FROM rental_payments p
        JOIN rental_requests rr ON p.request_id = rr.id
        JOIN rentals r ON rr.rental_id = r.id
        WHERE r.owner_id = ? AND p.status = 'completed'
        GROUP BY ym
        ORDER BY ym DESC
        LIMIT 24
        """,
        (owner_id,),
    ).fetchall()

    from datetime import datetime as _dt
    now = _dt.utcnow().replace(day=1)
    months = []
    for i in range(11, -1, -1):
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        months.append(f"{year}-{month:02d}")

    map_totals = {}
    for r in rows:
        # support sqlite3.Row and tuples
        if hasattr(r, "keys") and "ym" in r.keys():
            ym = r["ym"]
            total = float(r["total"] or 0.0)
        else:
            ym = r[0] if len(r) > 0 else None
            total = float(r[1]) if len(r) > 1 else 0.0
        if ym:
            map_totals[ym] = total

    data = [map_totals.get(m, 0.0) for m in months]
    labels = [f"{calendar.month_abbr[int(m.split('-')[1])]} {m.split('-')[0]}" for m in months]

    return jsonify({"labels": labels, "data": data})
