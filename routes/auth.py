from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash
from supabase_client import get_supabase_admin_client

auth_bp = Blueprint("auth", __name__)
db = get_supabase_admin_client()


@auth_bp.route("/user/login", methods=["POST"])
def user_login():
    """
    User login via email, phone, or username.
    Body: { "login": "email/phone", "password": "..." }
    """
    data = request.get_json()
    login_id = data.get("login", "").strip()
    password = data.get("password", "")

    if not login_id or not password:
        return jsonify({"error": "Login ID and password are required"}), 400

    # Try email first, then phone
    user = None
    result = db.table("users").select("*").eq("email", login_id).execute()
    if result.data:
        user = result.data[0]
    else:
        result = db.table("users").select("*").eq("phone", login_id).execute()
        if result.data:
            user = result.data[0]

    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(
        identity=str(user["id"]),
        additional_claims={"role": "user", "user_id": user["id"]},
    )

    return jsonify({
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "phone": user["phone"],
            "is_first_login": user.get("is_first_login", True),
            "selfie_url": user.get("selfie_url"),
        },
        "role": "user",
    })


@auth_bp.route("/employee/login", methods=["POST"])
def employee_login():
    """
    Store login with store_id + password.
    Body: { "store_id": "...", "password": "..." }
    """
    data = request.get_json()
    store_id = data.get("store_id", "").strip()
    password = data.get("password", "")

    if not store_id or not password:
        return jsonify({"error": "Store ID and password are required"}), 400

    result = (
        db.table("stores")
        .select("*")
        .eq("store_id", store_id)
        .execute()
    )

    if not result.data:
        return jsonify({"error": "Invalid credentials"}), 401

    store = result.data[0]

    if not check_password_hash(store["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(
        identity=str(store["id"]),
        additional_claims={
            "role": "employee",
            "store_id": store["store_id"],
        },
    )

    return jsonify({
        "token": token,
        "employee": {
            "store_id": store["store_id"],
            "name": store["store_name"],
        },
        "role": "employee",
    })


@auth_bp.route("/admin/login", methods=["POST"])
def admin_login():
    """
    Admin login with username + password.
    Body: { "username": "...", "password": "..." }
    """
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    result = db.table("admins").select("*").eq("username", username).execute()

    if not result.data:
        return jsonify({"error": "Invalid credentials"}), 401

    admin = result.data[0]

    if not check_password_hash(admin["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(
        identity=str(admin["id"]),
        additional_claims={"role": "admin", "admin_id": admin["id"]},
    )

    return jsonify({
        "token": token,
        "admin": {
            "id": admin["id"],
            "name": admin["name"],
            "username": admin["username"],
        },
        "role": "admin",
    })


@auth_bp.route("/user/register", methods=["POST"])
def user_register():
    """
    Public user self-registration.
    Body: { "name": "...", "email": "...", "phone": "...", "password": "..." }
    """
    data = request.get_json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    password = data.get("password", "")

    if not name or not password:
        return jsonify({"error": "Name and password are required"}), 400
    if not email and not phone:
        return jsonify({"error": "Email or phone is required"}), 400

    # Check duplicates
    if email:
        existing = db.table("users").select("id").eq("email", email).execute()
        if existing.data:
            return jsonify({"error": "Email already registered"}), 409
    if phone:
        existing = db.table("users").select("id").eq("phone", phone).execute()
        if existing.data:
            return jsonify({"error": "Phone already registered"}), 409

    password_hash = generate_password_hash(password)

    result = (
        db.table("users")
        .insert({
            "name": name,
            "email": email or None,
            "phone": phone or None,
            "password_hash": password_hash,
            "is_first_login": True,
        })
        .execute()
    )

    user = result.data[0]
    token = create_access_token(
        identity=str(user["id"]),
        additional_claims={"role": "user", "user_id": user["id"]},
    )

    return jsonify({
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "phone": user["phone"],
            "is_first_login": True,
        },
        "role": "user",
    }), 201
