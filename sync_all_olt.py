import sqlite3
from sync_core import sync_single_olt

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, brand, host, username, password
        FROM olt_devices
        WHERE is_active=1
    """)

    for row in cur.fetchall():
        olt = {
            "id": row[0],
            "brand": row[1],
            "host": row[2],
            "username": row[3],
            "password": row[4]
        }

        try:
            sync_single_olt(cur, olt)
            print(f"[OK] {olt['host']}")
        except Exception as e:
            print(f"[ERR] {olt['host']} → {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
