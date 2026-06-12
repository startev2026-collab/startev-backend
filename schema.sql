-- ============================================================
-- Bike Rental Management System — Supabase Database Schema
-- Run this SQL in your Supabase SQL Editor to create all tables
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. USERS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(20) UNIQUE,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    purpose VARCHAR(100),                          -- blinkit, zepto, instamart, personal
    platform_id VARCHAR(100),                      -- delivery platform ID if applicable
    selfie_url TEXT,                                -- Cloudinary URL
    id_proof_type VARCHAR(50),                     -- aadhar, pan, driving_licence, electricity_bill
    id_proof_url TEXT,                              -- Cloudinary URL
    alt_phone VARCHAR(20),
    dob DATE,
    permanent_address TEXT,
    current_address TEXT,
    father_name VARCHAR(255),
    is_first_login BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 2. STORES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS stores (
    id BIGSERIAL PRIMARY KEY,
    store_id VARCHAR(50) UNIQUE NOT NULL,
    store_name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    address TEXT,
    contact_number VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Employees table removed (using shared store login)

-- ============================================================
-- 4. ADMINS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS admins (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) DEFAULT 'Admin',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 5. BIKES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS bikes (
    id BIGSERIAL PRIMARY KEY,
    bike_number VARCHAR(50) UNIQUE NOT NULL,
    bike_model VARCHAR(255) NOT NULL,
    bike_type VARCHAR(100),
    store_id VARCHAR(50) NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    daily_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    weekly_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    monthly_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    status VARCHAR(50) DEFAULT 'available',         -- available, rented, maintenance
    image_url TEXT,                                  -- Cloudinary URL
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 6. RENTALS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS rentals (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bike_id BIGINT NOT NULL REFERENCES bikes(id) ON DELETE CASCADE,
    store_id VARCHAR(50) NOT NULL REFERENCES stores(store_id) ON DELETE CASCADE,
    rental_plan VARCHAR(20) NOT NULL,               -- daily, weekly, monthly
    start_date DATE NOT NULL,
    expiry_date DATE NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    payment_status VARCHAR(50) DEFAULT 'pending',    -- pending, completed, failed
    rental_status VARCHAR(50) DEFAULT 'active',      -- active, expired, returned
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 7. PAYMENTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    rental_id BIGINT NOT NULL REFERENCES rentals(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount DECIMAL(10, 2) NOT NULL,
    payment_method VARCHAR(50),                      -- online, cash, upi
    transaction_id VARCHAR(255) UNIQUE,
    payment_date TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 8. AUDIT LOGS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    admin_id BIGINT,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),                         -- store, bike, employee, rental
    entity_id BIGINT,
    details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INDEXES for performance
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_bikes_store_id ON bikes(store_id);
CREATE INDEX IF NOT EXISTS idx_bikes_status ON bikes(status);
-- (Employee indexes removed)
CREATE INDEX IF NOT EXISTS idx_rentals_user_id ON rentals(user_id);
CREATE INDEX IF NOT EXISTS idx_rentals_bike_id ON rentals(bike_id);
CREATE INDEX IF NOT EXISTS idx_rentals_store_id ON rentals(store_id);
CREATE INDEX IF NOT EXISTS idx_rentals_status ON rentals(rental_status);
CREATE INDEX IF NOT EXISTS idx_payments_rental_id ON payments(rental_id);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_admin_id ON audit_logs(admin_id);
