-- Traffic Violation Detection + Evidence Audit System
-- PostgreSQL Schema
-- Run this once to create all tables

-- Enable UUID extension (optional, for future use)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────────────
-- ENUMS
-- ─────────────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'officer', 'citizen', 'reviewer', 'auditor');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE violation_type AS ENUM (
        'speeding', 'red_light', 'wrong_lane',
        'no_helmet', 'no_seatbelt', 'illegal_parking', 'other'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE violation_status AS ENUM (
        'pending', 'challan_issued', 'paid',
        'appealed', 'appeal_approved', 'appeal_rejected', 'cancelled'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE challan_status AS ENUM ('unpaid', 'paid', 'waived', 'under_appeal');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE appeal_status AS ENUM (
        'pending', 'under_review', 'approved', 'rejected', 'more_info_needed'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE decision_type AS ENUM ('approved', 'rejected', 'more_info_needed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ─────────────────────────────────────────────────────────────────────────────
-- TABLES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    email        VARCHAR(200) UNIQUE NOT NULL,
    phone        VARCHAR(20),
    password_hash VARCHAR(200) NOT NULL,
    role         user_role NOT NULL DEFAULT 'citizen',
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role  ON users(role);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS vehicles (
    id           SERIAL PRIMARY KEY,
    plate_number VARCHAR(20) UNIQUE NOT NULL,
    owner_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    model        VARCHAR(100),
    color        VARCHAR(50),
    vehicle_type VARCHAR(50) DEFAULT 'car',
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vehicles_plate ON vehicles(plate_number);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS violations (
    id               SERIAL PRIMARY KEY,
    vehicle_id       INTEGER NOT NULL REFERENCES vehicles(id),
    officer_id       INTEGER NOT NULL REFERENCES users(id),
    violation_type   violation_type NOT NULL,
    location         VARCHAR(300),
    latitude         FLOAT,
    longitude        FLOAT,
    speed_recorded   FLOAT,
    speed_limit      FLOAT,
    signal_status    VARCHAR(10),
    description      TEXT,
    status           violation_status DEFAULT 'pending',
    detection_method VARCHAR(50) DEFAULT 'manual',
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_violations_vehicle   ON violations(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_violations_officer   ON violations(officer_id);
CREATE INDEX IF NOT EXISTS idx_violations_status    ON violations(status);
CREATE INDEX IF NOT EXISTS idx_violations_type      ON violations(violation_type);
CREATE INDEX IF NOT EXISTS idx_violations_created   ON violations(created_at);
CREATE INDEX IF NOT EXISTS idx_violations_location  ON violations(location);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evidence (
    id           SERIAL PRIMARY KEY,
    violation_id INTEGER NOT NULL REFERENCES violations(id),
    file_name    VARCHAR(300) NOT NULL,
    file_url     VARCHAR(600),
    file_hash    CHAR(64) NOT NULL,    -- SHA-256 hex = 64 chars
    file_type    VARCHAR(10),           -- photo / video / doc
    file_size_kb FLOAT,
    uploaded_by  INTEGER NOT NULL REFERENCES users(id),
    is_deleted   BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_evidence_violation ON evidence(violation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_hash      ON evidence(file_hash);

-- ─────────────────────────────────────────────────────────────────────────────
-- Tamper-evident audit log: append-only, no updates/deletes allowed
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evidence_access_logs (
    id              SERIAL PRIMARY KEY,
    evidence_id     INTEGER NOT NULL REFERENCES evidence(id),
    accessed_by     INTEGER NOT NULL REFERENCES users(id),
    action          VARCHAR(30),   -- upload / view / download / verify / delete
    ip_address      VARCHAR(50),
    user_agent      VARCHAR(300),
    hash_at_access  CHAR(64),
    hash_verified   BOOLEAN,
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eal_evidence   ON evidence_access_logs(evidence_id);
CREATE INDEX IF NOT EXISTS idx_eal_user       ON evidence_access_logs(accessed_by);
CREATE INDEX IF NOT EXISTS idx_eal_action     ON evidence_access_logs(action);
CREATE INDEX IF NOT EXISTS idx_eal_created    ON evidence_access_logs(created_at);

-- Prevent any UPDATE or DELETE on this table to ensure tamper-evidence
-- (Application-level enforcement; DB-level can use triggers)
CREATE OR REPLACE FUNCTION prevent_eal_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Evidence access logs are immutable and cannot be modified or deleted.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_eal_update ON evidence_access_logs;
CREATE TRIGGER trg_prevent_eal_update
    BEFORE UPDATE OR DELETE ON evidence_access_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_eal_modification();

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS challans (
    id               SERIAL PRIMARY KEY,
    violation_id     INTEGER UNIQUE NOT NULL REFERENCES violations(id),
    challan_number   VARCHAR(30) UNIQUE NOT NULL,
    amount           FLOAT NOT NULL,
    status           challan_status DEFAULT 'unpaid',
    due_date         TIMESTAMP,
    payment_date     TIMESTAMP,
    payment_method   VARCHAR(50),
    payment_reference VARCHAR(100),
    created_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_challans_number ON challans(challan_number);
CREATE INDEX IF NOT EXISTS idx_challans_status ON challans(status);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS appeals (
    id                   SERIAL PRIMARY KEY,
    challan_id           INTEGER NOT NULL REFERENCES challans(id),
    citizen_id           INTEGER NOT NULL REFERENCES users(id),
    reason               TEXT NOT NULL,
    supporting_doc_url   VARCHAR(600),
    supporting_doc_hash  CHAR(64),
    status               appeal_status DEFAULT 'pending',
    submitted_at         TIMESTAMP DEFAULT NOW(),
    updated_at           TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_appeals_challan ON appeals(challan_id);
CREATE INDEX IF NOT EXISTS idx_appeals_citizen ON appeals(citizen_id);
CREATE INDEX IF NOT EXISTS idx_appeals_status  ON appeals(status);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS appeal_decisions (
    id          SERIAL PRIMARY KEY,
    appeal_id   INTEGER NOT NULL REFERENCES appeals(id),
    reviewer_id INTEGER NOT NULL REFERENCES users(id),
    decision    decision_type NOT NULL,
    notes       TEXT,
    decided_at  TIMESTAMP DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS road_segments (
    id                   SERIAL PRIMARY KEY,
    name                 VARCHAR(200) NOT NULL,
    speed_limit          FLOAT NOT NULL DEFAULT 60.0,
    location_description VARCHAR(400),
    is_active            BOOLEAN DEFAULT TRUE,
    created_at           TIMESTAMP DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS violation_rules (
    id             SERIAL PRIMARY KEY,
    violation_type VARCHAR(50) UNIQUE NOT NULL,
    fine_amount    FLOAT NOT NULL,
    description    TEXT,
    is_active      BOOLEAN DEFAULT TRUE,
    updated_by     INTEGER REFERENCES users(id),
    updated_at     TIMESTAMP DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS notifications (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    subject      VARCHAR(200),
    message      TEXT NOT NULL,
    channel      VARCHAR(20) DEFAULT 'in_app',   -- email / sms / in_app
    status       VARCHAR(20) DEFAULT 'pending',  -- pending / sent / failed
    error_detail TEXT,
    created_at   TIMESTAMP DEFAULT NOW(),
    sent_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notif_user   ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notif_status ON notifications(status);
