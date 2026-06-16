import os
import requests
import time
import re

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
    Create a Cashfree order.
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
    
    if amount < 1.00:
        return jsonify({"error": "Minimum amount is 1 INR"}), 400

    try:
        user_res = db.table("users").select("email, phone, name").eq("id", user_id).execute()
        if not user_res.data:
            return jsonify({"error": "User not found"}), 404
        user_info = user_res.data[0]
        
        user_phone = user_info.get("phone") or "9999999999"
        # clean phone number to contain only digits, max 10 digits
        user_phone = re.sub(r'\D', '', user_phone)
        if len(user_phone) > 10:
            user_phone = user_phone[-10:]
        elif len(user_phone) < 10:
            user_phone = "9999999999"
            
        user_email = user_info.get("email") or "user@example.com"
        user_name = user_info.get("name") or "User"

        app_id = os.environ.get("CASHFREE_APP_ID")
        secret_key = os.environ.get("CASHFREE_SECRET_KEY")
        env = os.environ.get("CASHFREE_ENV", "sandbox")
        
        if not app_id or not secret_key:
            return jsonify({"error": "Cashfree credentials not configured"}), 500
            
        base_url = "https://sandbox.cashfree.com/pg" if env == "sandbox" else "https://api.cashfree.com/pg"
        
        headers = {
            "x-client-id": app_id,
            "x-client-secret": secret_key,
            "x-api-version": "2023-08-01",
            "Content-Type": "application/json"
        }
        
        order_id = f"order_{int(time.time() * 1000)}"
        
        # Let's get the origin header for return_url
        origin = request.headers.get("Origin") or "http://localhost:5173"
        return_url = f"{origin}/dashboard?order_id={{order_id}}"
        
        payload = {
            "order_id": order_id,
            "order_amount": float(amount),
            "order_currency": currency,
            "customer_details": {
                "customer_id": str(user_id),
                "customer_email": user_email,
                "customer_phone": user_phone,
                "customer_name": user_name
            },
            "order_meta": {
                "return_url": return_url
            }
        }

        response = requests.post(f"{base_url}/orders", json=payload, headers=headers)
        if response.status_code != 200:
            return jsonify({"error": f"Failed to create order: {response.text}"}), response.status_code
            
        order_data = response.json()
        return jsonify({
            "order_id": order_data["order_id"],
            "payment_session_id": order_data["payment_session_id"],
            "amount": order_data["order_amount"],
            "currency": order_data["order_currency"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@payments_bp.route("/verify-payment", methods=["POST"])
@jwt_required()
def verify_payment():
    """
    Verify payment completion via Cashfree order status API.
    """
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 401

    user_id = claims["user_id"]
    data = request.get_json()
    order_id = data.get("order_id")
    
    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400
        
    app_id = os.environ.get("CASHFREE_APP_ID")
    secret_key = os.environ.get("CASHFREE_SECRET_KEY")
    env = os.environ.get("CASHFREE_ENV", "sandbox")
    
    if not app_id or not secret_key:
        return jsonify({"error": "Cashfree credentials not configured"}), 500
        
    base_url = "https://sandbox.cashfree.com/pg" if env == "sandbox" else "https://api.cashfree.com/pg"
    
    headers = {
        "x-client-id": app_id,
        "x-client-secret": secret_key,
        "x-api-version": "2023-08-01"
    }
    
    try:
        # 1. Fetch order details from Cashfree
        order_res = requests.get(f"{base_url}/orders/{order_id}", headers=headers)
        if order_res.status_code != 200:
            return jsonify({"error": f"Failed to fetch order: {order_res.text}"}), order_res.status_code
            
        order_data = order_res.json()
        
        # 2. Check if the payment status is PAID
        if order_data.get("order_status") != "PAID":
            return jsonify({"error": f"Payment not completed. Status: {order_data.get('order_status')}"}), 400
            
        # 3. Security Check: verify customer_id matches user_id
        customer_details = order_data.get("customer_details", {})
        if str(customer_details.get("customer_id")) != str(user_id):
            return jsonify({"error": "Security check failed: user ID mismatch"}), 403
            
        # 4. Fetch payments for this order to find the successful transaction ID
        payments_res = requests.get(f"{base_url}/orders/{order_id}/payments", headers=headers)
        transaction_id = order_id  # Default fallback
        if payments_res.status_code == 200:
            payments = payments_res.json()
            for payment in payments:
                if payment.get("payment_status") == "SUCCESS":
                    transaction_id = payment.get("cf_payment_id") or transaction_id
                    break
                    
        return jsonify({
            "verified": True,
            "transaction_id": transaction_id,
            "message": "Payment verified successfully"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

