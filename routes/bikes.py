from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from supabase_client import get_supabase_admin_client

bikes_bp = Blueprint("bikes", __name__)
db = get_supabase_admin_client()


@bikes_bp.route("", methods=["GET"])
def list_bikes():
    """
    List bikes, optionally filtered by store_id and status.
    Query params: ?store_id=X&status=available
    """
    store_id = request.args.get("store_id")
    status = request.args.get("status")

    query = db.table("bikes").select("*, stores(store_name)")

    if store_id:
        query = query.eq("store_id", store_id)
    if status:
        query = query.eq("status", status)

    result = query.order("bike_number").execute()
    return jsonify({"bikes": result.data})


@bikes_bp.route("/<int:bike_id>", methods=["GET"])
def get_bike(bike_id):
    """Get a single bike."""
    result = db.table("bikes").select("*, stores(store_name)").eq("id", bike_id).execute()
    if not result.data:
        return jsonify({"error": "Bike not found"}), 404
    return jsonify({"bike": result.data[0]})


@bikes_bp.route("", methods=["POST"])
@jwt_required()
def create_bike():
    """Admin: add a new bike."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    required = ["bike_number", "bike_model", "store_id", "daily_price", "weekly_price", "monthly_price"]
    for field in required:
        if not data.get(field) and data.get(field) != 0:
            return jsonify({"error": f"{field} is required"}), 400

    # Check duplicate bike_number
    existing = db.table("bikes").select("id").eq("bike_number", data["bike_number"]).execute()
    if existing.data:
        return jsonify({"error": "Bike number already exists"}), 409

    # Verify store exists
    store = db.table("stores").select("id").eq("store_id", data["store_id"]).execute()
    if not store.data:
        return jsonify({"error": "Store not found"}), 404

    bike_data = {
        "bike_number": data["bike_number"],
        "bike_model": data["bike_model"],
        "bike_type": data.get("bike_type", ""),
        "store_id": data["store_id"],
        "daily_price": float(data["daily_price"]),
        "weekly_price": float(data["weekly_price"]),
        "monthly_price": float(data["monthly_price"]),
        "status": data.get("status", "available"),
        "image_url": data.get("image_url", ""),
    }

    result = db.table("bikes").insert(bike_data).execute()

    # Audit log
    _log_action(claims.get("admin_id"), "create", "bike", result.data[0]["id"],
                f"Added bike {data['bike_number']} to store {data['store_id']}")

    return jsonify({"bike": result.data[0], "message": "Bike added"}), 201


@bikes_bp.route("/<int:bike_id>", methods=["PUT"])
@jwt_required()
def update_bike(bike_id):
    """Admin: update a bike."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    allowed = ["bike_model", "bike_type", "store_id", "daily_price", "weekly_price",
               "monthly_price", "status", "image_url"]
    update_data = {}
    for k in allowed:
        if k in data:
            if k in ("daily_price", "weekly_price", "monthly_price"):
                update_data[k] = float(data[k])
            else:
                update_data[k] = data[k]

    if not update_data:
        return jsonify({"error": "No valid fields to update"}), 400

    result = db.table("bikes").update(update_data).eq("id", bike_id).execute()

    if not result.data:
        return jsonify({"error": "Bike not found"}), 404

    _log_action(claims.get("admin_id"), "update", "bike", bike_id,
                f"Updated bike fields: {list(update_data.keys())}")

    return jsonify({"bike": result.data[0], "message": "Bike updated"})


@bikes_bp.route("/<int:bike_id>", methods=["DELETE"])
@jwt_required()
def delete_bike(bike_id):
    """Admin: delete a bike."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    bike_result = db.table("bikes").select("bike_number").eq("id", bike_id).execute()
    if not bike_result.data:
        return jsonify({"error": "Bike not found"}), 404

    # Check if bike has active rentals
    active = db.table("rentals").select("id").eq("bike_id", bike_id).eq("rental_status", "active").execute()
    if active.data:
        return jsonify({"error": "Cannot delete bike with active rentals"}), 409

    db.table("bikes").delete().eq("id", bike_id).execute()

    _log_action(claims.get("admin_id"), "delete", "bike", bike_id,
                f"Deleted bike {bike_result.data[0]['bike_number']}")

    return jsonify({"message": "Bike deleted"})


def _log_action(admin_id, action, entity_type, entity_id, details):
    """Write an audit log entry."""
    try:
        db.table("audit_logs").insert({
            "admin_id": admin_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
        }).execute()
    except Exception:
        pass
