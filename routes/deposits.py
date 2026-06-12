from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from supabase_client import get_supabase_admin_client

deposits_bp = Blueprint("deposits", __name__)
db = get_supabase_admin_client()


def _get_required_amount():
    """Get the configured required deposit amount."""
    result = db.table("deposit_config").select("required_amount").limit(1).execute()
    if result.data:
        return float(result.data[0]["required_amount"])
    return 2000.00


def _get_deposit_status(balance, required):
    """Return a status string based on deposit balance vs required amount."""
    if balance >= required:
        return "verified"
    elif balance > 0:
        return "partial"
    else:
        return "pending"


@deposits_bp.route("/status", methods=["GET"])
@jwt_required()
def get_deposit_status():
    """User: Get own deposit status, balance, and required amount."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    required = _get_required_amount()

    user_result = db.table("users").select("deposit_balance").eq("id", user_id).execute()
    if not user_result.data:
        return jsonify({"error": "User not found"}), 404

    balance = float(user_result.data[0]["deposit_balance"] or 0)
    status = _get_deposit_status(balance, required)

    return jsonify({
        "deposit_balance": balance,
        "required_amount": required,
        "status": status,
        "is_verified": balance >= required,
    })


@deposits_bp.route("/config", methods=["GET"])
@jwt_required()
def get_config():
    """Any authenticated user: Get the required deposit amount."""
    required = _get_required_amount()
    return jsonify({"required_amount": required})


@deposits_bp.route("/config", methods=["PUT"])
@jwt_required()
def update_config():
    """Admin: Update the required deposit amount."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    amount = data.get("required_amount")
    if amount is None or float(amount) < 0:
        return jsonify({"error": "Valid required_amount is required"}), 400

    # Update existing config row
    config = db.table("deposit_config").select("id").limit(1).execute()
    if config.data:
        db.table("deposit_config").update({
            "required_amount": float(amount),
            "updated_at": "now()",
        }).eq("id", config.data[0]["id"]).execute()
    else:
        db.table("deposit_config").insert({
            "required_amount": float(amount),
        }).execute()

    # Audit log
    try:
        db.table("audit_logs").insert({
            "admin_id": claims.get("admin_id"),
            "action": "update_deposit_config",
            "entity_type": "deposit_config",
            "details": f"Required deposit amount updated to ₹{float(amount):.2f}",
        }).execute()
    except Exception:
        pass

    return jsonify({"message": "Deposit config updated", "required_amount": float(amount)})


@deposits_bp.route("/pay", methods=["POST"])
@jwt_required()
def pay_deposit():
    """
    User: Record a deposit payment.
    Body: { "amount": 2000, "transaction_id": "pay_xxx" }
    """
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    data = request.get_json()
    amount = float(data.get("amount", 0))
    transaction_id = data.get("transaction_id", "")

    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    # Update user's deposit balance
    user_result = db.table("users").select("deposit_balance").eq("id", user_id).execute()
    if not user_result.data:
        return jsonify({"error": "User not found"}), 404

    current_balance = float(user_result.data[0]["deposit_balance"] or 0)
    new_balance = current_balance + amount

    db.table("users").update({"deposit_balance": new_balance}).eq("id", user_id).execute()

    # Record transaction
    db.table("deposit_transactions").insert({
        "user_id": user_id,
        "amount": amount,
        "transaction_type": "deposit",
        "payment_status": "completed",
        "transaction_id": transaction_id,
        "performed_by_role": "user",
        "performed_by_id": user_id,
        "notes": "Security deposit payment",
    }).execute()

    required = _get_required_amount()
    status = _get_deposit_status(new_balance, required)

    return jsonify({
        "message": "Deposit recorded successfully",
        "deposit_balance": new_balance,
        "status": status,
        "is_verified": new_balance >= required,
    }), 201


