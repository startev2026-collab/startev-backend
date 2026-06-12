from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from werkzeug.security import generate_password_hash
from supabase_client import get_supabase_admin_client

stores_bp = Blueprint("stores", __name__)
db = get_supabase_admin_client()


@stores_bp.route("", methods=["GET"])
def list_stores():
    """List all stores (public — used by user portal for store selection)."""
    result = db.table("stores").select("*").order("store_name").execute()
    return jsonify({"stores": result.data})


@stores_bp.route("/<int:store_id>", methods=["GET"])
def get_store(store_id):
    """Get a single store by its DB id."""
    result = db.table("stores").select("*").eq("id", store_id).execute()
    if not result.data:
        return jsonify({"error": "Store not found"}), 404
    return jsonify({"store": result.data[0]})


@stores_bp.route("", methods=["POST"])
@jwt_required()
def create_store():
    """Admin: create a new store."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    required = ["store_id", "store_name", "password"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    # Check duplicate store_id
    existing = db.table("stores").select("id").eq("store_id", data["store_id"]).execute()
    if existing.data:
        return jsonify({"error": "Store ID already exists"}), 409

    store_data = {
        "store_id": data["store_id"],
        "store_name": data["store_name"],
        "password_hash": generate_password_hash(data["password"]),
        "address": data.get("address", ""),
        "contact_number": data.get("contact_number", ""),
    }

    result = db.table("stores").insert(store_data).execute()

    # Audit log
    _log_action(claims.get("admin_id"), "create", "store", result.data[0]["id"], f"Created store {data['store_id']}")

    return jsonify({"store": result.data[0], "message": "Store created"}), 201


@stores_bp.route("/<int:store_id>", methods=["PUT"])
@jwt_required()
def update_store(store_id):
    """Admin: update a store."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    allowed = ["store_name", "address", "contact_number"]
    update_data = {k: v for k, v in data.items() if k in allowed and v}
    
    if "password" in data and data["password"]:
        update_data["password_hash"] = generate_password_hash(data["password"])

    if not update_data:
        return jsonify({"error": "No valid fields to update"}), 400

    result = db.table("stores").update(update_data).eq("id", store_id).execute()

    if not result.data:
        return jsonify({"error": "Store not found"}), 404

    _log_action(claims.get("admin_id"), "update", "store", store_id, f"Updated store fields: {list(update_data.keys())}")

    return jsonify({"store": result.data[0], "message": "Store updated"})


@stores_bp.route("/<int:store_id>", methods=["DELETE"])
@jwt_required()
def delete_store(store_id):
    """Admin: delete a store."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    # Get store info before deleting
    store_result = db.table("stores").select("store_id").eq("id", store_id).execute()
    if not store_result.data:
        return jsonify({"error": "Store not found"}), 404

    db.table("stores").delete().eq("id", store_id).execute()

    _log_action(claims.get("admin_id"), "delete", "store", store_id, f"Deleted store {store_result.data[0]['store_id']}")

    return jsonify({"message": "Store deleted"})


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
        pass  # Don't fail the main request if logging fails
