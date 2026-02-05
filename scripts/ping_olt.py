#!/usr/bin/env python3
import os
import sqlite3
import subprocess
import platform
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "dashboard.db")

def ping(host):
    ip = host.split(":")[0]
    param = "-n" if platform.system().lower() == "windows" else "-c"
    cmd = ["ping", param, "1", ip]

    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, host
        FROM olt_devices
        WHERE is_active = 1
    """)

    olts = cur.fetchall()

    for olt_id, host in olts:
        online = ping(host)

        if online:
            cur.execute("""
                UPDATE olt_devices
                SET is_online = 1,
                    last_seen = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (olt_id,))
        else:
            cur.execute("""
                UPDATE olt_devices
                SET is_online = 0
                WHERE id = ?
            """, (olt_id,))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
