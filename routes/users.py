from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from supabase_client import get_supabase_admin_client

users_bp = Blueprint("users", __name__)
db = get_supabase_admin_client()


def require_role(*roles):
    """Check that the current JWT has one of the specified roles."""
    claims = get_jwt()
    if claims.get("role") not in roles:
        return False
    return True


@users_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    """Get current user's profile."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    result = db.table("users").select("*").eq("id", user_id).execute()

    if not result.data:
        return jsonify({"error": "User not found"}), 404

    user = result.data[0]
    user.pop("password_hash", None)
    return jsonify({"user": user})


@users_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    """Update current user's profile."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    data = request.get_json()

    # Fields that users can update
    allowed_fields = [
        "name", "phone", "email", "current_address", "permanent_address",
        "alt_phone", "dob", "father_name", "purpose", "platform_id",
    ]
    update_data = {k: v for k, v in data.items() if k in allowed_fields and v is not None}

    if not update_data:
        return jsonify({"error": "No valid fields to update"}), 400

    result = db.table("users").update(update_data).eq("id", user_id).execute()

    if result.data:
        user = result.data[0]
        user.pop("password_hash", None)
        return jsonify({"user": user, "message": "Profile updated"})

    return jsonify({"error": "Update failed"}), 500


@users_bp.route("/rentals", methods=["GET"])
@jwt_required()
def get_user_rentals():
    """Get all rentals for the current user."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    status = request.args.get("status")  # active, expired, returned

    query = db.table("rentals").select("*, bikes(bike_number, bike_model, image_url), stores(store_name)").eq("user_id", user_id)

    if status:
        query = query.eq("rental_status", status)

    result = query.order("created_at", desc=True).execute()
    return jsonify({"rentals": result.data})


@users_bp.route("/payments", methods=["GET"])
@jwt_required()
def get_user_payments():
    """Get all payments for the current user."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    result = (
        db.table("payments")
        .select("*, rentals(rental_plan, start_date, expiry_date)")
        .eq("user_id", user_id)
        .order("payment_date", desc=True)
        .execute()
    )
    return jsonify({"payments": result.data})


@users_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def get_user_dashboard():
    """Get dashboard data for current user."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]

    # Get active rentals (include bike pricing for renewal)
    active_rentals = (
        db.table("rentals")
        .select("*, bikes(bike_number, bike_model, image_url, daily_price, weekly_price, monthly_price), stores(store_name)")
        .eq("user_id", user_id)
        .eq("rental_status", "active")
        .execute()
    )

    # Get expired rentals (for renewal / fine display)
    expired_rentals = (
        db.table("rentals")
        .select("*, bikes(bike_number, bike_model, image_url, daily_price, weekly_price, monthly_price), stores(store_name)")
        .eq("user_id", user_id)
        .eq("rental_status", "expired")
        .execute()
    )

    # Get cancelled rentals
    cancelled_rentals = (
        db.table("rentals")
        .select("*, bikes(bike_number, bike_model, image_url), stores(store_name)")
        .eq("user_id", user_id)
        .eq("rental_status", "cancelled_by_admin")
        .execute()
    )

    # Get rental count
    all_rentals = db.table("rentals").select("id").eq("user_id", user_id).execute()

    # Get user info
    user_result = db.table("users").select("is_first_login, name, deposit_balance").eq("id", user_id).execute()
    user = user_result.data[0] if user_result.data else {}

    # Get deposit config
    deposit_config = db.table("deposit_config").select("required_amount").limit(1).execute()
    required_deposit = float(deposit_config.data[0]["required_amount"]) if deposit_config.data else 2000.00
    deposit_balance = float(user.get("deposit_balance") or 0)

    # Get fine settings
    settings_res = db.table("system_settings").select("*").execute()
    settings = {s["setting_key"]: s["setting_value"] for s in settings_res.data} if settings_res.data else {}

    return jsonify({
        "active_rentals": active_rentals.data,
        "expired_rentals": expired_rentals.data,
        "cancelled_rentals": cancelled_rentals.data,
        "total_rentals": len(all_rentals.data),
        "is_first_login": user.get("is_first_login", True),
        "name": user.get("name", ""),
        "deposit_balance": deposit_balance,
        "required_deposit": required_deposit,
        "deposit_verified": deposit_balance >= required_deposit,
        "fine_settings": {
            "default_fine_amount": float(settings.get("default_fine_amount", 300)),
            "fine_system_enabled": settings.get("fine_system_enabled", "true") == "true"
        }
    })

