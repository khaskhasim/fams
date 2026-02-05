import sqlite3
import hashlib
import os
from flask import Blueprint, render_template, request, redirect, session, flash

# ===============================
# BLUEPRINT (WAJIB auth_bp)
# ===============================
auth_bp = Blueprint("auth", __name__)

# ===============================
# DB PATH
# ===============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "dashboard.db")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ===============================
# LOGIN
# ===============================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT * FROM users
            WHERE username=? AND is_active=1
        """, (username,))
        user = cur.fetchone()
        conn.close()

        if not user:
            flash("User tidak ditemukan atau nonaktif", "error")
            return redirect("/login")

        if hash_password(password) != user["password_hash"]:
            flash("Password salah", "error")
            return redirect("/login")

        # LOGIN OK
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

        return redirect("/")

    return render_template("login.html")

# ===============================
# LOGOUT
# ===============================
# ===============================
# LOGOUT (POST ONLY)
# ===============================
@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Berhasil logout", "success")
    return redirect("/login")

