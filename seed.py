"""
Seed script to populate the database with demo data.
Run: python seed.py
"""
from werkzeug.security import generate_password_hash
from supabase_client import get_supabase_admin_client
from config import Config

db = get_supabase_admin_client()


def seed():
    print("🌱 Seeding database...")

    # 1. Create admin
    print("  → Creating admin account...")
    admin_hash = generate_password_hash(Config.ADMIN_PASSWORD)
    try:
        db.table("admins").upsert({
            "username": Config.ADMIN_USERNAME,
            "password_hash": admin_hash,
            "name": "Super Admin",
        }, on_conflict="username").execute()
    except Exception as e:
        print(f"    Admin may already exist: {e}")

    # 2. Create stores
    print("  → Creating stores...")
    stores = [
        {"store_id": "S001", "store_name": "EV Hub - Koramangala", "address": "123 Main Rd, Koramangala, Bangalore", "contact_number": "9876543210"},
        {"store_id": "S002", "store_name": "EV Hub - Indiranagar", "address": "45 CMH Rd, Indiranagar, Bangalore", "contact_number": "9876543211"},
        {"store_id": "S003", "store_name": "EV Hub - Whitefield", "address": "78 ITPL Main Rd, Whitefield, Bangalore", "contact_number": "9876543212"},
    ]
    for store in stores:
        try:
            db.table("stores").upsert(store, on_conflict="store_id").execute()
        except Exception as e:
            print(f"    Store {store['store_id']} error: {e}")

    # 3. Create employees
    print("  → Creating employees...")
    employees = [
        {"name": "Rahul Kumar", "store_id": "S001", "username": "rahul", "password_hash": generate_password_hash("emp123"), "phone": "9111111111"},
        {"name": "Priya Sharma", "store_id": "S002", "username": "priya", "password_hash": generate_password_hash("emp123"), "phone": "9222222222"},
        {"name": "Amit Patel", "store_id": "S003", "username": "amit", "password_hash": generate_password_hash("emp123"), "phone": "9333333333"},
    ]
    for emp in employees:
        try:
            db.table("employees").upsert(emp, on_conflict="username").execute()
        except Exception as e:
            print(f"    Employee {emp['username']} error: {e}")

    # 4. Create bikes
    print("  → Creating bikes...")
    bikes = [
        # Store S001
        {"bike_number": "BK001", "bike_model": "Ather 450X", "bike_type": "Electric Scooter", "store_id": "S001", "daily_price": 299, "weekly_price": 1499, "monthly_price": 4999, "status": "available"},
        {"bike_number": "BK002", "bike_model": "Ola S1 Pro", "bike_type": "Electric Scooter", "store_id": "S001", "daily_price": 349, "weekly_price": 1799, "monthly_price": 5999, "status": "available"},
        {"bike_number": "BK003", "bike_model": "TVS iQube", "bike_type": "Electric Scooter", "store_id": "S001", "daily_price": 249, "weekly_price": 1299, "monthly_price": 3999, "status": "available"},
        {"bike_number": "BK004", "bike_model": "Revolt RV400", "bike_type": "Electric Motorcycle", "store_id": "S001", "daily_price": 399, "weekly_price": 2099, "monthly_price": 6999, "status": "maintenance"},
        # Store S002
        {"bike_number": "BK005", "bike_model": "Ather 450X", "bike_type": "Electric Scooter", "store_id": "S002", "daily_price": 299, "weekly_price": 1499, "monthly_price": 4999, "status": "available"},
        {"bike_number": "BK006", "bike_model": "Bajaj Chetak", "bike_type": "Electric Scooter", "store_id": "S002", "daily_price": 349, "weekly_price": 1799, "monthly_price": 5999, "status": "available"},
        {"bike_number": "BK007", "bike_model": "Hero Vida V1", "bike_type": "Electric Scooter", "store_id": "S002", "daily_price": 279, "weekly_price": 1399, "monthly_price": 4499, "status": "available"},
        # Store S003
        {"bike_number": "BK008", "bike_model": "Ola S1 Air", "bike_type": "Electric Scooter", "store_id": "S003", "daily_price": 199, "weekly_price": 999, "monthly_price": 2999, "status": "available"},
        {"bike_number": "BK009", "bike_model": "Simple One", "bike_type": "Electric Scooter", "store_id": "S003", "daily_price": 349, "weekly_price": 1799, "monthly_price": 5999, "status": "available"},
        {"bike_number": "BK010", "bike_model": "Ultraviolette F77", "bike_type": "Electric Motorcycle", "store_id": "S003", "daily_price": 599, "weekly_price": 2999, "monthly_price": 9999, "status": "available"},
    ]
    for bike in bikes:
        try:
            db.table("bikes").upsert(bike, on_conflict="bike_number").execute()
        except Exception as e:
            print(f"    Bike {bike['bike_number']} error: {e}")

    # 5. Create demo users
    print("  → Creating demo users...")
    users = [
        {"name": "Karthik R", "phone": "9876500001", "email": "karthik@test.com", "password_hash": generate_password_hash("user123"), "is_first_login": True},
        {"name": "Sneha M", "phone": "9876500002", "email": "sneha@test.com", "password_hash": generate_password_hash("user123"), "is_first_login": True},
    ]
    for user in users:
        try:
            existing = db.table("users").select("id").eq("phone", user["phone"]).execute()
            if not existing.data:
                db.table("users").insert(user).execute()
        except Exception as e:
            print(f"    User {user['name']} error: {e}")

    print("\n✅ Seeding complete!")

    # 6. Seed deposit config
    print("  → Setting up deposit config...")
    try:
        existing = db.table("deposit_config").select("id").execute()
        if not existing.data:
            db.table("deposit_config").insert({"required_amount": 2000.00}).execute()
    except Exception as e:
        print(f"    Deposit config error: {e}")

    print("\n📋 Demo Credentials:")
    print("  Admin:    username=admin, password=admin123")
    print("  Employee: store_id=S001, username=rahul, password=emp123")
    print("  Employee: store_id=S002, username=priya, password=emp123")
    print("  User:     login=karthik@test.com, password=user123")
    print("  User:     login=9876500002, password=user123")


if __name__ == "__main__":
    seed()
