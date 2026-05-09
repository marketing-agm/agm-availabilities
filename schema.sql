-- AGM Tour Scheduling - D1 Database Schema
-- Run this via: wrangler d1 execute agm-tours --file=schema.sql

-- Availability slots created by leasing agents
CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property TEXT NOT NULL,
    slot_date TEXT NOT NULL,          -- YYYY-MM-DD
    start_time TEXT NOT NULL,         -- HH:MM (24hr)
    end_time TEXT NOT NULL,           -- HH:MM (24hr)
    status TEXT NOT NULL DEFAULT 'available',  -- 'available' or 'booked'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index for fast lookups by property + date range
CREATE INDEX IF NOT EXISTS idx_slots_property_date ON slots(property, slot_date);
CREATE INDEX IF NOT EXISTS idx_slots_status ON slots(status);

-- Bookings made by prospects
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL UNIQUE,
    property TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT DEFAULT '',
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    move_in_date TEXT DEFAULT '',     -- YYYY-MM-DD or empty
    unit_types TEXT DEFAULT '',       -- comma-separated: "studio,1bed,2bed"
    notes TEXT DEFAULT '',
    booked_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (slot_id) REFERENCES slots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bookings_property ON bookings(property);
CREATE INDEX IF NOT EXISTS idx_bookings_slot ON bookings(slot_id);

-- Simple property-level authentication for agents
CREATE TABLE IF NOT EXISTS property_auth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,      -- SHA-256 hash
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Active session tokens for authenticated agents
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    property TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
