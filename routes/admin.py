import io
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt
from supabase_client import get_supabase_admin_client

admin_bp = Blueprint("admin", __name__)
db = get_supabase_admin_client()


@admin_bp.route("/users", methods=["GET"])
@jwt_required()
def get_all_users():
    """Admin: get all users with their documents."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    result = db.table("users").select("*").order("created_at", desc=True).execute()
    # Remove password_hash from the response for security
    users = result.data
    for user in users:
        user.pop("password_hash", None)
    
    return jsonify({"users": users})


@admin_bp.route("/analytics", methods=["GET"])
@jwt_required()
def get_analytics():
    """Admin: get dashboard analytics."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    # Counts
    users = db.table("users").select("id", count="exact").execute()
    stores = db.table("stores").select("id", count="exact").execute()
    bikes = db.table("bikes").select("id, status", count="exact").execute()

    available = sum(1 for b in bikes.data if b["status"] == "available")
    rented = sum(1 for b in bikes.data if b["status"] == "rented")
    maintenance = sum(1 for b in bikes.data if b["status"] == "maintenance")

    # Total Deposit: real-time sum of all users' deposit_balance
    all_users = db.table("users").select("deposit_balance").execute()
    total_deposit = sum(float(u["deposit_balance"] or 0) for u in all_users.data)

    # Total Rental Revenue: sum of rental amounts only (no deposit money)
    all_rentals = db.table("rentals").select("amount, payment_status").execute()
    total_rental_revenue = sum(
        float(r["amount"]) for r in all_rentals.data
        if r.get("payment_status") == "completed"
    )

    # Active rentals
    active_rentals = db.table("rentals").select("id").eq("rental_status", "active").execute()

    return jsonify({
        "total_users": users.count or len(users.data),
        "total_employees": stores.count or len(stores.data),
        "total_stores": stores.count or len(stores.data),
        "total_bikes": bikes.count or len(bikes.data),
        "available_bikes": available,
        "rented_bikes": rented,
        "maintenance_bikes": maintenance,
        "active_rentals": len(active_rentals.data),
        "total_deposit": total_deposit,
        "total_rental_revenue": total_rental_revenue,
    })


@admin_bp.route("/store-revenue", methods=["GET"])
@jwt_required()
def get_store_revenue():
    """Admin: get revenue breakdown by store."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    rentals = db.table("rentals").select("store_id, amount, payment_status").execute()
    stores = db.table("stores").select("store_id, store_name").execute()

    store_names = {s["store_id"]: s["store_name"] for s in stores.data}

    revenue_map = {}
    for r in rentals.data:
        sid = r["store_id"]
        if sid not in revenue_map:
            revenue_map[sid] = {"store_id": sid, "store_name": store_names.get(sid, sid), "revenue": 0, "rentals": 0}
        if r.get("payment_status") == "completed":
            revenue_map[sid]["revenue"] += float(r["amount"])
        revenue_map[sid]["rentals"] += 1

    return jsonify({"store_revenue": list(revenue_map.values())})


@admin_bp.route("/monthly-revenue", methods=["GET"])
@jwt_required()
def get_monthly_revenue():
    """Admin: get revenue by month for charts."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    payments = db.table("payments").select("amount, payment_date").order("payment_date").execute()

    monthly = {}
    for p in payments.data:
        month_key = p.get("payment_date", "")[:7]  # YYYY-MM
        if month_key:
            if month_key not in monthly:
                monthly[month_key] = 0
            monthly[month_key] += float(p["amount"])

    chart_data = [{"month": k, "revenue": v} for k, v in sorted(monthly.items())]
    return jsonify({"monthly_revenue": chart_data})


@admin_bp.route("/audit-logs", methods=["GET"])
@jwt_required()
def get_audit_logs():
    """Admin: get audit logs."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    limit = int(request.args.get("limit", 100))
    result = db.table("audit_logs").select("*").order("created_at", desc=True).limit(limit).execute()
    return jsonify({"logs": result.data})


@admin_bp.route("/export/rentals", methods=["GET"])
@jwt_required()
def export_rentals_excel():
    """Admin: export rentals to Excel."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    try:
        from openpyxl import Workbook

        rentals = db.table("rentals").select(
            "*, users(name, phone), bikes(bike_number, bike_model), stores(store_name)"
        ).order("created_at", desc=True).execute()

        wb = Workbook()
        ws = wb.active
        ws.title = "Rentals"

        # Header
        headers = ["ID", "User", "Phone", "Bike Number", "Bike Model", "Store",
                    "Plan", "Start Date", "Expiry Date", "Amount", "Payment Status", "Rental Status"]
        ws.append(headers)

        for r in rentals.data:
            ws.append([
                r["id"],
                r.get("users", {}).get("name", ""),
                r.get("users", {}).get("phone", ""),
                r.get("bikes", {}).get("bike_number", ""),
                r.get("bikes", {}).get("bike_model", ""),
                r.get("stores", {}).get("store_name", ""),
                r["rental_plan"],
                r["start_date"],
                r["expiry_date"],
                float(r["amount"]),
                r["payment_status"],
                r["rental_status"],
            ])

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"rentals_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ImportError:
        return jsonify({"error": "openpyxl not installed"}), 500


