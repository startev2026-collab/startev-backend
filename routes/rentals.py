from datetime import date, timedelta, datetime, timezone
import math
import time
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from supabase_client import get_supabase_admin_client

rentals_bp = Blueprint("rentals", __name__)
db = get_supabase_admin_client()

PLAN_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


@rentals_bp.route("", methods=["POST"])
@jwt_required()
def create_rental():
    """
    Create a new rental after payment verification.
    Body: { "bike_id": 1, "store_id": "S001", "rental_plan": "daily|weekly|monthly",
            "payment_method": "online", "transaction_id": "TXN123" }
    """
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    data = request.get_json()

    required = ["bike_id", "store_id", "rental_plan"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    rental_plan = data["rental_plan"]
    if rental_plan not in PLAN_DAYS:
        return jsonify({"error": "Invalid rental plan. Use: daily, weekly, monthly"}), 400

    # Check if user already has an active rental
    active = (
        db.table("rentals")
        .select("id")
        .eq("user_id", user_id)
        .eq("rental_status", "active")
        .execute()
    )
    if active.data:
        return jsonify({"error": "You already have an active rental. Return it first."}), 409

    # Check deposit balance
    deposit_config = db.table("deposit_config").select("required_amount").limit(1).execute()
    required_deposit = float(deposit_config.data[0]["required_amount"]) if deposit_config.data else 2000.00

    user_deposit = db.table("users").select("deposit_balance").eq("id", user_id).execute()
    deposit_balance = float(user_deposit.data[0]["deposit_balance"] or 0) if user_deposit.data else 0

    if deposit_balance < required_deposit:
        return jsonify({
            "error": "A refundable security deposit of ₹{:,.0f} is required before renting a bike. Please complete the deposit payment to continue.".format(required_deposit),
            "deposit_required": True,
            "required_amount": required_deposit,
            "current_balance": deposit_balance,
        }), 403

    # Verify bike exists and is available
    bike_result = db.table("bikes").select("*").eq("id", data["bike_id"]).execute()
    if not bike_result.data:
        return jsonify({"error": "Bike not found"}), 404

    bike = bike_result.data[0]
    if bike["status"] != "available":
        return jsonify({"error": "Bike is not available"}), 409
    if bike["store_id"] != data["store_id"]:
        return jsonify({"error": "Bike does not belong to the specified store"}), 400

    # Calculate amount and dates
    price_key = f"{rental_plan}_price"
    amount = float(bike[price_key])
    
    start_str = data.get("start_date")
    if start_str:
        try:
            start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        except ValueError:
            start = datetime.now(timezone.utc)
    else:
        start = datetime.now(timezone.utc)
        
    expiry = start + timedelta(days=PLAN_DAYS[rental_plan])

    # Create rental
    rental_data = {
        "user_id": user_id,
        "bike_id": data["bike_id"],
        "store_id": data["store_id"],
        "rental_plan": rental_plan,
        "start_date": start.isoformat(),
        "expiry_date": expiry.isoformat(),
        "amount": amount,
        "payment_status": "completed",
        "rental_status": "active",
        "fine_amount": 0,
        "renewal_count": 0
    }

    rental_result = db.table("rentals").insert(rental_data).execute()
    rental = rental_result.data[0]

    # Create payment record
    payment_data = {
        "rental_id": rental["id"],
        "user_id": user_id,
        "amount": amount,
        "payment_method": data.get("payment_method", "online"),
        "transaction_id": data.get("transaction_id", f"TXN-{rental['id']}-{start.isoformat()}"),
        "payment_type": "rental"
    }
    db.table("payments").insert(payment_data).execute()

    # Update bike status to rented
    db.table("bikes").update({"status": "rented"}).eq("id", data["bike_id"]).execute()

    # Mark user as no longer first login
    db.table("users").update({"is_first_login": False}).eq("id", user_id).execute()

    return jsonify({
        "rental": rental,
        "message": "Bike rented successfully!",
    }), 201


@rentals_bp.route("", methods=["GET"])
@jwt_required()
def list_rentals():
    """Admin: list all rentals with filters."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    status = request.args.get("status")
    store_id = request.args.get("store_id")

    query = db.table("rentals").select(
        "*, users(name, phone, email), bikes(bike_number, bike_model), stores(store_name)"
    )

    if status:
        query = query.eq("rental_status", status)
    if store_id:
        query = query.eq("store_id", store_id)

    result = query.order("created_at", desc=True).execute()
    return jsonify({"rentals": result.data})


@rentals_bp.route("/<int:rental_id>/return", methods=["PUT"])
@jwt_required()
def return_bike(rental_id):
    """Return a rented bike (user, employee, or admin can do this)."""
    claims = get_jwt()
    role = claims.get("role")

    rental_result = db.table("rentals").select("*").eq("id", rental_id).execute()
    if not rental_result.data:
        return jsonify({"error": "Rental not found"}), 404

    rental = rental_result.data[0]

    # Authorization checks
    if role == "user" and rental["user_id"] != claims.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 403
    if role == "employee" and rental["store_id"] != claims.get("store_id"):
        return jsonify({"error": "Unauthorized"}), 403

    if rental["rental_status"] not in ["active", "expired"]:
        return jsonify({"error": "Rental is not active or expired"}), 400

    # Update rental status and clear equipment
    db.table("rentals").update({
        "rental_status": "returned",
        "battery_number": "",
        "charger_number": ""
    }).eq("id", rental_id).execute()

    # Update bike status back to available
    db.table("bikes").update({"status": "available"}).eq("id", rental["bike_id"]).execute()

    return jsonify({"message": "Bike returned successfully"})


@rentals_bp.route("/<int:rental_id>/cancel", methods=["PUT"])
@jwt_required()
def cancel_rental(rental_id):
    """Admin: Cancel a rental and mark bike as available."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    rental_result = db.table("rentals").select("*").eq("id", rental_id).execute()
    if not rental_result.data:
        return jsonify({"error": "Rental not found"}), 404

    rental = rental_result.data[0]

    if rental["rental_status"] not in ["active"]:
        return jsonify({"error": f"Cannot cancel a rental with status {rental['rental_status']}"}), 400

    # Update rental status
    db.table("rentals").update({"rental_status": "cancelled_by_admin"}).eq("id", rental_id).execute()

    # Update bike status back to available
    db.table("bikes").update({"status": "available"}).eq("id", rental["bike_id"]).execute()

    return jsonify({"message": "Rental cancelled successfully"})


@rentals_bp.route("/check-expired", methods=["POST"])
def check_expired_rentals():
    """
    Utility endpoint to mark expired rentals and calculate fines.
    Can be called by a cron job or manually.
    """
    now_utc = datetime.now(timezone.utc)
    
    # Fetch settings with retry to handle WinError 10035
    settings_res = None
    for attempt in range(3):
        try:
            settings_res = db.table("system_settings").select("*").execute()
            break
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(0.5)
            
    settings = {s["setting_key"]: s["setting_value"] for s in settings_res.data}
    
    if settings.get("fine_system_enabled") != "true":
        return jsonify({"message": "Fine system is disabled"})
        
    base_fine = float(settings.get("default_fine_amount", 300))

    # Find active or expired rentals past their expiry date
    rentals = (
        db.table("rentals")
        .select("*")
        .in_("rental_status", ["active", "expired"])
        .lt("expiry_date", now_utc.isoformat())
        .execute()
    )

    count = 0
    for rental in rentals.data:
        expiry = datetime.fromisoformat(rental["expiry_date"].replace('Z', '+00:00'))
        hours_passed = (now_utc - expiry).total_seconds() / 3600
        
        if hours_passed > 0:
            # Immediate fine + fine for every 24h
            fine = base_fine + math.floor(hours_passed / 24) * base_fine
            
            db.table("rentals").update({
                "rental_status": "expired",
                "fine_amount": fine,
                "fine_last_updated": now_utc.isoformat()
            }).eq("id", rental["id"]).execute()
            time.sleep(0.1)  # Fix WinError 10035 by adding a small delay between requests
            count += 1

    return jsonify({"message": f"Updated {count} expired rentals and calculated fines"})


@rentals_bp.route("/<int:rental_id>/renew", methods=["POST"])
@jwt_required()
def renew_rental(rental_id):
    """Renew an existing rental (expired or active)"""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403
        
    user_id = claims["user_id"]
    data = request.get_json()
    rental_plan = data.get("rental_plan")
    
    if not rental_plan or rental_plan not in PLAN_DAYS:
        return jsonify({"error": "Invalid rental plan"}), 400
        
    rental_result = db.table("rentals").select("*, bikes(daily_price, weekly_price, monthly_price)").eq("id", rental_id).execute()
    if not rental_result.data:
        return jsonify({"error": "Rental not found"}), 404
        
    rental = rental_result.data[0]
    if rental["user_id"] != user_id:
        return jsonify({"error": "Unauthorized"}), 403
        
    if rental["rental_status"] not in ["active", "expired"]:
        return jsonify({"error": "Only active or expired rentals can be renewed"}), 400
        
    # Calculate amount
    bike = rental["bikes"]
    price_key = f"{rental_plan}_price"
    plan_amount = float(bike[price_key])
    fine_amount = float(rental.get("fine_amount") or 0)
    
    total_amount = plan_amount + (fine_amount if rental["rental_status"] == "expired" else 0)
    
    # Calculate new dates
    start_str = data.get("start_date")
    now_utc = datetime.now(timezone.utc)
    
    if rental["rental_status"] == "expired":
        new_start = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if start_str else now_utc
    else:
        existing_expiry = datetime.fromisoformat(rental["expiry_date"].replace('Z', '+00:00'))
        new_start = existing_expiry
        
    new_expiry = new_start + timedelta(days=PLAN_DAYS[rental_plan])
    
    # Update rental
    update_data = {
        "rental_plan": rental_plan,
        "start_date": new_start.isoformat(),
        "expiry_date": new_expiry.isoformat(),
        "amount": plan_amount,
        "rental_status": "active",
        "fine_amount": 0,
        "renewal_count": int(rental.get("renewal_count") or 0) + 1
    }
    
    db.table("rentals").update(update_data).eq("id", rental_id).execute()
    
    # Record payment
    payment_data = {
        "rental_id": rental["id"],
        "user_id": user_id,
        "amount": total_amount,
        "payment_method": data.get("payment_method", "online"),
        "transaction_id": data.get("transaction_id", f"TXN-RENEW-{rental['id']}-{now_utc.timestamp()}"),
        "payment_type": "renewal"
    }
    db.table("payments").insert(payment_data).execute()
    
    # If the bike was marked available by some error, fix it
    db.table("bikes").update({"status": "rented"}).eq("id", rental["bike_id"]).execute()
    
    
    return jsonify({"message": "Rental renewed successfully", "rental": update_data})


@rentals_bp.route("/<int:rental_id>/equipment", methods=["PUT"])
@jwt_required()
def update_equipment(rental_id):
    """Employee: Update battery and charger numbers for an active rental."""
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    rental_result = db.table("rentals").select("*").eq("id", rental_id).execute()
    if not rental_result.data:
        return jsonify({"error": "Rental not found"}), 404

    rental = rental_result.data[0]
    if rental["store_id"] != claims.get("store_id"):
        return jsonify({"error": "Unauthorized"}), 403

    if rental["rental_status"] != "active":
        return jsonify({"error": "Can only update equipment on active rentals"}), 400

    data = request.get_json()
    battery_number = data.get("battery_number", "")
    charger_number = data.get("charger_number", "")

    # Update rental
    db.table("rentals").update({
        "battery_number": battery_number,
        "charger_number": charger_number
    }).eq("id", rental_id).execute()

    return jsonify({
        "message": "Equipment details updated successfully",
        "battery_number": battery_number,
        "charger_number": charger_number
    })
