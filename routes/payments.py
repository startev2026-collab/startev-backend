import os
import hashlib
import time
import re
import uuid

from flask import Blueprint, request, jsonify, redirect
from flask_jwt_extended import jwt_required, get_jwt
from supabase_client import get_supabase_admin_client

payments_bp = Blueprint("payments", __name__)
db = get_supabase_admin_client()

PAYU_MERCHANT_KEY = os.environ.get("PAYU_MERCHANT_KEY", "DfBuMo")
PAYU_SALT = os.environ.get("PAYU_SALT", "Fr8sL4n35BF6fs0rGBjtveZJJ3quEJ3b")
PAYU_ENV = os.environ.get("PAYU_ENV", "sandbox")
PAYU_BASE_URL = "https://test.payu.in/_payment" if PAYU_ENV == "sandbox" else "https://secure.payu.in/_payment"


def generate_payu_hash(txnid, amount, productinfo, firstname, email, udf1="", udf2="", udf3="", udf4="", udf5=""):
    hash_string = f"{PAYU_MERCHANT_KEY}|{txnid}|{amount}|{productinfo}|{firstname}|{email}|{udf1}|{udf2}|{udf3}|{udf4}|{udf5}||||||{PAYU_SALT}"
    return hashlib.sha512(hash_string.encode()).hexdigest()


def verify_payu_response(data):
    expected = f"{PAYU_SALT}|{data.get('status', '')}||||||{data.get('udf5', '')}|{data.get('udf4', '')}|{data.get('udf3', '')}|{data.get('udf2', '')}|{data.get('udf1', '')}|{data.get('email', '')}|{data.get('firstname', '')}|{data.get('productinfo', '')}|{data.get('amount', '')}|{data.get('txnid', '')}|{PAYU_MERCHANT_KEY}"
    return hashlib.sha512(expected.encode()).hexdigest() == data.get("hash", "")


@payments_bp.route("", methods=["GET"])
@jwt_required()
def list_payments():
    """Admin: list all payments."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    store_id = request.args.get("store_id")

    query = db.table("payments").select(
        "*, users(name, phone), rentals(rental_plan, store_id, start_date, expiry_date)"
    )

    result = query.order("payment_date", desc=True).execute()

    payments = result.data
    if store_id:
        payments = [p for p in payments if p.get("rentals", {}).get("store_id") == store_id]

    return jsonify({"payments": payments})


@payments_bp.route("/create-order", methods=["POST"])
@jwt_required()
def create_order():
    """Generate PayU payment hash and return form params."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 401

    user_id = claims["user_id"]

    data = request.get_json()
    payment_type = data.get("payment_type", "rental")

    if payment_type not in ("deposit", "renewal"):
        active = (
            db.table("rentals")
            .select("id")
            .eq("user_id", user_id)
            .eq("rental_status", "active")
            .execute()
        )
        if active.data:
            return jsonify({
                "error": "Please return your currently rented bike before renting another bike.",
                "has_active_rental": True
            }), 409

    amount = float(data.get("amount", 0))
    if amount < 1.00:
        return jsonify({"error": "Minimum amount is 1 INR"}), 400

    try:
        user_res = db.table("users").select("email, phone, name").eq("id", user_id).execute()
        if not user_res.data:
            return jsonify({"error": "User not found"}), 404
        user_info = user_res.data[0]

        user_phone = user_info.get("phone") or "9999999999"
        user_phone = re.sub(r'\D', '', user_phone)
        if len(user_phone) > 10:
            user_phone = user_phone[-10:]
        elif len(user_phone) < 10:
            user_phone = "9999999999"

        user_email = user_info.get("email") or "user@example.com"
        user_name = user_info.get("name") or "User"

        txnid = f"T{int(time.time() * 1000)}{uuid.uuid4().hex[:6].upper()}"
        productinfo = f"EV Bike Rental - {payment_type.capitalize()}"
        udf1 = payment_type

        hash_value = generate_payu_hash(txnid, amount, productinfo, user_name, user_email, udf1)

        origin = request.headers.get("Origin") or "http://localhost:5173"
        backend_url = os.environ.get("BACKEND_URL", "https://startev-backend.onrender.com")
        surl = f"{backend_url}/api/payments/callback?origin={origin}"
        furl = f"{backend_url}/api/payments/callback?origin={origin}"

        return jsonify({
            "txnid": txnid,
            "amount": str(amount),
            "productinfo": productinfo,
            "firstname": user_name,
            "email": user_email,
            "phone": user_phone,
            "hash": hash_value,
            "key": PAYU_MERCHANT_KEY,
            "surl": surl,
            "furl": furl,
            "action": PAYU_BASE_URL,
            "udf1": udf1,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@payments_bp.route("/verify-payment", methods=["POST"])
@jwt_required()
def verify_payment():
    """Verify PayU response hash."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    txnid = data.get("txnid", "")
    status = data.get("status", "")
    payu_hash = data.get("hash", "")

    if not txnid or not status or not payu_hash:
        return jsonify({"error": "Missing payment verification data"}), 400

    verified = verify_payu_response({
        "txnid": txnid,
        "status": status,
        "hash": payu_hash,
        "amount": data.get("amount", "0"),
        "productinfo": data.get("productinfo", ""),
        "firstname": data.get("firstname", ""),
        "email": data.get("email", ""),
        "udf1": data.get("udf1", ""),
        "udf2": data.get("udf2", ""),
        "udf3": data.get("udf3", ""),
        "udf4": data.get("udf4", ""),
        "udf5": data.get("udf5", ""),
    })

    if not verified or status != "success":
        return jsonify({"verified": False, "error": "Payment verification failed"}), 400

    return jsonify({
        "verified": True,
        "transaction_id": txnid,
        "message": "Payment verified successfully"
    })


@payments_bp.route("/callback", methods=["POST"])
def payment_callback():
    """Receive PayU POST callback and redirect to frontend."""
    data = request.form.to_dict()
    verified = verify_payu_response(data)

    if verified and data.get("status") == "success":
        status = "success"
    else:
        status = "failure"

    origin = request.args.get("origin") or "http://localhost:5173"
    redirect_url = (
        f"{origin}/payment-callback"
        f"?status={status}"
        f"&txnid={data.get('txnid', '')}"
        f"&amount={data.get('amount', '0')}"
        f"&payment_type={data.get('udf1', '')}"
        f"&productinfo={data.get('productinfo', '')}"
        f"&firstname={data.get('firstname', '')}"
        f"&email={data.get('email', '')}"
        f"&hash={data.get('hash', '')}"
        f"&udf1={data.get('udf1', '')}"
        f"&udf2={data.get('udf2', '')}"
        f"&udf3={data.get('udf3', '')}"
        f"&udf4={data.get('udf4', '')}"
        f"&udf5={data.get('udf5', '')}"
    )

    return redirect(redirect_url)
