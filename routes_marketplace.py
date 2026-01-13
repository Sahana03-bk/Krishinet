# routes_marketplace.py
import os
import json
from datetime import datetime as _dt
from werkzeug.utils import secure_filename
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    current_app, session, abort, jsonify
)
import stripe
from PIL import Image
from auth import get_db, login_required
from dateutil import tz
import json as _json_helper

marketplace_bp = Blueprint("marketplace", __name__, url_prefix="/marketplace")

# Stripe config (reads env)
STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_KEY") or ""
stripe.api_key = STRIPE_SECRET

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif", "mp4", "mov", "avi"}


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _upload_dir():
    ud = current_app.config.get("UPLOAD_DIR")
    if ud:
        os.makedirs(ud, exist_ok=True)
        return ud
    d = os.path.join(current_app.root_path, "static", "uploads")
    os.makedirs(d, exist_ok=True)
    return d


_get_db = get_db

CATEGORIES = [
    "Vegetables", "Fruits", "Seeds", "Fertilizers",
    "Pesticides", "Tools & Machinery", "Dairy", "Poultry", "Other"
]


def save_media_file(file, prefix="product"):
    """
    Save original upload and create a medium preview for display.
    Returns the preview filename (used by templates). Originals kept with _orig suffix.
    """
    if not file or file.filename == "":
        return None
    if not _allowed(file.filename):
        return None

    ext = file.filename.rsplit(".", 1)[1].lower()
    uid = session.get("user_id") or "anon"
    ts = int(_dt.utcnow().timestamp())
    base = secure_filename(f"{prefix}_{uid}_{ts}")
    orig_fname = f"{base}_orig.{ext}"
    preview_fname = f"{base}.jpg"  # convert preview to jpg for consistent delivery

    dest_dir = _upload_dir()
    orig_path = os.path.join(dest_dir, orig_fname)
    preview_path = os.path.join(dest_dir, preview_fname)

    try:
        # Save original bytes first
        file.save(orig_path)

        # If it's an image, create a medium-sized preview
        if ext.lower() in ("png", "jpg", "jpeg", "webp", "gif"):
            try:
                img = Image.open(orig_path).convert("RGB")
                img.thumbnail((1200, 900), Image.LANCZOS)   # keep good quality, not tiny
                img.save(preview_path, "JPEG", quality=85, optimize=True)
                return preview_fname
            except Exception:
                # If PIL fails, fallback to using the original as preview (copy)
                try:
                    import shutil
                    shutil.copyfile(orig_path, preview_path)
                    return preview_fname
                except Exception:
                    current_app.logger.exception("save_media_file: preview creation fallback failed")
                    return None
        else:
            # non-image (video) — return original name
            return orig_fname
    except Exception:
        current_app.logger.exception("save_media_file failed")
        # cleanup attempts
        try:
            if os.path.exists(orig_path): os.remove(orig_path)
            if os.path.exists(preview_path): os.remove(preview_path)
        except Exception:
            pass
        return None


# Basic login requirement helper (so blueprint not import app decorators)
def require_login(next_url=None):
    if not session.get("user_id"):
        flash("Please log in to continue.", "warning")
        return redirect(url_for("login", next=next_url or request.path))
    return None


# ---------------- Index / Listing ----------------
@marketplace_bp.route("/", methods=["GET"])
def index():
    db = _get_db()
    q = (request.args.get("q") or "").strip()
    cat = (request.args.get("category") or "").strip()
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")

    base_sql = """
    SELECT p.*, u.name as seller_name,
           pm.filename as product_image
    FROM products p
    JOIN users u ON p.seller_id = u.id
    LEFT JOIN (SELECT product_id, filename FROM product_media GROUP BY product_id) pm ON p.id = pm.product_id
    WHERE 1=1
    """
    params = []
    if q:
        base_sql += " AND (p.title LIKE ? OR p.description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if cat:
        base_sql += " AND p.category = ?"
        params.append(cat)
    if min_price:
        base_sql += " AND p.price >= ?"
        params.append(min_price)
    if max_price:
        base_sql += " AND p.price <= ?"
        params.append(max_price)

    me = session.get("user_id")
    if me:
        base_sql += " AND p.seller_id != ?"
        params.append(me)

    base_sql += " ORDER BY p.created_at DESC LIMIT 500"
    rows = db.execute(base_sql, params).fetchall()
    products = [dict(r) for r in rows]
    return render_template("marketplace/index.html", products=products, categories=CATEGORIES, q=q, cat=cat)


