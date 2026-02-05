-- ================= OLT DEVICES =================
CREATE TABLE IF NOT EXISTS olt_devices (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    brand TEXT NOT NULL,
    type TEXT NOT NULL,
    pon_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    last_seen TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ================= ONU STATUS =================
CREATE TABLE IF NOT EXISTS onu_status (
    id SERIAL PRIMARY KEY,

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

    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    alert_telegram INTEGER DEFAULT 0,

    CONSTRAINT uq_onu UNIQUE (olt_id, pon, onu_id),
    CONSTRAINT fk_olt
      FOREIGN KEY (olt_id)
      REFERENCES olt_devices(id)
      ON DELETE CASCADE
);

-- ================= ALERTS =================
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    olt_id INTEGER,
    onu_id INTEGER,
    level TEXT,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_resolved INTEGER DEFAULT 0
);

-- ================= PPPoE =================
CREATE TABLE IF NOT EXISTS pppoe_active (
    username TEXT PRIMARY KEY,
    rx_bytes BIGINT,
    tx_bytes BIGINT,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ================= TELEGRAM =================
CREATE TABLE IF NOT EXISTS alert_telegram (
    id INTEGER PRIMARY KEY DEFAULT 1,
    enabled INTEGER DEFAULT 0,
    bot_token TEXT,
    chat_id TEXT,
    updated_at TIMESTAMP
);

INSERT INTO alert_telegram (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;
