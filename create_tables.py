"""
Create tables in Supabase using the Management API.
Run: python create_tables.py
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# Use the PostgREST RPC endpoint to run SQL
# We'll use supabase's built-in pg_catalog for this
# Actually, let's use the management API endpoint for SQL

# Extract project ref from URL
project_ref = SUPABASE_URL.replace("https://", "").replace(".supabase.co", "")

SQL = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(20) UNIQUE,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    purpose VARCHAR(100),
    platform_id VARCHAR(100),
    selfie_url TEXT,
    id_proof_type VARCHAR(50),
    id_proof_url TEXT,
    alt_phone VARCHAR(20),
    dob DATE,
    permanent_address TEXT,
    current_address TEXT,
    father_name VARCHAR(255),
    is_first_login BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stores (
    id BIGSERIAL PRIMARY KEY,
    store_id VARCHAR(50) UNIQUE NOT NULL,
    store_name VARCHAR(255) NOT NULL,
    address TEXT,
    contact_number VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS employees (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    store_id VARCHAR(50) NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admins (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) DEFAULT 'Admin',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bikes (
    id BIGSERIAL PRIMARY KEY,
    bike_number VARCHAR(50) UNIQUE NOT NULL,
    bike_model VARCHAR(255) NOT NULL,
    bike_type VARCHAR(100),
    store_id VARCHAR(50) NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    daily_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    weekly_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    monthly_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    status VARCHAR(50) DEFAULT 'available',
    image_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rentals (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bike_id BIGINT NOT NULL REFERENCES bikes(id) ON DELETE CASCADE,
    store_id VARCHAR(50) NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    rental_plan VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL,
    expiry_date DATE NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    payment_status VARCHAR(50) DEFAULT 'pending',
    rental_status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    rental_id BIGINT NOT NULL REFERENCES rentals(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount DECIMAL(10, 2) NOT NULL,
    payment_method VARCHAR(50),
    transaction_id VARCHAR(255) UNIQUE,
    payment_date TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    admin_id BIGINT,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id BIGINT,
    details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bikes_store_id ON bikes(store_id);
CREATE INDEX IF NOT EXISTS idx_bikes_status ON bikes(status);
CREATE INDEX IF NOT EXISTS idx_employees_store_id ON employees(store_id);
CREATE INDEX IF NOT EXISTS idx_rentals_user_id ON rentals(user_id);
CREATE INDEX IF NOT EXISTS idx_rentals_bike_id ON rentals(bike_id);
CREATE INDEX IF NOT EXISTS idx_rentals_store_id ON rentals(store_id);
CREATE INDEX IF NOT EXISTS idx_rentals_status ON rentals(rental_status);
CREATE INDEX IF NOT EXISTS idx_payments_rental_id ON payments(rental_id);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_admin_id ON audit_logs(admin_id);
"""

def create_tables():
    """Execute SQL via Supabase's PostgREST RPC or raw SQL endpoint."""
    # Method: Use the database's REST API with service role key
    # The pg/query endpoint on supabase allows raw SQL with the service key
    url = f"{SUPABASE_URL}/rest/v1/rpc/"
    
    # Alternative: Use the SQL endpoint directly
    # Supabase exposes a SQL endpoint for service role
    sql_url = f"https://{project_ref}.supabase.co/pg/query"
    
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    
    # Try the pg/query endpoint first
    try:
        response = httpx.post(
            sql_url,
            json={"query": SQL},
            headers=headers,
            timeout=30,
        )
        if response.status_code == 200:
            print("✅ Tables created successfully via pg/query!")
            return True
        else:
            print(f"pg/query returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"pg/query failed: {e}")
    
    # Fallback: Try to create tables one at a time using individual statements
    print("\nTrying individual table creation via RPC...")
    
    # We can't run DDL via PostgREST directly, so let's guide the user
    print("\n" + "=" * 60)
    print("MANUAL STEP REQUIRED:")
    print("=" * 60)
    print("Please run the schema.sql file in your Supabase SQL Editor:")
    print(f"  1. Go to: https://supabase.com/dashboard/project/{project_ref}/sql/new")
    print("  2. Copy & paste the contents of backend/schema.sql")
    print("  3. Click 'Run'")
    print("=" * 60)
    return False


if __name__ == "__main__":
    result = create_tables()
    if not result:
        print("\nAfter creating tables manually, run: python seed.py")