@deposits_bp.route("/deduct", methods=["POST"])
@jwt_required()
def deduct_deposit():
    """
    Employee: Deduct from a user's deposit.
    Body: { "user_id": 1, "amount": 500, "notes": "Damage to bike" }
    """
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    target_user_id = data.get("user_id")
    amount = float(data.get("amount", 0))
    notes = data.get("notes", "")

    if not target_user_id or amount <= 0:
        return jsonify({"error": "user_id and positive amount are required"}), 400

    # Fetch user
    user_result = db.table("users").select("deposit_balance, name").eq("id", target_user_id).execute()
    if not user_result.data:
        return jsonify({"error": "User not found"}), 404

    current_balance = float(user_result.data[0]["deposit_balance"] or 0)
    if amount > current_balance:
        return jsonify({"error": f"Deduction amount (₹{amount}) exceeds deposit balance (₹{current_balance})"}), 400

    new_balance = current_balance - amount
    db.table("users").update({"deposit_balance": new_balance}).eq("id", target_user_id).execute()

    # Get numeric store ID to satisfy BIGINT constraint
    store_res = db.table("stores").select("id").eq("store_id", claims.get("store_id")).execute()
    store_numeric_id = store_res.data[0]["id"] if store_res.data else None

    # Record transaction
    db.table("deposit_transactions").insert({
        "user_id": target_user_id,
        "amount": -amount,
        "transaction_type": "deduction",
        "payment_status": "completed",
        "performed_by_role": "employee",
        "performed_by_id": store_numeric_id,
        "notes": notes,
    }).execute()

    return jsonify({
        "message": f"₹{amount} deducted from {user_result.data[0]['name']}'s deposit",
        "new_balance": new_balance,
    })


@deposits_bp.route("/refund", methods=["POST"])
@jwt_required()
def refund_deposit():
    """
    Admin: Refund a user's deposit.
    Body: { "user_id": 1, "notes": "Account closure" }
    """
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    target_user_id = data.get("user_id")
    notes = data.get("notes", "Account closure refund")

    if not target_user_id:
        return jsonify({"error": "user_id is required"}), 400

    # Check for active rentals
    active = db.table("rentals").select("id").eq("user_id", target_user_id).eq("rental_status", "active").execute()
    if active.data:
        return jsonify({"error": "Cannot refund — user has active rentals"}), 400

    # Fetch user
    user_result = db.table("users").select("deposit_balance, name").eq("id", target_user_id).execute()
    if not user_result.data:
        return jsonify({"error": "User not found"}), 404

    refund_amount = float(user_result.data[0]["deposit_balance"] or 0)
    if refund_amount <= 0:
        return jsonify({"error": "No deposit to refund"}), 400

    # Zero out balance
    db.table("users").update({"deposit_balance": 0}).eq("id", target_user_id).execute()

    # Record transaction
    db.table("deposit_transactions").insert({
        "user_id": target_user_id,
        "amount": -refund_amount,
        "transaction_type": "refund",
        "payment_status": "completed",
        "performed_by_role": "admin",
        "performed_by_id": claims.get("admin_id"),
        "notes": notes,
    }).execute()

    # Audit log
    try:
        db.table("audit_logs").insert({
            "admin_id": claims.get("admin_id"),
            "action": "refund_deposit",
            "entity_type": "user",
            "entity_id": target_user_id,
            "details": f"Refunded ₹{refund_amount:.2f} to {user_result.data[0]['name']}. Reason: {notes}",
        }).execute()
    except Exception:
        pass

    return jsonify({
        "message": f"₹{refund_amount} refunded to {user_result.data[0]['name']}",
        "refund_amount": refund_amount,
    })


