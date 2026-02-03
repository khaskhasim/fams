#!/usr/bin/env python3
import sqlite3
import hashlib
import getpass
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "dashboard.db")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    username = input("Username admin: ").strip()
    password = getpass.getpass("Password admin: ").strip()

    if not username or not password:
        print("❌ Username / password kosong")
        return

    password_hash = hash_password(password)

    try:
        cur.execute("""
            INSERT INTO users (username, password_hash, role, is_active)
            VALUES (?, ?, 'admin', 1)
        """, (username, password_hash))

        conn.commit()
        print("✅ Admin berhasil dibuat")

    except sqlite3.IntegrityError:
        print("❌ Username sudah ada")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
