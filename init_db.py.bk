import sqlite3
import os

os.makedirs("data", exist_ok=True)

conn = sqlite3.connect("data/dashboard.db")
cur = conn.cursor()

# ================= OLT DEVICES =================
cur.execute("""
CREATE TABLE IF NOT EXISTS olt_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    brand TEXT NOT NULL,
    type TEXT NOT NULL,
    pon_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    last_seen DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

# ================= ONU STATUS =================
cur.execute("""
CREATE TABLE IF NOT EXISTS onu_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    olt_id INTEGER NOT NULL,
    pon INTEGER NOT NULL,
    onu_id INTEGER NOT NULL,

    sn TEXT,
    mac TEXT,
    name TEXT,

    status TEXT,
    rx_power REAL,
    tx_power REAL,
    diagnosis TEXT,

    last_update DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (olt_id, pon, onu_id),
    FOREIGN KEY (olt_id) REFERENCES olt_devices(id)
)
""")

# ================= ALERTS =================
cur.execute("""
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    olt_id INTEGER,
    onu_id INTEGER,
    level TEXT,
    message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_resolved INTEGER DEFAULT 0
)
""")

conn.commit()
conn.close()

print("✅ Database dashboard.db SIAP (scraper + app.py AMAN)")
