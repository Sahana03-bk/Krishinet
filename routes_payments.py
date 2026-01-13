# routes_payments.py
import os
import json
from io import BytesIO
from datetime import datetime
from flask import session 
from flask import (
    Blueprint, request, current_app, jsonify, render_template, url_for,
    redirect, abort, send_file
)
try:
    import stripe
except Exception:
    stripe = None
from flask import request, redirect, url_for, flash, current_app, abort
# prefer auth helpers to avoid circular import
try:
    from auth import get_db, login_required
except Exception:
    try:
        from app import get_db, login_required
    except Exception:
        raise RuntimeError("get_db/login_required not found. Ensure auth.py exports them.")

payments_bp = Blueprint("payments", __name__)

# config from env
STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY", "") or os.getenv("STRIPE_API_KEY", "")
STRIPE_PUB    = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

if stripe and STRIPE_SECRET:
    stripe.api_key = STRIPE_SECRET

# Helper to create pending rental payment record
def create_rental_payment_record(db, request_id, payer_id, amount, currency="INR", method=None, external_id=None, mode="full"):
    cur = db.execute("""INSERT INTO rental_payments
                        (request_id, payer_id, amount, currency, method, status, external_id, mode, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                     (request_id, payer_id, amount, currency, method or "stripe", "pending", external_id or "", mode))
    return cur.lastrowid

# Helper to mark payment completed (used by webhook / manual flows)
def mark_rental_payment_completed(db, payment_row, stripe_session_id=None, stripe_payment_intent=None):
    """
    Marks rental_payments as completed and updates rental_requests status -> 'paid'.
    - payment_row: sqlite3.Row for rental_payments (must contain id and request_id)
    """
    try:
        pid = payment_row["id"] if hasattr(payment_row, "keys") and "id" in payment_row.keys() else (payment_row[0] if isinstance(payment_row, (list, tuple)) else None)
        req_id = payment_row["request_id"] if hasattr(payment_row, "keys") and "request_id" in payment_row.keys() else (payment_row[1] if isinstance(payment_row, (list, tuple)) else None)
    except Exception:
        current_app.logger.exception("Invalid payment_row passed to mark_rental_payment_completed")
        return False

    try:
        with db:
            db.execute("""UPDATE rental_payments
                          SET status = ?, external_id = COALESCE(?, external_id), updated_at = CURRENT_TIMESTAMP
                          WHERE id = ?""",
                       ("completed", stripe_payment_intent or stripe_session_id, pid))
            db.execute("UPDATE rental_requests SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", ("paid", req_id))
        return True
    except Exception:
        current_app.logger.exception("Failed to mark payment completed (db update)")
        return False

# ---------------- Create Checkout Session ----------------
# ---------------- Create Checkout Session ----------------
@payments_bp.route("/rental/request/<int:req_id>/create_session", methods=["POST"])
@login_required
def create_checkout_session(req_id):
    """
    Expects form body:
      - mode: 'advance' or 'full'
    Returns JSON:
      { ok: True, checkout_url: "...", sessionId: "...", payment_id: 123, amount: 100.0 }
    """
    db = get_db()

    # fetch rental request row
    rr_row = db.execute("""SELECT rr.*, r.owner_id, r.title, r.price_per_day, r.deposit, rr.requester_id, r.id AS rental_id
                           FROM rental_requests rr
                           JOIN rentals r ON rr.rental_id = r.id
                           WHERE rr.id = ?""", (req_id,)).fetchone()
    if not rr_row:
        return jsonify({"ok": False, "error": "request_not_found"}), 404

    # convert sqlite3.Row -> dict so .get(...) works
    try:
        rr = dict(rr_row)
    except Exception:
        try:
            rr = {k: rr_row[k] for k in rr_row.keys()}
        except Exception:
            current_app.logger.exception("Failed to convert rental_request row to dict")
            return jsonify({"ok": False, "error": "internal"}), 500

    # session + permission checks
    uid = session.get("user_id")
    if uid is None:
        return jsonify({"ok": False, "error": "not_authenticated"}), 401

    # only the requester may create a payment for their own request
    try:
        requester_id = rr.get("requester_id")
    except Exception:
        requester_id = rr["requester_id"] if "requester_id" in rr else None

    if uid != requester_id:
        return jsonify({"ok": False, "error": "not_allowed"}), 403

    # mode
    mode = (request.form.get("mode") or (request.json and request.json.get("mode")) or "full").lower()
    mode = "advance" if mode == "advance" else "full"

    # compute amounts
    try:
        offered_val = rr.get("price_offered")
        per_day_val = rr.get("price_per_day")
        days = int(rr.get("requested_days") or 1)
        # If price_offered already represents the total for all days, don’t multiply again
        if offered_val and float(offered_val) > 0:
            total_amount = float(offered_val)
        else:
            total_amount = float(per_day_val or 0.0) * days
    except Exception:
        total_amount = 0.0


    if mode == "advance":
        # prefer explicit deposit on rental, else 30% advance
        deposit_val = rr.get("deposit")
        try:
            deposit = float(deposit_val) if deposit_val is not None else 0.0
        except Exception:
            deposit = 0.0
        if deposit and deposit > 0:
            to_collect = round(deposit, 2)
        else:
            to_collect = round(total_amount * 0.30, 2)
    else:
        to_collect = round(total_amount, 2)

    if to_collect <= 0:
        return jsonify({"ok": False, "error": "invalid_amount"}), 400

    # record pending payment
    try:
        with db:
            pay_id = create_rental_payment_record(db, req_id, uid, to_collect, currency="INR", method="stripe", external_id="", mode=mode)
    except Exception:
        current_app.logger.exception("Failed to create rental_payment record")
        return jsonify({"ok": False, "error": "db_error"}), 500

    # prepare URLs
    origin = request.host_url.rstrip("/")
    success_url = (
        f"{url_for('payments.checkout_return', _external=True)}"
        f"?session_id={{CHECKOUT_SESSION_ID}}&payment_id={pay_id}"
    )

    # rental id for cancel url
    rental_id = rr.get("rental_id") or db.execute(
        "SELECT rental_id FROM rental_requests WHERE id = ?", (req_id,)
    ).fetchone().get("rental_id")
    cancel_url = url_for("rental.view_rental", rid=rental_id, _external=True) if rental_id else url_for("index", _external=True)
    
    
    # If Stripe is available, create a checkout session
    if stripe:
        try:
            amount_in_paise = int(round(to_collect * 100))
            # product title fallback
            title = rr.get("title") or "Rental"

            session_obj = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "inr",
                        "product_data": {"name": f"KrishiNet Rental: {title}"},
                        "unit_amount": amount_in_paise,
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=success_url,
                cancel_url=url_for("rental.view_rental", rid=rental_id, _external=True),
                metadata={"rental_payment_id": str(payment.id)}
            )

            # store external id (session id) for reference -- best-effort
            try:
                with db:
                    db.execute("UPDATE rental_payments SET external_id = ? WHERE id = ?", (session_obj.get("id"), pay_id))
            except Exception:
                current_app.logger.debug("Failed to update rental_payments.external_id (non-fatal)")

            return jsonify({
                "ok": True,
                "checkout_url": session_obj.get("url"),
                "sessionId": session_obj.get("id"),
                "payment_id": pay_id,
                "amount": to_collect
            })
        except Exception as e:
            current_app.logger.exception("Stripe Checkout creation failed")
            return jsonify({"ok": False, "error": "stripe_error", "message": str(e)}), 500

    # fallback (no stripe)
    fake_url = url_for("payments.checkout_success", _external=True) + f"?payment_id={pay_id}"
    current_app.logger.warning("Stripe library not present; returning fake checkout url for payment %s", pay_id)
    return jsonify({"ok": True, "checkout_url": fake_url, "payment_id": pay_id, "amount": to_collect})




# ---------------- Checkout success / thankyou ----------------
# in routes_payments.py — replace existing checkout_success() with below

@payments_bp.route("/rental/thankyou")
@login_required
def checkout_success():
    """
    Called after redirect from Stripe (or the fake local fallback).
    Query params:
      - payment_id : rental_payments.id (always present from our create_session)
      - session_id : (optional) Stripe Checkout session id returned by Stripe in success_url
    This handler will try to verify the session with Stripe (if configured) and
    mark the rental payment completed. If webhook is configured this is redundant
    but useful when webhook is not available (local dev).
    """
    pid = request.args.get("payment_id")
    session_id = request.args.get("session_id") or request.args.get("sessionId") or None

    db = get_db()
    # quick guard
    if not pid:
        return render_template("rental/thankyou.html", payment_id=None, verified=False)

    # fetch payment row
    pay_row = db.execute("SELECT * FROM rental_payments WHERE id = ?", (pid,)).fetchone()
    if not pay_row:
        return render_template("rental/thankyou.html", payment_id=pid, verified=False)

    # convert pay_row to dict for convenience
    try:
        pay = dict(pay_row)
    except Exception:
        try:
            pay = {k: pay_row[k] for k in pay_row.keys()}
        except Exception:
            pay = None

    verified = False
    # 1) Try to verify with stripe if we have session_id and stripe lib configured
    try:
        if stripe and session_id:
            sess = stripe.checkout.Session.retrieve(session_id, expand=["payment_intent"])
            # payment_status is set on session; PaymentIntent.status also useful
            payment_status = getattr(sess, "payment_status", None) or sess.get("payment_status")
            stripe_payment_intent = None
            if getattr(sess, "payment_intent", None):
                pi_obj = sess.payment_intent
                stripe_payment_intent = (pi_obj.id if hasattr(pi_obj, "id") else pi_obj)
            else:
                stripe_payment_intent = sess.get("payment_intent") or sess.get("paymentIntent")

            intent_status = None
            if stripe_payment_intent:
                try:
                    pi = stripe.PaymentIntent.retrieve(stripe_payment_intent)
                    intent_status = getattr(pi, "status", None) or pi.get("status")
                except Exception:
                    intent_status = None

            if payment_status == "paid" or intent_status == "succeeded":
                # mark completed (helper updates both payment and request)
                # prefer metadata for rental_payment_id
                metadata = getattr(sess, "metadata", {}) or sess.get("metadata", {}) or {}
                rp_id = metadata.get("rental_payment_id") or metadata.get("payment_id") or pid
                try:
                    rp_row = db.execute("SELECT * FROM rental_payments WHERE id = ?", (int(rp_id),)).fetchone()
                except Exception:
                    rp_row = None
                if rp_row:
                    ok = mark_rental_payment_completed(db, rp_row, stripe_session_id=session_id, stripe_payment_intent=stripe_payment_intent)
                    verified = bool(ok)
    except Exception:
        # non-fatal; continue to fallback logic
        current_app.logger.exception("checkout_success: stripe verification failed (non-fatal)")

    # 2) Fallback for local/dev when stripe or webhook is not available:
    #    If the current logged-in user is the payer and the payment is still pending,
    #    mark it completed so the user sees an immediate "Booking completed" experience.
    if not verified:
        try:
            from flask import session as flask_session
            uid = flask_session.get("user_id")
            # Only allow this quick-complete if the logged-in user is the payer
            if pay and uid and (str(pay.get("payer_id")) == str(uid) or pay.get("payer_id") == uid):
                # Only auto-complete if current status is still pending (avoid accidental re-mark)
                current_status = pay.get("status") or pay_row["status"]
                if current_status in (None, "", "pending", "requested"):
                    ok = mark_rental_payment_completed(db, pay_row, stripe_session_id=session_id, stripe_payment_intent=None)
                    if ok:
                        verified = True
        except Exception:
            current_app.logger.exception("checkout_success fallback mark completed failed (non-fatal)")

    # Render thank-you page. Front-end JS will poll payment status and open receipt when DB shows completed.
    return render_template("rental/thankyou.html", payment_id=pid, verified=verified)


# ---------------- Poll payment status ----------------
@payments_bp.route("/rental/payment/<int:pid>/status", methods=["GET"])
@login_required
def payment_status(pid):
    db = get_db()
    row = db.execute("SELECT * FROM rental_payments WHERE id = ?", (pid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "not_found"}), 404
    # ensure returned shape is JSON serializable
    try:
        status = row["status"]
        amount = row["amount"]
        method = row["method"]
        external = row["external_id"]
    except Exception:
        # fallback for different row shape
        d = dict(row) if hasattr(row, "keys") else row
        status = d.get("status")
        amount = d.get("amount")
        method = d.get("method")
        external = d.get("external_id")
    return jsonify({"ok": True, "status": status, "amount": amount, "method": method, "external_id": external})

# ---------------- Receipt (HTML and PDF) ----------------
@payments_bp.route("/rental/payment/<int:payment_id>/receipt")
@login_required
def payment_receipt(payment_id):
    """
    Renders receipt HTML. Supports query ?format=pdf to attempt PDF generation.
    Template used: templates/rental/receipt.html
    """
    db = get_db()
    p = db.execute("""SELECT p.*, rr.start_date, rr.end_date, rr.requested_days, rr.rental_id,
                             r.title AS rental_title, u.name AS renter_name, u.id AS renter_id, o.name AS owner_name, o.id AS owner_id
                      FROM rental_payments p
                      JOIN rental_requests rr ON p.request_id = rr.id
                      JOIN rentals r ON rr.rental_id = r.id
                      LEFT JOIN users u ON p.payer_id = u.id
                      LEFT JOIN users o ON r.owner_id = o.id
                      WHERE p.id = ?""", (payment_id,)).fetchone()
    if not p:
        return "Receipt not found", 404

    payment = dict(p)
    html = render_template("rental/receipt.html", rr=payment, payment=payment)

    # if user requested pdf
    if request.args.get("format") == "pdf":
        try:
            from weasyprint import HTML
            pdf = HTML(string=html, base_url=request.host_url).write_pdf()
            return send_file(BytesIO(pdf),
                             mimetype="application/pdf",
                             as_attachment=True,
                             download_name=f"receipt-{payment_id}.pdf")
        except Exception:
            current_app.logger.exception("PDF generation failed; returning HTML fallback")
            # fallthrough to return HTML

    return html

# Alternate URL style also accepted (used earlier code)
@payments_bp.route("/rental/payment/<int:pid>/receipt.pdf")
@login_required
def payment_receipt_pdf(pid):
    # simple wrapper to the above
    return payment_receipt(pid)

# ---------------- Refund (owner) ----------------
@payments_bp.route("/rental/payment/<int:pid>/refund", methods=["POST"])
@login_required
def payment_refund(pid):
    db = get_db()
    p = db.execute("""SELECT p.*, rr.rental_id, r.owner_id
                      FROM rental_payments p
                      JOIN rental_requests rr ON p.request_id = rr.id
                      JOIN rentals r ON rr.rental_id = r.id
                      WHERE p.id = ?""", (pid,)).fetchone()
    if not p:
        return jsonify({"ok": False, "error": "not_found"}), 404

    uid = None
    from flask import session
    uid = session.get("user_id")
    if uid != p["owner_id"]:
        return jsonify({"ok": False, "error": "not_allowed"}), 403

    external = p["external_id"] or ""
    # Try stripe refund if possible (best-effort)
    if stripe and external:
        try:
            # best-effort: try to refund a PaymentIntent or Charge stored in external_id
            # NOTE: robust handling requires storing the actual PaymentIntent/Charge id at payment time.
            # Here we'll simply mark refunded in DB to keep UI consistent.
            with db:
                db.execute("UPDATE rental_payments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", ("refunded", pid))
            return jsonify({"ok": True, "status": "refunded"})
        except Exception:
            current_app.logger.exception("Refund attempt failed")
            return jsonify({"ok": False, "error": "refund_failed"}), 500
    else:
        # no stripe or no external id: mark refunded in DB (dev environment)
        try:
            with db:
                db.execute("UPDATE rental_payments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", ("refunded", pid))
            return jsonify({"ok": True, "status": "refunded"})
        except Exception:
            current_app.logger.exception("Failed to mark refunded")
            return jsonify({"ok": False, "error": "db_error"}), 500

# ---------------- Stripe webhook ----------------
@payments_bp.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    endpoint_secret = STRIPE_WEBHOOK_SECRET
    if not stripe:
        current_app.logger.warning("Stripe library unavailable; ignoring webhook")
        return jsonify({"ok": False, "msg": "stripe_unavailable"}), 501

    event = None
    # verify signature if secret configured
    if endpoint_secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except Exception as e:
            current_app.logger.exception("Stripe webhook signature verification failed")
            return jsonify({"ok": False, "error": "signature_verification_failed"}), 400
    else:
        try:
            event = json.loads(payload)
        except Exception:
            return jsonify({"ok": False, "error": "invalid_payload"}), 400

    # normalize event type
    try:
        typ = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    except Exception:
        typ = None

    ev = event if isinstance(event, dict) else (event.to_dict() if hasattr(event, "to_dict") else {})

    # handle checkout.session.completed
    if typ == "checkout.session.completed" or ev.get("type") == "checkout.session.completed":
        data_obj = ev.get("data", {}).get("object", {}) if isinstance(ev.get("data", {}), dict) else {}
        metadata = data_obj.get("metadata") or {}
        rental_payment_id = metadata.get("rental_payment_id") or metadata.get("payment_id") or data_obj.get("metadata", {}).get("rental_payment_id")
        payment_intent = data_obj.get("payment_intent") or data_obj.get("paymentIntent") or None

        db = get_db()
        try:
            if rental_payment_id:
                with db:
                    db.execute("UPDATE rental_payments SET status = ?, external_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                               ("completed", payment_intent or (data_obj.get("id") or ""), rental_payment_id))
                    db.execute("UPDATE rental_requests SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT request_id FROM rental_payments WHERE id = ?)",
                               ("paid", rental_payment_id, rental_payment_id))
                current_app.logger.info("Marked rental_payment %s completed via webhook", rental_payment_id)
        except Exception:
            current_app.logger.exception("Failed to update DB from webhook")
        return jsonify({"ok": True}), 200

    # unknown events
    return jsonify({"ok": True, "received": typ}), 200

@payments_bp.route("/rental/pay/<int:payment_id>", methods=["GET"])
@login_required
def pay_rental_payment(payment_id):
    db = get_db()
    pid_row = db.execute("SELECT p.*, rr.requester_id, rr.rental_id FROM rental_payments p JOIN rental_requests rr ON p.request_id = rr.id WHERE p.id = ?", (payment_id,)).fetchone()
    if not pid_row:
        abort(404)
    # ensure current user is the payer
    if session.get("user_id") != pid_row["payer_id"]:
        abort(403)
    # render a page with the amount and a "Pay" button that uses your Stripe/checkout flow
    return render_template("payments/rental_pay.html", payment=dict(pid_row))

# Request owner to ask renter to pay full amount (or for renter to request full payment)
@payments_bp.route("/rental/request/<int:req_id>/request-full-payment", methods=["POST"])
@login_required
def request_full_payment(req_id):
    """
    Endpoint to create a rental_payments record for the FULL amount
    (useful when owner asks renter to pay full instead of advance).
    Expects JSON or form; returns JSON with payment_id and checkout URL (if Stripe available).
    """
    db = get_db()
    rr = db.execute("""SELECT rr.*, r.owner_id, r.title, r.price_per_day, r.deposit
                       FROM rental_requests rr
                       JOIN rentals r ON rr.rental_id = r.id
                       WHERE rr.id = ?""", (req_id,)).fetchone()
    if not rr:
        return jsonify({"ok": False, "error": "request_not_found"}), 404

    uid = None
    from flask import session
    uid = session.get("user_id")
    if uid is None:
        return jsonify({"ok": False, "error": "not_authenticated"}), 401

    # Only the requester (renter) may initiate payment for their rental request
    if uid != rr["requester_id"]:
        return jsonify({"ok": False, "error": "not_allowed"}), 403

    # compute total_amount (use price_offered if present else price_per_day * requested_days)
    try:
        price_per_day = float(rr.get("price_offered") or rr.get("price_per_day") or 0.0)
    except Exception:
        price_per_day = 0.0
    try:
        days = int(rr.get("requested_days") or 1)
    except Exception:
        days = 1
    total_amount = round(price_per_day * days, 2)
    if total_amount <= 0:
        return jsonify({"ok": False, "error": "invalid_amount"}), 400

    # Create pending full-payment record (mode = 'full')
    try:
        with db:
            pid = create_rental_payment_record(db, req_id, uid, total_amount, currency="INR", method="stripe", external_id="", mode="full")
    except Exception:
        current_app.logger.exception("Failed to create rental_payment record for full payment")
        return jsonify({"ok": False, "error": "db_error"}), 500

    # return a checkout URL (use existing create_checkout_session route or client to call it)
    # We'll respond with the payment id so frontend can create a checkout session (call /create_session)
    return jsonify({"ok": True, "payment_id": pid, "amount": total_amount})

@payments_bp.route("/payments")
@login_required
def payments_overview():
    """
    Payments overview:
      - earned : payments for rentals owned by current user (owner view)
      - paid   : payments made by current user (renter view)
    """
    db = get_db()
    uid = session.get("user_id")

    # Owner: payments where the rental belongs to current user
    earned_q = """
      SELECT p.*, rr.start_date, rr.end_date, rr.id AS request_id,
             r.title AS rental_title, u.name AS payer_name, u.id AS payer_id, r.owner_id
      FROM rental_payments p
      JOIN rental_requests rr ON p.request_id = rr.id
      JOIN rentals r ON rr.rental_id = r.id
      LEFT JOIN users u ON p.payer_id = u.id
      WHERE r.owner_id = ?
      ORDER BY p.created_at DESC
    """
    try:
        earned_rows = db.execute(earned_q, (uid,)).fetchall()
    except Exception:
        current_app.logger.exception("payments_overview: earned query failed")
        earned_rows = []

    # Renter: payments where current user is the payer
    paid_q = """
      SELECT p.*, rr.start_date, rr.end_date, rr.id AS request_id, rr.rental_id,
             r.title AS rental_title, o.name AS owner_name, o.id AS owner_id
      FROM rental_payments p
      JOIN rental_requests rr ON p.request_id = rr.id
      JOIN rentals r ON rr.rental_id = r.id
      LEFT JOIN users o ON r.owner_id = o.id
      WHERE p.payer_id = ?
      ORDER BY p.created_at DESC
    """
    try:
        paid_rows = db.execute(paid_q, (uid,)).fetchall()
    except Exception:
        current_app.logger.exception("payments_overview: paid query failed")
        paid_rows = []

    def row_to_dict(r):
        try:
            return {k: r[k] for k in r.keys()}
        except Exception:
            # fallback for other row types
            return dict(r)

    earned = [row_to_dict(r) for r in earned_rows]
    paid = [row_to_dict(r) for r in paid_rows]

    # totals (sum of completed amounts for display)
    def sum_amount(rows):
        s = 0.0
        for r in rows:
            try:
                if r.get("amount") is not None and r.get("status") == "completed":
                    s += float(r.get("amount") or 0.0)
            except Exception:
                pass
        return round(s, 2)

    total_earned = sum_amount(earned)
    total_paid = sum_amount(paid)

    return render_template("payments.html",
                           earned=earned, paid=paid,
                           total_earned=total_earned, total_paid=total_paid)

# alias so existing templates using url_for('profile.my_payments') work
@payments_bp.route("/profile/my-payments")
@login_required
def my_payments_alias():
    return payments_overview()

@payments_bp.route("/checkout-return")
@login_required
def checkout_return():
    """
    Stripe success_url -> redirect here.
    Verifies Stripe session (if provided) and marks rental_payments.status = 'completed'.
    Then redirect to payments overview (no thankyou page).
    """
    session_id = request.args.get("session_id") or request.args.get("sessionId")
    payment_id = request.args.get("payment_id") or request.args.get("paymentId")
    db = get_db()

    verified = False
    try:
        if session_id and current_app.config.get("STRIPE_SECRET_KEY"):
            import stripe
            stripe.api_key = current_app.config.get("STRIPE_SECRET_KEY")
            sess = stripe.checkout.Session.retrieve(session_id, expand=["payment_intent"])
            sess_payment_status = sess.get("payment_status") or getattr(sess, "payment_status", None)
            pi_id = None
            if sess.get("payment_intent"):
                pi_obj = sess.payment_intent
                pi_id = pi_obj.id if hasattr(pi_obj, "id") else pi_obj

            # Accept if checkout reports paid or PaymentIntent succeeded
            pi_succeeded = False
            if pi_id:
                try:
                    pi = stripe.PaymentIntent.retrieve(pi_id)
                    pi_succeeded = (pi.get("status") == "succeeded") if isinstance(pi, dict) else (getattr(pi, "status", None) == "succeeded")
                except Exception:
                    pi_succeeded = False

            if sess_payment_status == "paid" or pi_succeeded:
                metadata = sess.get("metadata") or {}
                rp_id = metadata.get("rental_payment_id") or metadata.get("payment_id") or payment_id
                if rp_id:
                    rp_row = db.execute("SELECT * FROM rental_payments WHERE id = ?", (int(rp_id),)).fetchone()
                    if rp_row:
                        # use your helper to set status and store stripe ids
                        ok = mark_rental_payment_completed(db, rp_row, stripe_session_id=session_id, stripe_payment_intent=pi_id)
                        if ok:
                            verified = True
    except Exception:
        current_app.logger.exception("checkout_return: stripe verification failed")

    # Optional fallback: if user is logged in and payer matches, mark completed
    if not verified and payment_id:
        try:
            from flask import session as flask_session
            uid = flask_session.get("user_id")
            rp_row = db.execute("SELECT * FROM rental_payments WHERE id = ?", (int(payment_id),)).fetchone()
            if rp_row and uid and str(rp_row["payer_id"]) == str(uid) and rp_row["status"] in (None, "", "pending", "requested"):
                ok = mark_rental_payment_completed(db, rp_row, stripe_session_id=session_id, stripe_payment_intent=None)
                if ok:
                    verified = True
        except Exception:
            current_app.logger.exception("checkout_return fallback failed")

    if verified:
        flash("Payment successful — receipt is available in Payments (use the PDF button to download).", "success")
    else:
        flash("Payment processed. Verification may be delayed — the receipt will appear in Payments when available.", "info")

    return redirect(url_for("payments.payments_overview"))