# ---------------- Post product ----------------
@marketplace_bp.route("/product/new", methods=["GET", "POST"])
def product_new():
    rr = require_login()
    if rr: return rr

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "").strip()
        description = (request.form.get("description") or "").strip()
        try: price = float(request.form.get("price") or 0)
        except: price = 0.0
        try: quantity = float(request.form.get("quantity") or 0)
        except: quantity = 0.0
        qty_unit = (request.form.get("quantity_unit") or "").strip()
        delivery_text = (request.form.get("delivery_locations_text") or "").strip()
        delivery_list = [d.strip() for d in delivery_text.split(",") if d.strip()]
        delivery_json = json.dumps(delivery_list)

        if not title:
            flash("Title required.", "warning")
            return redirect(url_for("marketplace.product_new"))

        db = _get_db()
        with db:
            cur = db.execute("""
                INSERT INTO products (seller_id, title, category, description, price, quantity, quantity_unit, delivery_locations)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (session["user_id"], title, category, description, price, quantity, qty_unit, delivery_json))
            pid = cur.lastrowid

            files = request.files.getlist("media[]")
            for f in files:
                if not f or f.filename == "": continue
                fname = save_media_file(f, prefix=f"product_{pid}")
                if fname:
                    db.execute("INSERT INTO product_media (product_id, filename, media_type) VALUES (?, ?, ?)",
                               (pid, fname, "image" if fname.rsplit(".",1)[1].lower() in ("png","jpg","jpeg","webp","gif") else "video"))

            # notify followers (best-effort)
            try:
                followers = db.execute("SELECT follower_id FROM follow WHERE target_id = ?", (session["user_id"],)).fetchall()
                payload = json.dumps({"product_id": pid, "title": title})
                for fr in followers:
                    try:
                        db.execute("INSERT INTO notifications (user_id, actor_id, verb, payload, is_read) VALUES (?, ?, ?, ?, 0)",
                                   (fr["follower_id"], session["user_id"], "product_posted", payload))
                    except Exception:
                        current_app.logger.debug("notify follower failed")
            except Exception:
                current_app.logger.debug("followers notify skipped")

        flash("Product posted.", "success")
        return redirect(url_for("marketplace.index"))

    return render_template("marketplace/product_form.html", categories=CATEGORIES, product=None)


# ---------------- Product view (hero image + details) ----------------
@marketplace_bp.route("/product/<int:pid>")
def view_product(pid):
    db = _get_db()
    p_row = db.execute("SELECT p.*, u.name as seller_name, u.profile_photo FROM products p JOIN users u ON p.seller_id = u.id WHERE p.id = ?", (pid,)).fetchone()
    if not p_row:
        abort(404)
    product = dict(p_row)
    try:
        delivery_list = json.loads(product.get("delivery_locations") or "[]")
        if not isinstance(delivery_list, list): delivery_list = []
    except Exception:
        delivery_list = []
    medias_rows = db.execute("SELECT * FROM product_media WHERE product_id = ? ORDER BY created_at ASC", (pid,)).fetchall()
    medias = [dict(m) for m in medias_rows]
    hero = None
    if medias:
        hero = medias[0].get("filename")
    elif product.get("product_image"):
        hero = product.get("product_image")
    elif product.get("profile_photo"):
        hero = product.get("profile_photo")
    return render_template("marketplace/product_view.html", product=product, medias=medias, delivery_list=delivery_list, hero_image=hero)


# ---------------- Buy -> create order & stripe checkout ----------------
@marketplace_bp.route("/product/<int:pid>/buy", methods=["POST"])
def buy_product(pid):
    rr = require_login()
    if rr:
        return rr

    db = _get_db()
    p_row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not p_row:
        flash("Product not found.", "warning")
        return redirect(url_for("marketplace.index"))

    p = dict(p_row)

    try:
        qty_raw = request.form.get("quantity", "1")
        qty = float(qty_raw) if qty_raw != "" else 1.0
    except Exception:
        qty = 1.0

    if qty <= 0:
        flash("Invalid quantity.", "warning")
        return redirect(url_for("marketplace.view_product", pid=pid))

    try:
        unit_price = float(p.get("price") or 0.0)
    except Exception:
        unit_price = 0.0

    if unit_price <= 0:
        flash("Product has invalid price; contact seller.", "warning")
        return redirect(url_for("marketplace.view_product", pid=pid))

    subtotal = unit_price * qty

    if not stripe.api_key:
        current_app.logger.error("Stripe secret key (STRIPE_SECRET_KEY) not configured in environment.")
        flash("Payment system not configured. Contact admin.", "danger")
        return redirect(url_for("marketplace.view_product", pid=pid))

    order_id = None
    try:
        with db:
            cur = db.execute("""
                INSERT INTO orders (buyer_id, seller_id, total_amount, currency, status, payment_meta, gateway)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session["user_id"], p["seller_id"], subtotal, "INR", "created", json.dumps({}), "stripe"))
            order_id = cur.lastrowid

            db.execute("""
                INSERT INTO order_items (order_id, product_id, unit_price, quantity, qty_unit, subtotal)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (order_id, pid, unit_price, qty, p.get("quantity_unit"), subtotal))
    except Exception:
        current_app.logger.exception("DB insert for new order failed")
        flash("Unable to create order. Please try again.", "danger")
        return redirect(url_for("marketplace.view_product", pid=pid))

    try:
        domain = request.url_root.rstrip("/")
        unit_amount_int = int(round(unit_price * 100))
        if unit_amount_int <= 0:
            raise ValueError("unit amount must be > 0")

        stripe_qty = int(qty) if float(qty).is_integer() and int(qty) >= 1 else 1

        if not float(qty).is_integer():
            line_item = {
                "price_data": {
                    "currency": "inr",
                    "product_data": {"name": p.get("title") or "", "description": p.get("description") or ""},
                    "unit_amount": int(round(subtotal * 100)),  # charge subtotal as single item
                },
                "quantity": 1
            }
        else:
            line_item = {
                "price_data": {
                    "currency": "inr",
                    "product_data": {"name": p.get("title") or "", "description": p.get("description") or ""},
                    "unit_amount": unit_amount_int,
                },
                "quantity": stripe_qty
            }

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[line_item],
            mode="payment",
            success_url=f"{domain}{url_for('marketplace.checkout_success', order_id=order_id)}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{domain}{url_for('marketplace.view_product', pid=pid)}",
            metadata={"order_id": str(order_id), "product_id": str(pid), "requested_quantity": str(qty)}
        )

        with db:
            db.execute("UPDATE orders SET stripe_session_id = ? WHERE id = ?", (checkout_session.id, order_id))

        return redirect(checkout_session.url)

    except stripe.error.StripeError as se:
        current_app.logger.exception("Stripe API error during checkout creation")
        try:
            with db:
                db.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
                db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        except Exception:
            current_app.logger.exception("Failed to rollback order after stripe error")
        flash("Payment initialization failed (payment gateway error). Please try again.", "danger")
        return redirect(url_for("marketplace.view_product", pid=pid))

    except Exception as e:
        current_app.logger.exception("Unexpected error creating checkout session")
        try:
            with db:
                db.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
                db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        except Exception:
            current_app.logger.exception("Failed to rollback order after unexpected error")
        flash("Payment initialization failed. Please try again or contact support.", "danger")
        return redirect(url_for("marketplace.view_product", pid=pid))


@marketplace_bp.route("/checkout/success/<int:order_id>")
def checkout_success(order_id):
    session_id = request.args.get("session_id")
    db = _get_db()
    if not session_id:
        flash("Payment completed; if the order remains 'created' it will update once webhook is received.", "info")
        return redirect(url_for("marketplace.order_detail", order_id=order_id))

    try:
        checkout_sess = stripe.checkout.Session.retrieve(session_id, expand=["payment_intent"])
        payment_status = getattr(checkout_sess, "payment_status", None) or (checkout_sess.get("payment_intent") and checkout_sess["payment_intent"].get("status"))
        payment_intent = checkout_sess.get("payment_intent")
        paid = False
        if payment_status and str(payment_status).lower() in ("paid", "succeeded"):
            paid = True
        if not paid and payment_intent:
            pi_status = payment_intent.get("status") if isinstance(payment_intent, dict) else getattr(payment_intent, "status", None)
            if pi_status and str(pi_status).lower() in ("succeeded", "paid"):
                paid = True

        if paid:
            with db:
                db.execute("UPDATE orders SET status=?, stripe_payment_intent=?, payment_meta=? WHERE id=?",
                           ("paid", payment_intent if isinstance(payment_intent, str) else (payment_intent.get("id") if isinstance(payment_intent, dict) else ""), json.dumps(checkout_sess), order_id))
            flash("Payment confirmed. Receipt will appear in Orders.", "success")
        else:
            flash("Payment not confirmed yet. Webhook will update the order once Stripe sends confirmation.", "info")

    except Exception:
        current_app.logger.exception("checkout success verify failed")
        flash("Unable to verify payment with Stripe; order will be updated when webhook arrives.", "warning")

    return redirect(url_for("marketplace.order_detail", order_id=order_id))


# ---------------- stripe webhook ----------------
@marketplace_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """
    Stripe webhook handler:
    - verifies signature (if STRIPE_WEBHOOK_SECRET configured)
    - handles checkout.session.completed and payment_intent.succeeded
    - idempotently marks orders paid, inserts payments row
    - fixes order_items.subtotal if missing, decrements product quantities
    - notifies the seller
    """
    payload = request.data
    sig = request.headers.get("Stripe-Signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET") or ""
    event = None

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
        else:
            event = stripe.Event.construct_from(json.loads(payload.decode("utf-8")), stripe.api_key)
    except Exception:
        current_app.logger.exception("stripe webhook: event construct/verification failed")
        return jsonify({"ok": False, "error": "invalid_signature_or_payload"}), 400

    try:
        etype = event.get("type")
        db = _get_db()

        def _mark_order_paid(order_id, payment_amount=None, currency="INR",
                             gateway="stripe", payment_intent=None, raw_meta=None):
            if not order_id:
                return False
            try:
                with db:
                    o = db.execute(
                        "SELECT id, status, total_amount, buyer_id, seller_id FROM orders WHERE id = ?",
                        (order_id,)
                    ).fetchone()
                    if not o:
                        current_app.logger.debug("stripe webhook: order not found %s", order_id)
                        return False

                    # convert to dict so we can reference safely
                    o = dict(o)

                    if o.get("status") != "paid":
                        db.execute(
                            "UPDATE orders SET status = ?, stripe_payment_intent = ?, payment_meta = ? WHERE id = ?",
                            ("paid", payment_intent or "", json.dumps(raw_meta or {}), order_id)
                        )

                    already = db.execute("SELECT 1 FROM payments WHERE order_id = ?", (order_id,)).fetchone()
                    if not already:
                        amt = payment_amount if (payment_amount is not None) else (o.get("total_amount") or 0.0)
                        db.execute(
                            """INSERT INTO payments (order_id, amount, currency, gateway, payment_intent, raw_meta)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (order_id, amt, currency, gateway, payment_intent or "", json.dumps(raw_meta or {}))
                        )

                    items = db.execute(
                        "SELECT id, product_id, quantity, unit_price, subtotal FROM order_items WHERE order_id = ?",
                        (order_id,)
                    ).fetchall()

                    for it in items:
                        iid = it["id"]
                        prod_id = it["product_id"]
                        try:
                            qty = float(it["quantity"] or 0)
                        except Exception:
                            qty = 0.0
                        try:
                            up = float(it["unit_price"] or 0)
                        except Exception:
                            up = 0.0

                        if not it["subtotal"] or float(it["subtotal"]) == 0:
                            calc_sub = up * qty
                            db.execute("UPDATE order_items SET subtotal = ? WHERE id = ?", (calc_sub, iid))

                        p = db.execute("SELECT quantity FROM products WHERE id = ?", (prod_id,)).fetchone()
                        if p:
                            try:
                                cur_q = float(p["quantity"] or 0)
                                new_q = cur_q - qty
                                if new_q < 0:
                                    new_q = 0
                                db.execute("UPDATE products SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                           (new_q, prod_id))
                            except Exception:
                                current_app.logger.exception("stripe webhook: failed updating product quantity for %s", prod_id)

                    payload2 = json.dumps({"order_id": order_id, "amount": o.get("total_amount")})
                    try:
                        db.execute(
                            "INSERT INTO notifications (user_id, actor_id, verb, payload, is_read) VALUES (?, ?, ?, ?, 0)",
                            (o.get("seller_id"), o.get("buyer_id"), "order_paid", payload2)
                        )
                    except Exception:
                        current_app.logger.debug("stripe webhook: failed to insert notification for order %s", order_id)

                return True
            except Exception:
                current_app.logger.exception("stripe webhook: _mark_order_paid failed for order %s", order_id)
                return False

        # handle checkout.session.completed
        if etype == "checkout.session.completed":
            sess = event["data"]["object"]
            metadata = sess.get("metadata") or {}
            try:
                order_id = int(metadata.get("order_id") or 0)
            except Exception:
                order_id = 0

            payment_intent = sess.get("payment_intent") or sess.get("payment_intent_id") or ""
            amount_total = None
            if sess.get("amount_total") is not None:
                try:
                    amount_total = float(sess.get("amount_total")) / 100.0
                except Exception:
                    amount_total = None
            raw_meta = sess
            _mark_order_paid(order_id,
                             payment_amount=amount_total,
                             currency=(sess.get("currency") or "INR"),
                             gateway="stripe",
                             payment_intent=payment_intent,
                             raw_meta=raw_meta)

        # handle payment_intent.succeeded
        elif etype == "payment_intent.succeeded":
            pi = event["data"]["object"]

            try:
                res = record_stripe_payment_intent(db, pi)
                current_app.logger.info("PaymentIntent recorded: %s", res)
            except Exception:
                current_app.logger.exception("record_stripe_payment_intent raised")
                res = {}

            order_id = None
            try:
                metadata = pi.get("metadata") or {}
                if metadata and metadata.get("order_id"):
                    try:
                        order_id = int(metadata.get("order_id"))
                    except Exception:
                        order_id = None

                if not order_id and isinstance(res, dict):
                    order_id = res.get("order_id")

                amount = None
                if pi.get("amount_received") is not None:
                    try:
                        amount = float(pi.get("amount_received")) / 100.0
                    except Exception:
                        amount = None

                payment_intent = pi.get("id") or ""

                if order_id:
                    ok = _mark_order_paid(order_id,
                                          payment_amount=amount,
                                          currency=(pi.get("currency") or "INR"),
                                          gateway="stripe",
                                          payment_intent=payment_intent,
                                          raw_meta=pi)
                    current_app.logger.info("Called _mark_order_paid(order_id=%s) -> %s", order_id, ok)
                else:
                    current_app.logger.info(
                        "No order_id found for PaymentIntent %s; payment recorded for manual reconciliation",
                        payment_intent
                    )

            except Exception:
                current_app.logger.exception("payment_intent.succeeded: post-record reconciliation failed")

        else:
            current_app.logger.debug("stripe webhook: unhandled event type %s", etype)

    except Exception:
        current_app.logger.exception("stripe webhook: top-level handler failure")
        return jsonify({"ok": False}), 500

    return jsonify({"ok": True})


# ---------------- Orders / receipt ----------------
@marketplace_bp.route("/orders")
def orders_list():
    rr = require_login()
    if rr: return rr
    db = _get_db()
    uid = session["user_id"]
    rows = db.execute("SELECT * FROM orders WHERE buyer_id = ? OR seller_id = ? ORDER BY created_at DESC LIMIT 200", (uid, uid)).fetchall()
    return render_template("marketplace/orders.html", orders=[dict(r) for r in rows])


@marketplace_bp.route("/order/<int:order_id>")
def order_detail(order_id):
    rr = require_login()
    if rr: return rr
    db = _get_db()
    o = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not o:
        abort(404)

    # convert to dict for consistent access
    order = dict(o)

    # security: only buyer or seller can view
    if session["user_id"] not in (order["buyer_id"], order["seller_id"]):
        abort(403)

    items = db.execute("SELECT oi.*, p.title FROM order_items oi JOIN products p ON oi.product_id = p.id WHERE oi.order_id = ?", (order_id,)).fetchall()
    items = [dict(i) for i in items]

    # ensure payment_meta is JSON/dict for the template
    try:
        pm = order.get("payment_meta")
        if pm and isinstance(pm, (str, bytes)):
            order["payment_meta"] = json.loads(pm)
    except Exception:
        current_app.logger.debug("order_detail: failed to parse payment_meta for order %s", order_id)
        order["payment_meta"] = order.get("payment_meta") or {}

    return render_template("marketplace/order_detail.html", order=order, items=items)


@marketplace_bp.route("/order/<int:order_id>/receipt")
def order_receipt(order_id):
    rr = require_login()
    if rr:
        return rr
    db = _get_db()
    o = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not o:
        abort(404)
    if session["user_id"] not in (o["buyer_id"], o["seller_id"]):
        abort(403)

    items = db.execute("SELECT oi.*, p.title FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id WHERE oi.order_id = ?", (order_id,)).fetchall()

    # Build concise payments summary for the receipt (don't expose raw_meta)
    payments = []
    import json as _json
    p_rows = db.execute("SELECT * FROM payments WHERE order_id = ? ORDER BY created_at ASC", (order_id,)).fetchall()
    for pr in p_rows:
        p_summary = {
            "payment_id": pr["id"],
            "amount": pr["amount"],
            "payment_intent": pr["payment_intent"],
            "status": None,
            "charge_id": None,
            "receipt_url": None,
            "paid_at": pr["created_at"]
        }
        try:
            raw_meta = pr["raw_meta"]
            parsed = {}
            if raw_meta:
                if isinstance(raw_meta, (str, bytes)):
                    parsed = _json.loads(raw_meta)
                elif isinstance(raw_meta, dict):
                    parsed = raw_meta

            p_summary["status"] = parsed.get("payment_status") or parsed.get("status") or None

            charges = None
            if isinstance(parsed.get("charges"), dict):
                charges = parsed["charges"].get("data", [])
            elif isinstance(parsed.get("payment_intent"), dict):
                charges = parsed["payment_intent"].get("charges", {}).get("data", [])
            if charges:
                p_summary["charge_id"] = charges[0].get("id")
                p_summary["receipt_url"] = charges[0].get("receipt_url")
            p_summary["charge_id"] = p_summary["charge_id"] or parsed.get("latest_charge") or p_summary["charge_id"]
        except Exception:
            pass

        payments.append(p_summary)

    order_dict = dict(o)
    order_dict["payments"] = payments

    return render_template("marketplace/receipt.html", order=order_dict, items=[dict(i) for i in items])

# ---------------- Edit / Delete ----------------
@marketplace_bp.route("/product/<int:pid>/edit", methods=["GET", "POST"])
def product_edit(pid):
    rr = require_login()
    if rr: return rr
    db = _get_db()
    p_row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not p_row: abort(404)
    p = dict(p_row)
    if session.get("user_id") != p["seller_id"]: abort(403)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "").strip()
        description = (request.form.get("description") or "").strip()
        try: price = float(request.form.get("price") or 0)
        except: price = 0.0
        try: quantity = float(request.form.get("quantity") or 0)
        except: quantity = 0.0
        qty_unit = (request.form.get("quantity_unit") or "").strip()
        delivery_text = (request.form.get("delivery_locations_text") or "").strip()
        delivery_list = [d.strip() for d in delivery_text.split(",") if d.strip()]
        delivery_json = json.dumps(delivery_list)
        with db:
            db.execute("""
                UPDATE products SET title=?, category=?, description=?, price=?, quantity=?, quantity_unit=?, delivery_locations=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (title, category, description, price, quantity, qty_unit, delivery_json, pid))
            files = request.files.getlist("media[]")
            for f in files:
                if not f or f.filename == "": continue
                fname = save_media_file(f, prefix=f"product_{pid}")
                if fname:
                    db.execute("INSERT INTO product_media (product_id, filename, media_type) VALUES (?, ?, ?)",
                               (pid, fname, "image" if fname.rsplit(".",1)[1].lower() in ("png","jpg","jpeg","webp","gif") else "video"))
        flash("Product updated.", "success")
        return redirect(url_for("marketplace.view_product", pid=pid))
    medias = db.execute("SELECT * FROM product_media WHERE product_id = ?", (pid,)).fetchall()
    return render_template("marketplace/product_form.html", categories=CATEGORIES, product=p, medias=[dict(m) for m in medias])


@marketplace_bp.route("/product/<int:pid>/delete", methods=["POST"])
def product_delete(pid):
    rr = require_login()
    if rr: return rr
    db = _get_db()
    p_row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not p_row: abort(404)
    p = dict(p_row)
    if session.get("user_id") != p["seller_id"]: abort(403)
    try:
        medias = db.execute("SELECT filename FROM product_media WHERE product_id = ?", (pid,)).fetchall()
        upload_dir = _upload_dir()
        with db:
            for m in medias:
                fname = m["filename"] if isinstance(m, dict) else m[0]
                if fname:
                    try:
                        path = os.path.join(upload_dir, fname)
                        if os.path.exists(path): os.remove(path)
                    except Exception:
                        current_app.logger.debug("failed to remove file %s", fname)
            db.execute("DELETE FROM product_media WHERE product_id = ?", (pid,))
            db.execute("DELETE FROM order_items WHERE product_id = ?", (pid,))
            db.execute("DELETE FROM products WHERE id = ?", (pid,))
    except Exception:
        current_app.logger.exception("product delete failed")
        flash("Failed to delete product (server error).", "danger")
        return redirect(url_for("marketplace.view_product", pid=pid))
    flash("Product deleted.", "success")
    return redirect(url_for("marketplace.index"))


# ---------------- Seller dashboard (my posts) ----------------
@marketplace_bp.route("/my-posts")
def my_posts():
    rr = require_login()
    if rr:
        return rr

    db = _get_db()
    uid = session["user_id"]

    try:
        page = max(1, int(request.args.get("page") or 1))
    except Exception:
        page = 1
    per_page = 10
    offset = (page - 1) * per_page

    total_row = db.execute(
        "SELECT COUNT(*) AS cnt FROM products WHERE seller_id = ?",
        (uid,)
    ).fetchone()
    total_products = (total_row["cnt"] if total_row else 0)

    rows = db.execute("""
      SELECT p.id, p.title, p.quantity, p.quantity_unit, p.price, p.created_at,
             pm.filename AS product_image,
             COALESCE((SELECT SUM(oi.quantity) FROM order_items oi
                       JOIN orders o2 ON o2.id = oi.order_id
                       WHERE oi.product_id = p.id AND o2.status = 'paid'), 0) AS sold_count,
             COALESCE((SELECT SUM(oi.subtotal) FROM order_items oi
                       JOIN orders o2 ON o2.id = oi.order_id
                       WHERE oi.product_id = p.id AND o2.status = 'paid'), 0) AS revenue
      FROM products p
      LEFT JOIN (SELECT product_id, filename FROM product_media GROUP BY product_id) pm 
        ON pm.product_id = p.id
      WHERE p.seller_id = ?
      ORDER BY p.created_at DESC
      LIMIT ? OFFSET ?
    """, (uid, per_page, offset)).fetchall()

    products = [dict(r) for r in rows]

    # --- Seller totals ---
    totals_row = db.execute("""
      SELECT
        COALESCE(SUM(oi.quantity), 0) AS total_units_sold,
        COALESCE(SUM(oi.subtotal), 0) AS total_revenue
      FROM order_items oi
      JOIN orders o ON o.id = oi.order_id
      JOIN products p ON p.id = oi.product_id
      WHERE p.seller_id = ? AND o.status = 'paid'
    """, (uid,)).fetchone()

    try:
        tv = dict(totals_row or {"total_units_sold": 0, "total_revenue": 0})
        seller_totals = {
            "total_units_sold": _as_float(tv.get("total_units_sold", 0)),
            "total_revenue": _as_float(tv.get("total_revenue", 0))
        }
    except Exception:
        current_app.logger.exception("my_posts: failed to parse seller_totals")
        seller_totals = {"total_units_sold": 0.0, "total_revenue": 0.0}

    # --- Pagination info ---
    total_pages = max(1, (total_products + per_page - 1) // per_page)
    pagination = {
        "page": page,
        "per_page": per_page,
        "total_products": total_products,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1
    }

    return render_template(
        "marketplace/my_posts.html",
        products=products,
        seller_totals=seller_totals,
        posted_count=total_products,
        pagination=pagination
    )


@marketplace_bp.route("/product/<int:pid>/sales")
def product_sales_detail(pid):
    rr = require_login()
    if rr:
        return rr
    db = _get_db()

    pr = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not pr:
        abort(404)
    pr = dict(pr)
    if session.get("user_id") != pr["seller_id"]:
        abort(403)

    rows = db.execute("""
        SELECT o.id as order_id, o.buyer_id, COALESCE(u.name, '') as buyer_name,
               oi.quantity, oi.qty_unit, oi.unit_price, oi.subtotal, o.total_amount, o.currency, o.created_at
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        LEFT JOIN users u ON u.id = o.buyer_id
        WHERE oi.product_id = ? AND o.status = 'paid'
        ORDER BY o.created_at DESC
    """, (pid,)).fetchall()

    # convert rows -> dicts and normalize numeric fields
    orders = []
    for r in rows:
        rd = dict(r)
        rd['quantity'] = _as_float(rd.get('quantity'), 0.0)
        rd['unit_price'] = _as_float(rd.get('unit_price'), 0.0)
        rd['subtotal'] = _as_float(rd.get('subtotal'), rd['quantity'] * rd['unit_price'])
        # keep created_at as-is for template (string or datetime)
        orders.append(rd)

    product = pr
    # Sum only the paid orders (we already limited SQL to paid)
    total_sold = sum(o.get('quantity', 0.0) for o in orders)
    total_revenue = sum(o.get('subtotal', 0.0) for o in orders)

    # Pass numbers directly to the template (templates will format)
    return render_template("marketplace/product_sales.html",
                           product=product, orders=orders,
                           total_sold=total_sold, total_revenue=total_revenue)


@marketplace_bp.route("/my-orders")
def my_orders():
    rr = require_login()
    if rr: return rr

    db = _get_db()
    uid = session["user_id"]

    rows = db.execute("""
        SELECT o.*, u.name as seller_name
        FROM orders o
        LEFT JOIN users u ON u.id = o.seller_id
        WHERE o.buyer_id = ?
        ORDER BY o.created_at DESC
        LIMIT 500
    """, (uid,)).fetchall()

    orders = []
    for r in rows:
        o = dict(r)
        order_id = o["id"]

        items_rows = db.execute("""
            SELECT oi.*, p.title
            FROM order_items oi
            LEFT JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = ?
        """, (order_id,)).fetchall()
        items = []
        for it in items_rows:
            itd = dict(it)
            # normalize numeric fields
            itd['quantity'] = _as_float(itd.get('quantity'), 0.0)
            itd['unit_price'] = _as_float(itd.get('unit_price'), 0.0)
            itd['subtotal'] = _as_float(itd.get('subtotal'), itd['quantity'] * itd['unit_price'])
            items.append(itd)

        payment_meta = {}
        try:
            pm = o.get("payment_meta")
            if pm:
                if isinstance(pm, (str, bytes)):
                    payment_meta = json.loads(pm)
                elif isinstance(pm, dict):
                    payment_meta = pm
        except Exception:
            current_app.logger.debug("payment_meta parse failed for order %s", order_id)
            payment_meta = {}

        txn_id = payment_meta.get("payment_intent") or payment_meta.get("id") or payment_meta.get("payment_intent_id") or ""

        orders.append({
            "order": o,
            "items": items,
            "payment_meta": payment_meta,
            "txn_id": txn_id
        })

    totals_row = db.execute("""
        SELECT COUNT(*) AS purchases_count, COALESCE(SUM(total_amount),0) AS total_spent
        FROM orders
        WHERE buyer_id = ? AND status = 'paid'
    """, (uid,)).fetchone()
    try:
        br = dict(totals_row or {"purchases_count": 0, "total_spent": 0})
        buyer_totals = {"purchases_count": int(br.get("purchases_count", 0)), "total_spent": _as_float(br.get("total_spent", 0))}
    except Exception:
        buyer_totals = {"purchases_count": 0, "total_spent": 0.0}

    return render_template("marketplace/orders.html",
                           orders=orders,
                           buyer_totals=buyer_totals)

# Add / replace this in routes_marketplace.py
# Add / replace this in routes_marketplace.py
@marketplace_bp.route("/purchase-history")
@login_required
def purchase_history():
    """
    Clean purchase history: list orders for current buyer with concise items and payment summary.
    Avoid exposing raw payment JSON.
    """
    db = _get_db()
    uid = session["user_id"]

    try:
        rows = db.execute("""
            SELECT o.id AS order_id, o.total_amount, o.currency, o.status, o.created_at,
                   u.name AS seller_name
            FROM orders o
            LEFT JOIN users u ON u.id = o.seller_id
            WHERE o.buyer_id = ?
            ORDER BY o.created_at DESC
            LIMIT 500
        """, (uid,)).fetchall()
    except Exception:
        current_app.logger.exception("purchase_history: failed fetching orders")
        rows = []

    orders = []
    import json as _json
    for r in rows:
        try:
            o = dict(r)
            order_id = o["order_id"]

            # -- items summary --
            items_rows = db.execute("""
               SELECT oi.quantity, oi.qty_unit, oi.unit_price, oi.subtotal, p.title
               FROM order_items oi
               LEFT JOIN products p ON p.id = oi.product_id
               WHERE oi.order_id = ?
            """, (order_id,)).fetchall()

            items = []
            for it in items_rows:
                itd = dict(it)
                title = itd.get("title") or "Item"
                qty = itd.get("quantity") or 0
                unit = itd.get("qty_unit") or ""
                unit_price = None
                subtotal = None
                try:
                    unit_price = float(itd.get("unit_price")) if itd.get("unit_price") is not None else None
                except Exception:
                    unit_price = None
                try:
                    subtotal = float(itd.get("subtotal")) if itd.get("subtotal") is not None else None
                except Exception:
                    subtotal = None

                # ensure we have a subtotal (fallback)
                if subtotal is None:
                    try:
                        subtotal = (unit_price or 0.0) * float(qty or 0.0)
                    except Exception:
                        subtotal = 0.0

                items.append({
                    "title": title,
                    "quantity": qty,
                    "qty_unit": unit,
                    "unit_price": unit_price,
                    "subtotal": subtotal
                })

            # build a single-line items_text for table display (first 2 items)
            items_text_parts = []
            for it in items[:2]:
                price_display = f" ₹{(it['subtotal']):,.2f}" if it['subtotal'] is not None else ""
                qty_unit = f" {it['qty_unit']}" if it['qty_unit'] else ""
                items_text_parts.append(f"{it['title']} — {it['quantity']}{qty_unit}{price_display}")
            items_text = " • ".join(items_text_parts)
            if len(items) > 2:
                items_text += f" (+{len(items)-2} more)"

            # -- payments summary (do NOT render raw_meta) --
            p_rows = db.execute("""
                SELECT id, amount, currency, payment_intent, raw_meta, created_at
                FROM payments
                WHERE order_id = ?
                ORDER BY created_at ASC
            """, (order_id,)).fetchall()

            payments = []
            for pr in p_rows:
                prd = dict(pr)
                receipt_url = None
                raw_meta = prd.get("raw_meta")

                # safely parse raw_meta into parsed (only if JSON string or dict)
                parsed = None
                if raw_meta:
                    try:
                        if isinstance(raw_meta, (str, bytes)):
                            parsed = _json.loads(raw_meta)
                        elif isinstance(raw_meta, dict):
                            parsed = raw_meta
                    except Exception:
                        parsed = None

                # try to extract receipt_url from parsed structure (charges/payment_intent)
                if parsed:
                    try:
                        charges = None
                        if isinstance(parsed.get("charges"), dict):
                            charges = parsed["charges"].get("data", [])
                        elif isinstance(parsed.get("payment_intent"), dict):
                            charges = parsed["payment_intent"].get("charges", {}).get("data", [])
                        if charges and isinstance(charges, (list, tuple)) and len(charges) > 0:
                            receipt_url = charges[0].get("receipt_url") or charges[0].get("receipt")
                        # fallback to latest_charge if present
                        if not receipt_url:
                            latest = parsed.get("latest_charge") or parsed.get("latest_charge_id")
                            if latest and isinstance(latest, str):
                                # not a URL, but keep it available if needed by UI later
                                receipt_url = None
                    except Exception:
                        receipt_url = None

                payments.append({
                    "id": prd.get("id"),
                    "amount": prd.get("amount"),
                    "currency": prd.get("currency"),
                    "payment_intent": prd.get("payment_intent") or "",
                    "receipt_url": receipt_url,
                    "created_at": prd.get("created_at")
                })

            # format created_at simply (if numeric timestamp, convert)
            created_raw = o.get("created_at")
            try:
                if isinstance(created_raw, (int, float)):
                    created = _dt.fromtimestamp(created_raw).strftime("%Y-%m-%d %H:%M")
                else:
                    created = str(created_raw)
            except Exception:
                created = str(created_raw)

            # format total amount display
            total_display = ""
            try:
                total_val = float(o.get("total_amount") or 0.0)
                # assume already in rupees (adjust if stored in paise)
                total_display = f"₹{total_val:,.2f}"
            except Exception:
                total_display = str(o.get("total_amount") or "")

            orders.append({
                "order_id": order_id,
                "seller_name": o.get("seller_name") or "Unknown",
                "total_display": total_display,
                "status": o.get("status") or "",
                "created": created,
                "items_text": items_text,
                "items": items,
                "payments": payments
            })

        except Exception:
            current_app.logger.exception("purchase_history: failed processing order row")
            continue

    return render_template("marketplace/purchase_history.html", orders=orders)

# ---- Helpers for safe numeric conversion and currency display ----
def _as_float(val, default=0.0):
    """Safely convert DB numeric-like values to float (defensive)."""
    try:
        if val is None:
            return float(default)
        return float(val)
    except Exception:
        try:
            return float(str(val))
        except Exception:
            return float(default)


def _money_display(amount):
    """Return formatted rupee string (assumes amount is already in rupees).
       If your DB stores paise (cents), change amount = amount / 100.0 here.
    """
    try:
        a = float(amount or 0.0)
        return f"₹{a:,.2f}"
    except Exception:
        return str(amount or "")

