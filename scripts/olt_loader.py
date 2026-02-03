import sqlite3

DB_PATH = "data/dashboard.db"

def get_active_olts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM olt_devices
        WHERE is_active = 1
    """)

    rows = cur.fetchall()
    conn.close()

    return [dict(r) for r in rows]