@deposits_bp.route("/transactions", methods=["GET"])
@jwt_required()
def get_own_transactions():
    """User: Get own deposit transactions."""
    claims = get_jwt()
    if claims.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403

    user_id = claims["user_id"]
    result = (
        db.table("deposit_transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return jsonify({"transactions": result.data})


@deposits_bp.route("/user/<int:user_id>", methods=["GET"])
@jwt_required()
def get_user_deposit(user_id):
    """Employee/Admin: View a user's deposit status + transactions."""
    claims = get_jwt()
    if claims.get("role") not in ("employee", "admin"):
        return jsonify({"error": "Unauthorized"}), 403

    user_result = db.table("users").select("id, name, phone, email, deposit_balance").eq("id", user_id).execute()
    if not user_result.data:
        return jsonify({"error": "User not found"}), 404

    user = user_result.data[0]
    balance = float(user["deposit_balance"] or 0)
    required = _get_required_amount()

    transactions = (
        db.table("deposit_transactions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return jsonify({
        "user": {
            "id": user["id"],
            "name": user["name"],
            "phone": user["phone"],
            "email": user["email"],
        },
        "deposit_balance": balance,
        "required_amount": required,
        "status": _get_deposit_status(balance, required),
        "is_verified": balance >= required,
        "transactions": transactions.data,
    })


@deposits_bp.route("/search-users", methods=["GET"])
@jwt_required()
def search_users():
    """Employee: Search users by phone or name for deposit management."""
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    query_str = request.args.get("q", "").strip()
    if not query_str or len(query_str) < 2:
        return jsonify({"users": []})

    # Search by phone (exact prefix) or name (ilike)
    by_phone = db.table("users").select("id, name, phone, email, deposit_balance").ilike("phone", f"%{query_str}%").limit(10).execute()
    by_name = db.table("users").select("id, name, phone, email, deposit_balance").ilike("name", f"%{query_str}%").limit(10).execute()

    # Merge and deduplicate
    seen = set()
    users = []
    for u in by_phone.data + by_name.data:
        if u["id"] not in seen:
            seen.add(u["id"])
            balance = float(u["deposit_balance"] or 0)
            required = _get_required_amount()
            u["deposit_status"] = _get_deposit_status(balance, required)
            users.append(u)

    return jsonify({"users": users[:15]})


@deposits_bp.route("/store-users", methods=["GET"])
@jwt_required()
def get_store_users_with_deposits():
    """Employee: Get users who have active rentals at the employee's store, with deposit info."""
    claims = get_jwt()
    if claims.get("role") != "employee":
        return jsonify({"error": "Unauthorized"}), 403

    store_id = claims.get("store_id")

    # Get active rentals for this store
    rentals = (
        db.table("rentals")
        .select("user_id, users(id, name, phone, email, deposit_balance)")
        .eq("store_id", store_id)
        .eq("rental_status", "active")
        .execute()
    )

    seen = set()
    users = []
    required = _get_required_amount()
    for r in rentals.data:
        u = r.get("users")
        if u and u["id"] not in seen:
            seen.add(u["id"])
            balance = float(u["deposit_balance"] or 0)
            u["deposit_status"] = _get_deposit_status(balance, required)
            u["deposit_balance"] = balance
            users.append(u)

    return jsonify({"users": users})


@deposits_bp.route("/all-transactions", methods=["GET"])
@jwt_required()
def get_all_transactions():
    """Admin: Get all deposit transactions with user info."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    tx_type = request.args.get("type")  # deposit, deduction, refund

    query = db.table("deposit_transactions").select("*, users(name, phone, email)")

    if tx_type:
        query = query.eq("transaction_type", tx_type)

    result = query.order("created_at", desc=True).limit(200).execute()
    return jsonify({"transactions": result.data})


@deposits_bp.route("/summary", methods=["GET"])
@jwt_required()
def get_deposit_summary():
    """Admin: Get summary stats for deposits."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    all_tx = db.table("deposit_transactions").select("amount, transaction_type").execute()

    total_deposits = sum(float(t["amount"]) for t in all_tx.data if t["transaction_type"] == "deposit")
    total_deductions = sum(abs(float(t["amount"])) for t in all_tx.data if t["transaction_type"] == "deduction")
    total_refunds = sum(abs(float(t["amount"])) for t in all_tx.data if t["transaction_type"] == "refund")

    # Count users with verified deposits
    required = _get_required_amount()
    all_users = db.table("users").select("deposit_balance").execute()
    verified_count = sum(1 for u in all_users.data if float(u["deposit_balance"] or 0) >= required)
    pending_count = sum(1 for u in all_users.data if float(u["deposit_balance"] or 0) < required)

    return jsonify({
        "total_deposits": total_deposits,
        "total_deductions": total_deductions,
        "total_refunds": total_refunds,
        "net_held": total_deposits - total_deductions - total_refunds,
        "verified_users": verified_count,
        "pending_users": pending_count,
        "required_amount": required,
    })
