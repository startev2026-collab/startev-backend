import os
import razorpay
import hmac
import hashlib

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from supabase_client import get_supabase_admin_client

payments_bp = Blueprint("payments", __name__)
db = get_supabase_admin_client()

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

    # Filter by store_id if provided (needs post-query filter due to nested join)
    payments = result.data
    if store_id:
        payments = [p for p in payments if p.get("rentals", {}).get("store_id") == store_id]

    return jsonify({"payments": payments})


@payments_bp.route("/create-order", methods=["POST"])
@jwt_required()
def create_order():
    """
    Create a Razorpay order.
    """
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 401

    user_id = claims["user_id"]

    # Block order creation if user already has an active rental
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
    currency = data.get("currency", "INR")
    receipt = data.get("receipt", "receipt_01")
    
    amount_paise = int(amount * 100)
    if amount_paise < 100:
        return jsonify({"error": "Minimum amount is 100 paise (1 INR)"}), 400

    try:
        razorpay_client = razorpay.Client(
            auth=(os.environ.get("RAZORPAY_KEY_ID"), os.environ.get("RAZORPAY_KEY_SECRET"))
        )
        
        order_data = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt
        }
        order = razorpay_client.order.create(data=order_data)
        
        return jsonify({
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@payments_bp.route("/verify-payment", methods=["POST"])
@jwt_required()
def verify_payment():
    """
    Verify payment completion via Razorpay signature.
    """
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_signature = data.get("razorpay_signature")
    
    if not razorpay_payment_id or not razorpay_order_id or not razorpay_signature:
        return jsonify({"error": "Missing signature fields"}), 400
        
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    sig_msg = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected_sig = hmac.new(
        secret.encode(),
        sig_msg.encode(),
        hashlib.sha256
    ).hexdigest()
    
    if hmac.compare_digest(expected_sig, razorpay_signature):
        # In production, mark payment as paid in DB
        return jsonify({
            "verified": True,
            "transaction_id": razorpay_payment_id,
            "message": "Payment verified successfully"
        })
    else:
        return jsonify({"error": "Signature mismatch"}), 400
