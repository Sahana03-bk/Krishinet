# routes_rental.py
import os
import json
from datetime import datetime as _dt
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    current_app, session, abort, jsonify
)
from werkzeug.utils import secure_filename
import uuid

# Prefer helpers from auth.py to avoid circular imports with app.py
try:
    from auth import get_db, login_required
except Exception:
    # Last-resort fallback: try importing from app (may reintroduce circular import).
    try:
        from app import get_db, login_required
    except Exception:
        raise RuntimeError("get_db/login_required not found. Ensure auth.py exports them.")

# Lazy resolver for save_media_file to avoid importing marketplace at module import time
def _get_save_media():
    try:
        from routes_marketplace import save_media_file
        return save_media_file
    except Exception:
        # minimal fallback implementation
        def save_media_file(file, prefix="rental"):
            if not file or file.filename == "":
                return None
            ext = file.filename.rsplit(".", 1)[-1].lower()
            ts = int(_dt.utcnow().timestamp())
            uid = session.get("user_id", "anon")
            fname = secure_filename(f"{prefix}_{uid}_{ts}.{ext}")
            upload_dir = os.path.join(current_app.root_path, "static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            path = os.path.join(upload_dir, fname)
            file.save(path)
            return fname
        return save_media_file

rental_bp = Blueprint("rental", __name__, url_prefix="/rental")

# basic categories (editable)
RENTAL_CATEGORIES = ["Tractor", "Plough", "Rotavator", "Harvester", "Seeder", "Sprayer", "Trailer", "Other"]

# ---------------- Listings index ----------------
@rental_bp.route("/", methods=["GET"])
@login_required
def index():
    """
    Shows all rentals for all users including the current user's own equipment.
    Provides filters by search, category, and owner_id.
    """
    db = get_db()
    q = (request.args.get("q") or "").strip()
    cat = (request.args.get("category") or "").strip()
    owner = request.args.get("owner")

    sql = """
        SELECT r.*, 
               (SELECT filename FROM rental_media m WHERE m.rental_id = r.id LIMIT 1) AS hero, 
               u.name as owner_name
        FROM rentals r 
        JOIN users u ON r.owner_id = u.id
        WHERE 1=1
    """
    params = []

    # Search by title/description/location
    if q:
        sql += " AND (r.title LIKE ? OR r.description LIKE ? OR r.location LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]

    # Filter by category
    if cat:
        sql += " AND r.category = ?"
        params.append(cat)

    # If specific owner filter (optional)
    if owner:
        sql += " AND r.owner_id = ?"
        params.append(owner)

    sql += " ORDER BY r.created_at DESC LIMIT 500"

    try:
        rows = db.execute(sql, params).fetchall()
        rentals = [dict(x) for x in rows]
    except Exception:
        current_app.logger.exception("rental.index query failed")
        rentals = []

    uid = session.get("user_id")
    if uid:
        for r in rentals:
            r["is_owner"] = (r["owner_id"] == uid)

    return render_template("rental/index.html",
                           rentals=rentals,
                           categories=RENTAL_CATEGORIES,
                           q=q, cat=cat)

# ---------------- New listing / Create ----------------
@rental_bp.route("/new", methods=["GET", "POST"])
@login_required
def rental_new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "").strip()
        description = (request.form.get("description") or "").strip()
        try:
            price_per_day = float(request.form.get("price_per_day") or 0)
        except Exception:
            price_per_day = 0.0
        deposit = float(request.form.get("deposit") or 0) if request.form.get("deposit") else 0.0
        condition = request.form.get("condition")
        location = request.form.get("location")
        lat = request.form.get("latitude")
        lon = request.form.get("longitude")

        if not title or price_per_day <= 0:
            flash("Please provide a title and valid price per day.", "warning")
            return redirect(url_for("rental.rental_new"))

        db = get_db()
        try:
            with db:
                cur = db.execute("""INSERT INTO rentals (owner_id, title, category, description, price_per_day, deposit, condition, location, latitude, longitude)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session["user_id"], title, category, description, price_per_day, deposit, condition, location, lat, lon))
                rid = cur.lastrowid
                files = request.files.getlist("media[]")
                save_media_file = _get_save_media()
                for f in files:
                    if f and f.filename:
                        try:
                            fname = save_media_file(f, prefix=f"rental_{rid}")
                        except Exception:
                            fname = None
                            current_app.logger.exception("save_media_file failed during rental_new")
                        if fname:
                            db.execute("INSERT INTO rental_media (rental_id, filename, media_type) VALUES (?, ?, ?)", (rid, fname, "image"))
            flash("Rental posted.", "success")
            return redirect(url_for("rental.view_rental", rid=rid))
        except Exception:
            current_app.logger.exception("rental_new failed")
            flash("Failed to create listing.", "danger")
            return redirect(url_for("rental.rental_new"))

    return render_template("rental/form.html", categories=RENTAL_CATEGORIES, rental=None)

# ---------------- View single rental ----------------
@rental_bp.route("/view/<int:rid>")
def view_rental(rid):
    db = get_db()
    r = db.execute("SELECT r.*, u.name as owner_name, u.id as owner_id, u.profile_photo FROM rentals r JOIN users u ON r.owner_id = u.id WHERE r.id = ?", (rid,)).fetchone()
    if not r:
        abort(404)
    medias = db.execute("SELECT * FROM rental_media WHERE rental_id = ? ORDER BY created_at ASC", (rid,)).fetchall()
    unav = db.execute("SELECT start_date, end_date FROM rental_unavailabilities WHERE rental_id = ? ORDER BY start_date", (rid,)).fetchall()
    my_request = None
    if session.get("user_id"):
        try:
            req_row = db.execute("""SELECT * FROM rental_requests
                                     WHERE rental_id = ? AND requester_id = ?
                                     ORDER BY created_at DESC LIMIT 1""",
                                  (rid, session["user_id"])).fetchone()
            if req_row:
                my_request = dict(req_row)
        except Exception:
            current_app.logger.debug("could not fetch my_request")

    return render_template("rental/view.html", rental=dict(r), medias=[dict(m) for m in medias],
                           unavail=[dict(u) for u in unav], my_request=my_request)

# ---------------- Request create (renter) ----------------
@rental_bp.route("/request/<int:rid>", methods=["POST"])
@login_required
def request_rental(rid):
    db = get_db()
    r = db.execute("SELECT * FROM rentals WHERE id = ?", (rid,)).fetchone()
    if not r:
        abort(404)
    start = request.form.get("start_date")
    end = request.form.get("end_date")
    note = (request.form.get("note") or "").strip()
    if not start or not end:
        flash("Please select start and end dates.", "warning")
        return redirect(url_for("rental.view_rental", rid=rid))
    try:
        from datetime import datetime as _d
        s = _d.strptime(start, "%Y-%m-%d").date()
        e = _d.strptime(end, "%Y-%m-%d").date()
        days = (e - s).days + 1
        if days <= 0:
            raise ValueError("invalid")
    except Exception:
        flash("Invalid dates.", "warning")
        return redirect(url_for("rental.view_rental", rid=rid))

    conflict = db.execute("""
      SELECT COUNT(*) AS c FROM rental_requests
      WHERE rental_id = ? AND status IN ('accepted','paid','ongoing') AND NOT (end_date < ? OR start_date > ?)
    """, (rid, start, end)).fetchone()
    if conflict and conflict['c'] > 0:
        flash("The selected dates conflict with an existing booking. Choose other dates.", "danger")
        return redirect(url_for("rental.view_rental", rid=rid))

    price_per_day = float(r["price_per_day"] or 0)
    total_price = price_per_day * days

    try:
        with db:
            cur = db.execute("""INSERT INTO rental_requests (rental_id, requester_id, start_date, end_date, requested_days, price_offered, status)
                                VALUES (?, ?, ?, ?, ?, ?, ?)""", (rid, session["user_id"], start, end, days, total_price, "requested"))
            req_id = cur.lastrowid
            try:
                payload = json.dumps({"rental_id": rid, "request_id": req_id, "start": start, "end": end, "note": note})
                db.execute("INSERT INTO notifications (user_id, actor_id, verb, payload, is_read) VALUES (?, ?, ?, ?, 0)",
                           (r["owner_id"], session["user_id"], "rental_requested", payload))
            except Exception:
                current_app.logger.debug("notifications insertion skipped or failed")
        flash("Rental request sent to owner.", "success")
        return redirect(url_for("rental.my_requests"))
    except Exception:
        current_app.logger.exception("request_rental failed")
        flash("Failed to send rental request.", "danger")
        return redirect(url_for("rental.view_rental", rid=rid))

# ---------------- Owner: list requests for their rentals ----------------
@rental_bp.route("/requests")
@login_required
def owner_requests():
    db = get_db()
    uid = session["user_id"]
    rows = db.execute("""
      SELECT rr.*, r.title as rental_title, u.name as requester_name
      FROM rental_requests rr
      JOIN rentals r ON rr.rental_id = r.id
      JOIN users u ON rr.requester_id = u.id
      WHERE r.owner_id = ?
      ORDER BY rr.created_at DESC
    """, (uid,)).fetchall()
    return render_template("rental/owner_requests.html", requests=[dict(x) for x in rows])

# ---------------- Renter: my requests ----------------
@rental_bp.route("/my-requests")
@login_required
def my_requests():
    db = get_db()
    uid = session["user_id"]
    rows = db.execute("""
      SELECT rr.*, r.title as rental_title, u.name as owner_name
      FROM rental_requests rr
      JOIN rentals r ON rr.rental_id = r.id
      JOIN users u ON r.owner_id = u.id
      WHERE rr.requester_id = ?
      ORDER BY rr.created_at DESC
    """, (uid,)).fetchall()
    return render_template("rental/my_requests.html", requests=[dict(x) for x in rows])

# ---------------- Action on a request (accept/reject/cancel/complete) ----------------
@rental_bp.route("/request/<int:req_id>/action", methods=["POST"])
@login_required
def request_action(req_id):
    action = request.form.get("action")
    if action not in ("accept", "reject", "cancel", "complete"):
        return jsonify({"ok": False, "error": "invalid_action"}), 400
    db = get_db()
    rr = db.execute("SELECT rr.*, r.owner_id, r.title, r.price_per_day FROM rental_requests rr JOIN rentals r ON rr.rental_id = r.id WHERE rr.id = ?", (req_id,)).fetchone()
    if not rr:
        return jsonify({"ok": False, "error": "not_found"}), 404
    uid = session["user_id"]

    # permission checks
    if action in ("accept", "reject", "complete") and uid != rr["owner_id"]:
        return jsonify({"ok": False, "error": "not_allowed"}), 403
    if action == "cancel" and uid != rr["requester_id"]:
        return jsonify({"ok": False, "error": "not_allowed"}), 403

    new_status = {"accept":"accepted", "reject":"rejected", "cancel":"cancelled", "complete":"completed"}[action]

    # if accepting, check for conflicts again
    if action == "accept":
        conflict = db.execute("""
          SELECT COUNT(*) AS c FROM rental_requests
          WHERE rental_id = ? AND status IN ('accepted','paid','ongoing') AND NOT (end_date < ? OR start_date > ?)
        """, (rr["rental_id"], rr["start_date"], rr["end_date"])).fetchone()
        if conflict and conflict['c'] > 0:
            return jsonify({"ok": False, "error": "conflict"}), 409

    try:
        with db:
            if action == "accept":
                db.execute("UPDATE rental_requests SET status=?, accepted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (new_status, req_id))
            else:
                db.execute("UPDATE rental_requests SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (new_status, req_id))

            # notify the other party
            notify_to = rr["requester_id"] if uid == rr["owner_id"] else rr["owner_id"]
            payload = json.dumps({"request_id": req_id, "action": new_status})
            try:
                db.execute("INSERT INTO notifications (user_id, actor_id, verb, payload, is_read) VALUES (?, ?, ?, ?, 0)",
                           (notify_to, uid, "rental_request_update", payload))
            except Exception:
                current_app.logger.debug("notify insert failed")
    except Exception:
        current_app.logger.exception("request_action failed")
        return jsonify({"ok": False}), 500

    return jsonify({"ok": True, "status": new_status})

# ---------------- Mark unavailability (owner) ----------------
@rental_bp.route("/<int:rid>/unavailability", methods=["POST"])
@login_required
def mark_unavailability(rid):
    db = get_db()
    r = db.execute("SELECT * FROM rentals WHERE id = ?", (rid,)).fetchone()
    if not r:
        abort(404)
    if r["owner_id"] != session.get("user_id"):
        abort(403)
    start = request.form.get("start_date")
    end = request.form.get("end_date")
    reason = request.form.get("reason") or ""
    if not start or not end:
        flash("Please choose start and end dates.", "warning")
        return redirect(url_for("rental.view_rental", rid=rid))
    with db:
        db.execute("INSERT INTO rental_unavailabilities (rental_id, start_date, end_date, reason) VALUES (?, ?, ?, ?)",
                   (rid, start, end, reason))
    flash("Marked unavailable.", "success")
    return redirect(url_for("rental.view_rental", rid=rid))

# ---------------- Owner: edit listing ----------------
@rental_bp.route("/edit/<int:rid>", methods=["GET", "POST"])
@login_required
def rental_edit(rid):
    db = get_db()
    r = db.execute("SELECT * FROM rentals WHERE id = ?", (rid,)).fetchone()
    if not r:
        abort(404)
    if r["owner_id"] != session.get("user_id"):
        abort(403)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "").strip()
        description = (request.form.get("description") or "").strip()
        try:
            price_per_day = float(request.form.get("price_per_day") or 0)
        except Exception:
            price_per_day = 0.0
        deposit = float(request.form.get("deposit") or 0) if request.form.get("deposit") else 0.0
        condition = request.form.get("condition")
        location = request.form.get("location")
        lat = request.form.get("latitude")
        lon = request.form.get("longitude")

        if not title or price_per_day <= 0:
            flash("Please provide a title and valid price per day.", "warning")
            return redirect(url_for("rental.rental_edit", rid=rid))

        try:
            with db:
                db.execute("""UPDATE rentals SET title=?, category=?, description=?, price_per_day=?, deposit=?, condition=?, location=?, latitude=?, longitude=?, updated_at=CURRENT_TIMESTAMP
                              WHERE id=?""",
                           (title, category, description, price_per_day, deposit, condition, location, lat, lon, rid))
                files = request.files.getlist("media[]")
                save_media_file = _get_save_media()
                for f in files:
                    if f and f.filename:
                        try:
                            fname = save_media_file(f, prefix=f"rental_{rid}")
                        except Exception:
                            fname = None
                            current_app.logger.exception("save_media_file failed during rental_edit")
                        if fname:
                            db.execute("INSERT INTO rental_media (rental_id, filename, media_type) VALUES (?, ?, ?)", (rid, fname, "image"))
            flash("Listing updated.", "success")
            return redirect(url_for("rental.view_rental", rid=rid))
        except Exception:
            current_app.logger.exception("rental_edit failed")
            flash("Failed to update listing.", "danger")
            return redirect(url_for("rental.rental_edit", rid=rid))

    categories = RENTAL_CATEGORIES
    return render_template("rental/form.html", categories=categories, rental=dict(r))

# ---------------- Update listing (owner-only, API + form) ----------------
@rental_bp.route("/<int:rid>/update", methods=["POST", "PUT", "PATCH"])
@login_required
def rental_update(rid):
    db = get_db()
    r = db.execute("SELECT * FROM rentals WHERE id = ?", (rid,)).fetchone()
    if not r:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "not_found"}), 404
        abort(404)

    uid = session.get("user_id")
    if r["owner_id"] != uid:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "not_allowed"}), 403
        abort(403)

    # accept both JSON and form input
    data = {}
    if request.is_json:
        try:
            data.update(request.get_json() or {})
        except Exception:
            data.update({})
    else:
        data.update(request.form.to_dict(flat=True))

    # collect update fields
    updates = {}
    if "title" in data:
        updates["title"] = (data.get("title") or "").strip()
    if "category" in data:
        updates["category"] = (data.get("category") or "").strip()
    if "description" in data:
        updates["description"] = (data.get("description") or "").strip()
    if "price_per_day" in data:
        try:
            updates["price_per_day"] = float(data.get("price_per_day") or 0)
        except Exception:
            updates["price_per_day"] = None
    if "deposit" in data:
        try:
            updates["deposit"] = float(data.get("deposit") or 0)
        except Exception:
            updates["deposit"] = None
    if "condition" in data:
        updates["condition"] = data.get("condition")
    if "location" in data:
        updates["location"] = data.get("location")
    if "latitude" in data:
        updates["latitude"] = data.get("latitude")
    if "longitude" in data:
        updates["longitude"] = data.get("longitude")

    # parse remove_media_ids param (JSON array, comma-separated string, or single)
    remove_ids = []
    if "remove_media_ids" in data:
        val = data.get("remove_media_ids")
        if isinstance(val, (list, tuple)):
            for x in val:
                try:
                    remove_ids.append(int(x))
                except Exception:
                    pass
        elif isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, (list, tuple)):
                    for x in parsed:
                        try:
                            remove_ids.append(int(x))
                        except Exception:
                            pass
            except Exception:
                for part in val.split(","):
                    part = part.strip()
                    if part.isdigit():
                        remove_ids.append(int(part))
        else:
            try:
                remove_ids.append(int(val))
            except Exception:
                pass

    # hero image id (optional)
    hero_image_id = None
    if "hero_image_id" in data:
        try:
            hero_image_id = int(data.get("hero_image_id"))
        except Exception:
            hero_image_id = None

    # files to add
    new_files = request.files.getlist("media[]") if request.files else []

    # media limit
    MAX_MEDIA_TOTAL = 6
    try:
        cur_media = db.execute("SELECT id, filename FROM rental_media WHERE rental_id = ? ORDER BY id ASC", (rid,)).fetchall()
        existing_count = len(cur_media)
    except Exception:
        cur_media = []
        existing_count = 0

    space_left = max(0, MAX_MEDIA_TOTAL - existing_count)
    accepted_files = new_files[:space_left] if new_files else []

    save_media_file = _get_save_media()

    deleted_media_filenames = []
    added_media_filenames = []

    try:
        with db:
            # apply rental field updates
            if updates:
                set_parts = []
                params = []
                for k, v in updates.items():
                    if v is None and k in ("price_per_day", "deposit"):
                        continue
                    set_parts.append(f"{k} = ?")
                    params.append(v)
                if set_parts:
                    params.append(rid)
                    sql = "UPDATE rentals SET " + ", ".join(set_parts) + ", updated_at = CURRENT_TIMESTAMP WHERE id = ?"
                    db.execute(sql, params)

            # delete specified media rows (verify rental_id)
            if remove_ids:
                placeholders = ",".join("?" for _ in remove_ids)
                q_params = (*remove_ids, rid)
                rows_to_del = db.execute(f"SELECT id, filename FROM rental_media WHERE id IN ({placeholders}) AND rental_id = ?", q_params).fetchall()
                for row in rows_to_del:
                    try:
                        db.execute("DELETE FROM rental_media WHERE id = ?", (row["id"],))
                        deleted_media_filenames.append(row["filename"])
                    except Exception:
                        current_app.logger.exception("Failed to delete rental_media row id=%s", row["id"])

            # save new files up to space_left
            for f in accepted_files:
                if f and getattr(f, "filename", ""):
                    try:
                        fname = save_media_file(f, prefix=f"rental_{rid}")
                    except Exception:
                        current_app.logger.exception("save_media_file failed during rental_update")
                        fname = None
                    if fname:
                        db.execute("INSERT INTO rental_media (rental_id, filename, media_type, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (rid, fname, "image"))
                        added_media_filenames.append(fname)

            # set hero image if requested and belongs to rental
            if hero_image_id:
                mcheck = db.execute("SELECT filename FROM rental_media WHERE id = ? AND rental_id = ?", (hero_image_id, rid)).fetchone()
                if mcheck:
                    fname = mcheck["filename"]
                    try:
                        db.execute("UPDATE rentals SET hero_filename = ? WHERE id = ?", (fname, rid))
                    except Exception:
                        try:
                            db.execute("UPDATE rentals SET hero = ? WHERE id = ?", (fname, rid))
                        except Exception:
                            current_app.logger.debug("No hero column available on rentals table; hero not persisted")
    except Exception:
        current_app.logger.exception("rental_update failed (transaction)")
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "db_error"}), 500
        flash("Failed to update listing.", "danger")
        return redirect(url_for("rental.rental_edit", rid=rid))

    # remove deleted files from disk after successful DB commit (best-effort)
    if deleted_media_filenames:
        upload_dir = os.path.join(current_app.root_path, "static", "uploads")
        for fn in deleted_media_filenames:
            try:
                path = os.path.join(upload_dir, fn)
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                current_app.logger.exception("Failed to remove file %s", fn)

    updated_row = db.execute("SELECT r.*, (SELECT filename FROM rental_media m WHERE m.rental_id = r.id LIMIT 1) AS hero_filename FROM rentals r WHERE r.id = ?", (rid,)).fetchone()
    updated_rental = dict(updated_row) if updated_row else {}

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "ok": True,
            "rental": updated_rental,
            "added_media": added_media_filenames,
            "deleted_media": deleted_media_filenames
        })

    flash("Listing updated.", "success")
    return redirect(url_for("rental.rental_edit", rid=rid))

# ---------------- Owner: delete listing ----------------
@rental_bp.route("/delete/<int:rid>", methods=["POST"])
@login_required
def rental_delete(rid):
    db = get_db()
    r = db.execute("SELECT * FROM rentals WHERE id = ?", (rid,)).fetchone()
    if not r:
        abort(404)
    if r["owner_id"] != session.get("user_id"):
        abort(403)

    try:
        with db:
            medias = db.execute("SELECT filename FROM rental_media WHERE rental_id = ?", (rid,)).fetchall()
            db.execute("DELETE FROM rental_media WHERE rental_id = ?", (rid,))
            db.execute("DELETE FROM rental_requests WHERE rental_id = ?", (rid,))
            db.execute("DELETE FROM rental_unavailabilities WHERE rental_id = ?", (rid,))
            db.execute("DELETE FROM rental_reviews WHERE rental_id = ?", (rid,)) 
            db.execute("DELETE FROM rentals WHERE id = ?", (rid,))
        try:
            upload_dir = os.path.join(current_app.root_path, "static", "uploads")
            for m in medias:
                fname = m["filename"] if isinstance(m, dict) else (m[0] if m else None)
                if fname:
                    path = os.path.join(upload_dir, fname)
                    if os.path.exists(path):
                        os.remove(path)
        except Exception:
            current_app.logger.debug("Failed to remove media files (non-critical).")
    except Exception:
        current_app.logger.exception("rental_delete failed")
        flash("Failed to delete listing.", "danger")
        return redirect(url_for("rental.view_rental", rid=rid))

    flash("Listing deleted.", "success")
    return redirect(url_for("rental.my_listings"))

# ---------------- My listings (owner management) ----------------
@rental_bp.route("/my-listings")
@login_required
def my_listings():
    db = get_db()
    uid = session["user_id"]
    rows = db.execute("SELECT r.*, (SELECT filename FROM rental_media m WHERE m.rental_id = r.id LIMIT 1) AS hero FROM rentals r WHERE owner_id = ? ORDER BY r.created_at DESC", (uid,)).fetchall()
    return render_template("rental/my_listings.html", rentals=[dict(x) for x in rows])

# --- Calendar events endpoint (bookings + unavailabilities) ---
@rental_bp.route("/events/<int:rid>")
def rental_events(rid):
    db = get_db()
    r = db.execute("SELECT id FROM rentals WHERE id = ?", (rid,)).fetchone()
    if not r:
        return jsonify([])

    events = []
    rows = db.execute("""
      SELECT id, requester_id, start_date, end_date, status
      FROM rental_requests
      WHERE rental_id = ?
    """, (rid,)).fetchall()
    for row in rows:
        status = row["status"] if isinstance(row, dict) else row[4]
        start = row["start_date"] if isinstance(row, dict) else row[2]
        end = row["end_date"] if isinstance(row, dict) else row[3]
        ev = {
            "id": f"req-{row['id']}" if isinstance(row, dict) else f"req-{row[0]}",
            "title": ("Request" if status == "requested" else status.capitalize()),
            "start": start,
            "end": end,
            "allDay": True,
            "extendedProps": {"type": "booking", "status": status}
        }
        if status in ("accepted", "paid", "ongoing"):
            ev["color"] = "#d9534f"
        elif status == "requested":
            ev["color"] = "#f0ad4e"
        elif status in ("rejected", "cancelled", "completed"):
            ev["color"] = "#6c757d"
        events.append(ev)

    urows = db.execute("SELECT id, start_date, end_date, reason FROM rental_unavailabilities WHERE rental_id = ?", (rid,)).fetchall()
    for u in urows:
        ev = {
            "id": f"unav-{u['id']}" if isinstance(u, dict) else f"unav-{u[0]}",
            "title": ("Unavailable" if (isinstance(u, dict) and not u.get("reason")) else (u["reason"] if isinstance(u, dict) else (u[3] if len(u)>3 else "Unavailable"))),
            "start": u["start_date"] if isinstance(u, dict) else u[1],
            "end": u["end_date"] if isinstance(u, dict) else u[2],
            "allDay": True,
            "color": "#6c757d",
            "extendedProps": {"type": "unavailability"}
        }
        events.append(ev)

    return jsonify(events)
