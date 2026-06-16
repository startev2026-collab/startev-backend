import json
import concurrent.futures
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from werkzeug.security import generate_password_hash
from supabase_client import get_supabase_admin_client
from cloudinary_utils import upload_image

employees_bp = Blueprint("employees", __name__)
db = get_supabase_admin_client()



@employees_bp.route("/register-user", methods=["POST"])
@jwt_required()
def register_user():
    """
    Employee: register a new user (customer) with full details.
    Accepts multipart/form-data for file uploads.
    """
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    # Handle both JSON and form data
    if request.content_type and "multipart/form-data" in request.content_type:
        data = request.form.to_dict()
    else:
        data = request.get_json()

    required = ["name", "phone", "password"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    # Check duplicate phone
    existing = db.table("users").select("id").eq("phone", data["phone"]).execute()
    if existing.data:
        return jsonify({"error": "Phone number already registered"}), 409

    if data.get("email"):
        existing = db.table("users").select("id").eq("email", data["email"]).execute()
        if existing.data:
            return jsonify({"error": "Email already registered"}), 409

    # Prepare all upload tasks to run concurrently
    upload_tasks = []

    if request.files.get("selfie"):
        upload_tasks.append({
            "type": "selfie",
            "file": request.files["selfie"].read(),
            "folder": "bike_rental/selfies"
        })

    id_proof_count = int(data.get("id_proof_count", 0))
    for i in range(id_proof_count):
        file = request.files.get(f"id_proof_{i}")
        doc_type = data.get(f"id_proof_type_{i}", "")
        is_verified = data.get(f"id_proof_verified_{i}", "false") == "true"

        if file and doc_type:
            upload_tasks.append({
                "type": "id_proof",
                "doc_type": doc_type,
                "is_verified": is_verified,
                "file": file.read(),
                "folder": "bike_rental/id_proofs"
            })

    # Fallback: handle legacy single id_proof upload
    if id_proof_count == 0 and request.files.get("id_proof"):
        upload_tasks.append({
            "type": "id_proof",
            "doc_type": data.get("id_proof_type", ""),
            "is_verified": True,
            "file": request.files["id_proof"].read(),
            "folder": "bike_rental/id_proofs"
        })

    def upload_worker(task):
        res = upload_image(task["file"], folder=task["folder"])
        task["url"] = res["url"]
        return task

    selfie_url = ""
    id_documents = []
    verified_type = ""

    if upload_tasks:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                results = list(executor.map(upload_worker, upload_tasks))
        except Exception as e:
            return jsonify({"error": f"Failed to upload registration documents: {str(e)}"}), 500
            
        for res in results:
            if res["type"] == "selfie":
                selfie_url = res["url"]
            elif res["type"] == "id_proof":
                doc = {
                    "type": res["doc_type"],
                    "url": res["url"],
                    "is_verified_original": res["is_verified"],
                }
                id_documents.append(doc)
                if res["is_verified"]:
                    verified_type = res["doc_type"]

    user_data = {
        "name": data["name"],
        "phone": data["phone"],
        "email": data.get("email") or None,
        "password_hash": generate_password_hash(data["password"]),
        "purpose": data.get("purpose", ""),
        "platform_id": data.get("platform_id", ""),
        "selfie_url": selfie_url,
        "id_proof_type": verified_type,
        "id_proof_url": json.dumps(id_documents) if id_documents else "",
        "alt_phone": data.get("alt_phone", ""),
        "dob": data.get("dob") or None,
        "permanent_address": data.get("permanent_address", ""),
        "current_address": data.get("current_address", ""),
        "father_name": data.get("father_name", ""),
        "is_first_login": True,
    }

    result = db.table("users").insert(user_data).execute()
    user = result.data[0]
    
    # Log the registration action associated with the store
    store_id = claims.get("store_id")
    _log_action(
        admin_id=None,
        action="register_customer",
        entity_type="user",
        entity_id=user["id"],
        details=store_id
    )

    user.pop("password_hash", None)
    return jsonify({"user": user, "message": "User registered successfully"}), 201


@employees_bp.route("/store-bikes", methods=["GET"])
@jwt_required()
def get_store_bikes():
    """Employee: get all bikes for their assigned store."""
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    store_id = claims.get("store_id")
    status = request.args.get("status")

    query = db.table("bikes").select("*").eq("store_id", store_id)
    if status:
        query = query.eq("status", status)

    result = query.order("bike_number").execute()
    return jsonify({"bikes": result.data})


@employees_bp.route("/store-rentals", methods=["GET"])
@jwt_required()
def get_store_rentals():
    """Employee: get all rentals for their assigned store."""
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    store_id = claims.get("store_id")
    status = request.args.get("status")

    query = (
        db.table("rentals")
        .select("*, users(name, phone, email), bikes(bike_number, bike_model)")
        .eq("store_id", store_id)
    )
    if status:
        query = query.eq("rental_status", status)

    result = query.order("created_at", desc=True).execute()
    return jsonify({"rentals": result.data})


@employees_bp.route("/store-users", methods=["GET"])
@jwt_required()
def get_store_users():
    """Employee: get all users that belong to their store (either registered here or have rented here)."""
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    store_id = claims.get("store_id")

    # Get users registered at this store via the store_id field on the user record
    store_users = db.table("users").select("*").eq("store_id", store_id).order("created_at", desc=True).execute()

    # Also get user_ids from audit_logs registered by this store (fallback for older records)
    registrations = (
        db.table("audit_logs")
        .select("entity_id")
        .eq("action", "register_customer")
        .eq("entity_type", "user")
        .eq("details", store_id)
        .execute()
    )
    registered_user_ids = [r["entity_id"] for r in registrations.data]

    # Combine: users already from store_id field + any from audit_logs not yet included
    store_user_ids = {u["id"] for u in store_users.data}
    extra_ids = [uid for uid in registered_user_ids if uid not in store_user_ids]

    extra_users = []
    if extra_ids:
        extra_result = db.table("users").select("*").in_("id", extra_ids).order("created_at", desc=True).execute()
        extra_users = extra_result.data

    users = store_users.data + extra_users
    for user in users:
        user.pop("password_hash", None)

    return jsonify({"users": users})


@employees_bp.route("/store-stats", methods=["GET"])
@jwt_required()
def get_store_stats():
    """Employee: get statistics for their store."""
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    store_id = claims.get("store_id")

    # Bike counts by status
    all_bikes = db.table("bikes").select("status").eq("store_id", store_id).execute()
    available = sum(1 for b in all_bikes.data if b["status"] == "available")
    rented = sum(1 for b in all_bikes.data if b["status"] == "rented")
    maintenance = sum(1 for b in all_bikes.data if b["status"] == "maintenance")

    # Active rentals count
    active_rentals = (
        db.table("rentals").select("id")
        .eq("store_id", store_id)
        .eq("rental_status", "active")
        .execute()
    )

    # 1. Total Deposit for this store (sum of deposit balance for store customers)
    rentals = db.table("rentals").select("user_id").eq("store_id", store_id).execute()
    rental_user_ids = [r["user_id"] for r in rentals.data]

    registrations = (
        db.table("audit_logs")
        .select("entity_id")
        .eq("action", "register_customer")
        .eq("entity_type", "user")
        .eq("details", store_id)
        .execute()
    )
    registered_user_ids = [r["entity_id"] for r in registrations.data]
    user_ids = list(set(rental_user_ids + registered_user_ids))

    total_deposit = 0.0
    if user_ids:
        users = db.table("users").select("deposit_balance").in_("id", user_ids).execute()
        total_deposit = sum(float(u["deposit_balance"] or 0) for u in users.data)

    # 2. Total Rental Revenue for this store (completed payments)
    completed_rentals = (
        db.table("rentals")
        .select("amount")
        .eq("store_id", store_id)
        .eq("payment_status", "completed")
        .execute()
    )
    total_revenue = sum(float(r["amount"]) for r in completed_rentals.data)

    return jsonify({
        "total_bikes": len(all_bikes.data),
        "available_bikes": available,
        "rented_bikes": rented,
        "maintenance_bikes": maintenance,
        "active_rentals": len(active_rentals.data),
        "total_deposit": total_deposit,
        "total_revenue": total_revenue,
    })


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
