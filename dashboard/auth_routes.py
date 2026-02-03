from flask import Blueprint, render_template, request, redirect, session, flash, url_for
import sqlite3, hashlib
from db.db import DB_PATH

auth_bp = Blueprint("auth", __name__)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


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
            return redirect(url_for("auth.login"))

        if hash_password(password) != user["password_hash"]:
            flash("Password salah", "error")
            return redirect(url_for("auth.login"))

        # LOGIN SUKSES
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

        return redirect("/")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Berhasil logout", "success")
    return redirect(url_for("auth.login"))