@admin_bp.route("/export/revenue-pdf", methods=["GET"])
@jwt_required()
def export_revenue_pdf():
    """Admin: export revenue report to PDF."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        # Get data
        payments = db.table("payments").select("amount, payment_date").execute()
        total_revenue = sum(float(p["amount"]) for p in payments.data)

        rentals = db.table("rentals").select("store_id, amount, payment_status").execute()
        stores = db.table("stores").select("store_id, store_name").execute()
        store_names = {s["store_id"]: s["store_name"] for s in stores.data}

        # Build PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph("Revenue Report", styles["Title"]))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
        elements.append(Spacer(1, 20))
        elements.append(Paragraph(f"Total Revenue: ₹{total_revenue:,.2f}", styles["Heading2"]))
        elements.append(Spacer(1, 20))

        # Store-wise table
        table_data = [["Store", "Revenue", "Total Rentals"]]
        revenue_map = {}
        for r in rentals.data:
            sid = r["store_id"]
            if sid not in revenue_map:
                revenue_map[sid] = {"revenue": 0, "count": 0}
            if r.get("payment_status") == "completed":
                revenue_map[sid]["revenue"] += float(r["amount"])
            revenue_map[sid]["count"] += 1

        for sid, data in revenue_map.items():
            table_data.append([
                store_names.get(sid, sid),
                f"₹{data['revenue']:,.2f}",
                str(data["count"]),
            ])

        table = Table(table_data, colWidths=[200, 150, 100])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ]))
        elements.append(table)

        doc.build(elements)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"revenue_report_{datetime.now().strftime('%Y%m%d')}.pdf",
            mimetype="application/pdf",
        )
    except ImportError:
        return jsonify({"error": "reportlab not installed"}), 500


@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@jwt_required()
def delete_user(user_id):
    """Admin: delete a user."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    try:
        # Check if the user has any active or expired rentals (meaning they haven't returned the bike yet)
        active_rentals = db.table("rentals").select("id").eq("user_id", user_id).in_("rental_status", ["active", "expired"]).execute()
        if active_rentals.data:
            return jsonify({"error": "Cannot delete customer with active or expired rentals. Please mark the rentals as returned first."}), 409

        db.table("users").delete().eq("id", user_id).execute()
        return jsonify({"message": "User deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to delete user: {str(e)}"}), 500


@admin_bp.route("/settings", methods=["GET"])
@jwt_required()
def get_settings():
    """Admin: get system settings."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
        
    result = db.table("system_settings").select("*").execute()
    settings = {s["setting_key"]: s["setting_value"] for s in result.data}
    return jsonify({"settings": settings})


@admin_bp.route("/settings", methods=["POST"])
@jwt_required()
def update_settings():
    """Admin: update system settings."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.get_json()
    updates = []
    
    for key, value in data.items():
        if key in ["default_fine_amount", "fine_system_enabled"]:
            db.table("system_settings").upsert({"setting_key": key, "setting_value": str(value)}).execute()
            updates.append(key)
            
    return jsonify({"message": "Settings updated", "updated": updates})


@admin_bp.route("/fines", methods=["GET"])
@jwt_required()
def get_fines():
    """Admin: get overdue rentals and fine metrics."""
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403
        
    # Get overdue/expired rentals
    overdue_result = (
        db.table("rentals")
        .select("*, users(name, phone, email), bikes(bike_number, bike_model), stores(store_name)")
        .eq("rental_status", "expired")
        .order("expiry_date", desc=True)
        .execute()
    )
    overdue_rentals = overdue_result.data
    
    # Calculate collected fines from payments table
    payments_result = db.table("payments").select("amount").eq("payment_type", "renewal").execute()
    # Assuming renewal payments contain fine, but since we just store total_amount in renewal, we can't easily split it.
    # Actually, a better way to track collected fines is to sum the difference, but for simplicity we'll just return overdue rentals.
    
    total_outstanding_fines = sum(float(r.get("fine_amount", 0)) for r in overdue_rentals)
    users_with_fines = len(set(r["user_id"] for r in overdue_rentals if float(r.get("fine_amount", 0)) > 0))
    
    return jsonify({
        "overdue_rentals": overdue_rentals,
        "metrics": {
            "total_outstanding_fines": total_outstanding_fines,
            "users_with_fines": users_with_fines,
            "overdue_count": len(overdue_rentals)
        }
    })


