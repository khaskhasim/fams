# =====================================================
# PATH ROOT PROJECT (WAJIB PALING ATAS)
# =====================================================
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# =====================================================
# IMPORT STANDARD / PYTHON
# =====================================================
import time
import threading
import subprocess
import platform
import sqlite3
import hashlib
from datetime import datetime
from functools import wraps


import requests

# =====================================================
# IMPORT FLASK
# =====================================================
from flask import (
    Flask,
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    abort,
    flash,
    jsonify,

    session
)

# =====================================================
# IMPORT EXTERNAL LIBRARY
# =====================================================
from routeros_api import RouterOsApiPool

# =====================================================
# IMPORT INTERNAL PROJECT
# =====================================================
from sync_core import sync_single_olt

#from db.db import get_db, DB_PATH
from db.db import get_db

from auth_routes import auth_bp   # ⬅️ blueprint auth dipisah

# =====================================================
# INIT FLASK APP
# =====================================================
app = Flask(__name__)
#app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
#app.secret_key = os.environ["31e0d88238362d67e224808d41bbd3b291efa54b153278090fc11b228e3baa4b"]
app.secret_key = os.environ["FLASK_SECRET_KEY"]


# =====================================================
# REGISTER BLUEPRINT
# =====================================================
app.register_blueprint(auth_bp)

# =====================================================
# GLOBAL STORAGE
# =====================================================
sync_progress = {}

# =====================================================
# HELPER FUNCTION
# =====================================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def get_active_tr069():
    conn = get_db()
    row = conn.execute("""
        SELECT *
        FROM tr069_servers
        WHERE is_active = 1
        LIMIT 1
    """).fetchone()
    conn.close()
    return row

def ping_host(host: str) -> bool:
    """
    Ping host (support ip atau ip:port)
    """
    ip = host.split(":")[0]
    param = "-n" if platform.system().lower() == "windows" else "-c"

    try:
        res = subprocess.run(
            ["ping", param, "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2
        )
        return res.returncode == 0
    except Exception:
        return False



def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated




@app.route("/")
@login_required
def home():
    conn = get_db()
    cur = conn.cursor()

    # =====================================================
    # OLT STATUS (REAL-TIME via PING)
    # =====================================================
    cur.execute("""
        SELECT id, name, host
        FROM olt_devices
        WHERE is_active = 1
    """)
    olts = cur.fetchall()

    olt_total = len(olts)
    olt_online = 0

    for o in olts:
        if ping_host(o["host"]):
            olt_online += 1

    olt_offline = olt_total - olt_online

    # =====================================================
    # ONU SUMMARY
    # =====================================================
    # total onu
    cur.execute("SELECT COUNT(*) AS total FROM onu_status")
    ont_total = cur.fetchone()["total"] or 0

    # online onu
    cur.execute("""
        SELECT COUNT(*) AS total
        FROM onu_status
        WHERE status = 'ONLINE'
    """)
    ont_online = cur.fetchone()["total"] or 0

    ont_offline = ont_total - ont_online


    # =====================================================
    # LIST ONU BERMASALAH (TERBARU)
    # =====================================================
    cur.execute("""
        SELECT
            o.name AS olt,
            n.pon,
            n.onu_id,
            n.name,
            n.mac,
            n.status,
            n.diagnosis,
            n.last_update
        FROM onu_status n
        JOIN olt_devices o ON o.id = n.olt_id
        WHERE n.status != 'ONLINE'
        ORDER BY n.last_update DESC
        LIMIT 10
    """)
    ont_problem_list = cur.fetchall()

    conn.close()

    # =====================================================
    # PERSENTASE ONU
    # =====================================================
    ont_online_percent = int((ont_online / ont_total) * 100) if ont_total else 0
    ont_offline_percent = 100 - ont_online_percent

    return render_template(
        "dashboard_home.html",
        active_page="dashboard",
        show_topbar=False,

        # HEADER
        today=datetime.now().strftime("%A, %d %B %Y"),
        user="Juragan",

        # OLT
        olt_total=olt_total,
        olt_online=olt_online,
        olt_offline=olt_offline,

        # ONU
        ont_total=ont_total,
        ont_online=ont_online,
        ont_offline=ont_offline,
        ont_online_percent=ont_online_percent,
        ont_offline_percent=ont_offline_percent,

        # ONU BERMASALAH
        ont_problem_list=ont_problem_list
    )


# =========================
# TAMBAH OLT BARU
# =========================


@app.route("/olt/add", methods=["GET", "POST"])
@login_required
def olt_add():
    if request.method == "POST":
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO olt_devices
            (name, host, username, password, brand, type, pon_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            request.form["name"],
            request.form["host"],
            request.form["username"],
            request.form["password"],
            request.form["brand"],
            request.form["type"],
            request.form["pon_count"] or 0
        ))

        conn.commit()
        conn.close()

        # 🔁 redirect ke list OLT + pesan sukses
        return redirect(url_for(
            "olt_devices",
            success=1,
            name=request.form["name"]
        ))

    return render_template(
        "olt_add.html",
        active_page="olt_devices"
    )


@app.route("/olt/devices")
@login_required
def olt_devices():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM olt_devices ORDER BY created_at DESC")
    olts = cur.fetchall()

    olt_status = {}
    for o in olts:
        olt_status[o["id"]] = ping_host(o["host"])

    conn.close()

    return render_template(
        "olt_devices.html",
        active_page="olt_devices",
        olts=olts,
        olt_status=olt_status
    )


@app.route("/olt/<int:olt_id>")
@login_required
def olt_onu_by_olt(olt_id):
    status_filter = request.args.get("status", "ALL")
    pon_filter = request.args.get("pon", "ALL")
    page = max(int(request.args.get("page", 1)), 1)

    PER_PAGE = 25
    offset = (page - 1) * PER_PAGE

    conn = get_db()
    cur = conn.cursor()

    # ================= GET OLT INFO =================
    cur.execute("SELECT * FROM olt_devices WHERE id=?", (olt_id,))
    olt = cur.fetchone()
    if not olt:
        conn.close()
        return "OLT tidak ditemukan", 404

    # ================= SUMMARY =================
    cur.execute(
        "SELECT COUNT(*) AS total FROM onu_status WHERE olt_id=?",
        (olt_id,)
    )

    total = cur.fetchone()["total"] or 0

    cur.execute("""
        SELECT COUNT(*) AS total
        FROM onu_status
        WHERE olt_id=? AND status='ONLINE'
    """, (olt_id,))

    online = cur.fetchone()["total"] or 0

    offline = total - online


    # ================= PON LIST =================
    cur.execute("""
        SELECT DISTINCT pon FROM onu_status
        WHERE olt_id=?
        ORDER BY CAST(pon AS INTEGER)
    """, (olt_id,))
    pon_list = [str(r["pon"]) for r in cur.fetchall()]

    # ================= WHERE =================
    where = "WHERE olt_id=?"
    params = [olt_id]

    if status_filter == "ONLINE":
        where += " AND status='ONLINE'"
    elif status_filter == "OFFLINE":
        where += " AND status!='ONLINE'"

    if pon_filter != "ALL":
        where += " AND pon=?"
        params.append(pon_filter)

    # ================= PAGINATION =================
    cur.execute(
        f"SELECT COUNT(*) AS total FROM onu_status {where}",
        params
    )
    total_rows = cur.fetchone()["total"] or 0
    total_pages = (total_rows + PER_PAGE - 1) // PER_PAGE


    # ================= DATA (RX TERBURUK DI ATAS) =================
    query = f"""
        SELECT *
        FROM onu_status
        {where}
        ORDER BY
        rx_power IS NULL,
        rx_power ASC,
        CAST(pon AS INTEGER),
        CAST(onu_id AS INTEGER)
        LIMIT ? OFFSET ?
    """

    cur.execute(query, params + [PER_PAGE, offset])
    rows = cur.fetchall()

    conn.close()

    return render_template(
        "olt_dashboard.html",
        active_page="olt_devices",
        olt=olt,
        rows=rows,
        total=total,
        online=online,
        offline=offline,
        status_filter=status_filter,
        pon_filter=str(pon_filter),
        pon_list=pon_list,
        page=page,
        total_pages=total_pages
    )





@app.route("/olt/<int:olt_id>/edit", methods=["GET", "POST"])
@login_required
def olt_edit(olt_id):
    conn = get_db()
    cur = conn.cursor()

    # Ambil data OLT
    cur.execute("SELECT * FROM olt_devices WHERE id=?", (olt_id,))
    olt = cur.fetchone()

    if not olt:
        conn.close()
        return "OLT tidak ditemukan", 404

    if request.method == "POST":
        # Gunakan password lama jika field kosong
        password = request.form.get("password") or olt["password"]

        # Pastikan pon_count integer
        pon_count = request.form.get("pon_count") or 0

        cur.execute("""
            UPDATE olt_devices
            SET
                name = ?,
                host = ?,
                username = ?,
                password = ?,
                brand = ?,
                type = ?,
                pon_count = ?
            WHERE id = ?
        """, (
            request.form.get("name"),
            request.form.get("host"),
            request.form.get("username"),
            password,
            request.form.get("brand"),
            request.form.get("type"),
            int(pon_count),
            olt_id
        ))

        conn.commit()
        conn.close()

        flash("OLT berhasil diperbarui", "success")
        return redirect("/olt/devices")

    conn.close()

    return render_template(
        "olt_edit.html",
        active_page="olt_devices",
        olt=olt
    )



@app.route("/olt/<int:olt_id>/delete", methods=["POST"])
@login_required
def olt_delete(olt_id):
    conn = get_db()
    cur = conn.cursor()

    try:
        # =========================
        # CEK OLT ADA ATAU TIDAK
        # =========================
        cur.execute(
            "SELECT name FROM olt_devices WHERE id=?",
            (olt_id,)
        )
        olt = cur.fetchone()

        if not olt:
            flash("OLT tidak ditemukan atau sudah dihapus", "warning")
            return redirect("/olt/devices")

        # =========================
        # HAPUS ONU TERKAIT
        # =========================
        cur.execute(
            "DELETE FROM onu_status WHERE olt_id=?",
            (olt_id,)
        )

        # =========================
        # HAPUS OLT
        # =========================
        cur.execute(
            "DELETE FROM olt_devices WHERE id=?",
            (olt_id,)
        )

        conn.commit()

        flash(
            f"OLT '{olt['name']}' dan seluruh ONT berhasil dihapus",
            "success"
        )

    except Exception as e:
        conn.rollback()
        flash(f"Gagal menghapus OLT: {e}", "danger")

    finally:
        conn.close()

    return redirect("/olt/devices")






@app.route("/olt/<int:olt_id>/sync", methods=["POST"])
@login_required
def sync_olt(olt_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM olt_devices WHERE id=?", (olt_id,))
    olt = cur.fetchone()
    conn.close()

    if not olt:
        return jsonify({
            "success": False,
            "message": "OLT tidak ditemukan"
        }), 404

    # init progress (AMAN)
    with sync_lock:
        sync_progress[olt_id] = {
            "status": "running",
            "message": "Menghubungi OLT...",
            "current": 0,
            "total": 1
        }

    def run_sync():
        try:
            ok, msg = sync_single_olt(dict(olt))
            with sync_lock:
                sync_progress[olt_id] = {
                    "status": "done" if ok else "error",
                    "message": msg,
                    "current": 1,
                    "total": 1
                }
        except Exception as e:
            with sync_lock:
                sync_progress[olt_id] = {
                    "status": "error",
                    "message": str(e),
                    "current": 0,
                    "total": 1
                }

    threading.Thread(target=run_sync, daemon=True).start()

    return jsonify({
        "success": True,
        "message": "Sinkronisasi dimulai"
    })



@app.route("/olt/<int:olt_id>/sync/status")
@login_required
def sync_status(olt_id):
    with sync_lock:
        return jsonify(
            sync_progress.get(olt_id, {
                "status": "idle",
                "message": "",
                "current": 0,
                "total": 1
            })
        )


@app.route("/pppoe")
@login_required
def pppoe_dashboard():
    conn = get_db()
    cur = conn.cursor()

    # ambil filter status (opsional)
    status_filter = request.args.get("status", "ALL")

    rows_raw = cur.execute("""
        SELECT
            username,
            rx_bytes,
            tx_bytes,
            last_update,
            (strftime('%s','now') - strftime('%s', last_update)) AS age
        FROM pppoe_active
        ORDER BY username
    """).fetchall()

    # mapping ke object (biar rapi di template)
    rows = []
    for r in rows_raw:
        rows.append({
            "username": r[0],
            "rx_bytes": r[1],
            "tx_bytes": r[2],
            "last_update": r[3],
            "age": r[4]
        })

    # filter status
    if status_filter == "ACTIVE":
        rows = [r for r in rows if r["age"] < 180]
    elif status_filter == "STALE":
        rows = [r for r in rows if r["age"] >= 180]

    # summary
    total = len(rows)
    active = sum(1 for r in rows if r["age"] < 180)
    stale  = total - active

    return render_template(
        "pppoe.html",
        rows=rows,
        total=total,
        active=active,
        stale=stale,
        status_filter=status_filter,
        active_page="pppoe",
        show_topbar=True
    )


# ===============================
# LIST MIKROTIK
# ===============================
@app.route("/mikrotik")
@login_required
def mikrotik_devices():
    conn = get_db()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT
            id, name, host,
            sys_name, sys_uptime,
            last_seen,
            (strftime('%s','now') - strftime('%s', last_seen)) AS age
        FROM mikrotik_devices
        ORDER BY name
    """).fetchall()

    conn.close()

    return render_template(
        "mikrotik_devices.html",
        rows=rows,
        active_page="mikrotik",
        show_topbar=True
    )


# ===============================
# ADD MIKROTIK
# ===============================
@app.route("/mikrotik/add", methods=["GET", "POST"])
@login_required
def mikrotik_add():
    if request.method == "POST":
        conn = get_db()
        conn.execute("""
            INSERT INTO mikrotik_devices
            (name, host, snmp_community, api_user, api_pass, api_port)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            request.form["name"],
            request.form["host"],
            "dashboard",          # ← DEFAULT SNMP COMMUNITY
            request.form["api_user"],
            request.form["api_pass"],
            request.form["api_port"] or 8728
        ))
        conn.commit()
        conn.close()

        flash("Mikrotik berhasil ditambahkan", "success")
        return redirect("/mikrotik")

    return render_template(
        "mikrotik_add.html",
        active_page="mikrotik",
        show_topbar=True
    )


# ===============================
# EDIT MIKROTIK
# ===============================
@app.route("/mikrotik/<int:id>/edit", methods=["GET", "POST"])
@login_required
def mikrotik_edit(id):
    conn = get_db()
    cur = conn.cursor()

    router = cur.execute("""
        SELECT *
        FROM mikrotik_devices
        WHERE id=?    """, (id,)).fetchone()

    if not router:
        conn.close()
        abort(404)

    if request.method == "POST":
        name = request.form["name"]
        host = request.form["host"]
        snmp_community = request.form["snmp_community"]
        api_user = request.form["api_user"]
        api_port = request.form["api_port"]

        # password optional
        api_pass = request.form.get("api_pass")

        if api_pass:
            cur.execute("""
                UPDATE mikrotik_devices
                SET
                    name=?,
                    host=?,
                    snmp_community=?,
                    api_user=?,
                    api_pass=?,
                    api_port=?
                WHERE id=?            """, (
                name, host, snmp_community,
                api_user, api_pass, api_port, id
            ))
        else:
            cur.execute("""
                UPDATE mikrotik_devices
                SET
                    name=?,
                    host=?,
                    snmp_community=?,
                    api_user=?,
                    api_port=?
                WHERE id=?            """, (
                name, host, snmp_community,
                api_user, api_port, id
            ))

        conn.close()
        flash("Mikrotik berhasil diperbarui", "success")
        return redirect("/mikrotik")

    conn.close()
    return render_template(
        "mikrotik_edit.html",
        r=router,
        active_page="mikrotik",
        show_topbar=True
    )


# ===============================
# DETAIL (PLACEHOLDER)
# ===============================
@app.route("/mikrotik/<int:id>")
@login_required
def mikrotik_detail(id):
    conn = get_db()
    r = conn.execute("""
        SELECT id, name, host, api_port, api_user
        FROM mikrotik_devices
        WHERE id=?    """, (id,)).fetchone()
    conn.close()

    if not r:
        return "Router not found", 404

    return render_template(
        "mikrotik_detail.html",
        router=r,
        router_id=id,          # ⬅️ INI KUNCINYA
        active_page="mikrotik"
    )



# ===============================
# DELETE MIKROTIK
# ===============================
@app.route("/mikrotik/<int:id>/delete", methods=["POST"])
@login_required
def mikrotik_delete(id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM mikrotik_devices WHERE id=?", (id,))
    conn.commit()

    flash("Mikrotik berhasil dihapus", "success")
    return redirect("/mikrotik")



from pysnmp.hlapi import *
import re

@app.route("/mikrotik/<int:id>/test-snmp", methods=["POST"])
@login_required
def mikrotik_test_snmp(id):
    conn = get_db()
    cur = conn.cursor()

    row = cur.execute("""
        SELECT host, snmp_community
        FROM mikrotik_devices
        WHERE id=?    """, (id,)).fetchone()

    if not row:
        flash("Mikrotik tidak ditemukan", "error")
        return redirect("/mikrotik")

    host, community = row
    port = 161
    try:
        def snmp_get(oid):
            it = getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                UdpTransportTarget((host, port), timeout=2, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )
            eInd, eStat, eIdx, v = next(it)
            if eInd or eStat:
                raise Exception(eInd or eStat.prettyPrint())
            return str(v[0][1])

        sys_descr  = snmp_get("1.3.6.1.2.1.1.1.0")  # sysDescr
        sys_name   = snmp_get("1.3.6.1.2.1.1.5.0")  # sysName
        sys_uptime = snmp_get("1.3.6.1.2.1.1.3.0")  # sysUpTime

        # ambil versi RouterOS dari sysDescr (opsional)
        match = re.search(r"RouterOS\s+([\d\.]+)", sys_descr)
        ros_version = match.group(1) if match else None

        cur.execute("""
            UPDATE mikrotik_devices
            SET
              sys_descr=?,
              sys_name=?,
              sys_uptime=?,
              ros_version=?,
              last_seen=CURRENT_TIMESTAMP
            WHERE id=?        """, (
            sys_descr,
            sys_name,
            int(sys_uptime),
            ros_version,
            id
        ))
        conn.commit()

        flash(f"SNMP OK: {sys_name}", "success")

    except Exception as e:
        flash(f"SNMP GAGAL: {e}", "error")

    return redirect("/mikrotik")



@app.route("/api/mikrotik/<int:id>/realtime")
@login_required
def mikrotik_realtime(id):
    conn = get_db()
    r = conn.execute("""
        SELECT host, api_user, api_pass, api_port
        FROM mikrotik_devices
        WHERE id=?    """, (id,)).fetchone()
    conn.commit()
    conn.close()

    if not r:
        return {"error": "not found"}, 404

    try:
        from routeros_api import RouterOsApiPool

        api_pool = RouterOsApiPool(
            r["host"],
            username=r["api_user"],
            password=r["api_pass"],
            port=r["api_port"],
            use_ssl=False,
            plaintext_login=True
        )

        api = api_pool.get_api()

        res   = api.get_resource("/system/resource").get()[0]
        clock = api.get_resource("/system/clock").get()[0]

        data = {
            "cpu": int(res["cpu-load"]),
            "memory": round(
                (1 - int(res["free-memory"]) / int(res["total-memory"])) * 100, 1
            ),
            "uptime": res["uptime"],
            "version": res["version"],
            "board": res["board-name"],
            "router_time": f'{clock["date"]} {clock["time"]}'
        }

        api_pool.disconnect()
        return data

    except Exception as e:
        return {"error": str(e)}, 500




@app.route("/settings/telegram", methods=["GET", "POST"])
@login_required
def telegram_settings_page():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        enabled = True if request.form.get("enabled") else False
        bot_token = request.form.get("token", "").strip()
        chat_id = request.form.get("chat_id", "").strip()

        cur.execute("""
            UPDATE alert_telegram
            SET
                enabled = ?,
                bot_token = ?,
                chat_id = ?,
                updated_at = CURRENT_TIMESTAMP

            WHERE id = 1
        """, (enabled, bot_token, chat_id))

        conn.commit()
        cur.close()
        conn.close()

        flash("✅ Konfigurasi Telegram berhasil disimpan!", "success")
        return redirect(url_for("telegram_settings_page"))

    cur.execute("""
        SELECT enabled, bot_token, chat_id
        FROM alert_telegram
        WHERE id = 1
    """)
    cfg = cur.fetchone()

    cur.close()
    conn.close()

    return render_template(
        "settings_telegram.html",
        telegram=cfg,
        active_page="settings",
        show_topbar=True
    )


@app.route("/settings/telegram/test", methods=["POST"])
@login_required
def telegram_test_page():
    conn = get_db()
    cfg = conn.execute("""
        SELECT enabled, bot_token, chat_id
        FROM alert_telegram
        WHERE id=1
    """).fetchone()
    conn.close()

    if not cfg or not cfg["enabled"]:
        flash("❌ Telegram belum diaktifkan", "danger")
        return redirect(url_for("telegram_settings_page"))

    token = cfg["bot_token"]
    chat_id = cfg["chat_id"]

    pesan = (
        "🔔 <b>Test notifikasi Dashboard ISP</b>\n"
        "Jika kamu menerima pesan ini,\n"
        "konfigurasi Telegram sudah OK! ✅"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": pesan,
        "parse_mode": "HTML"
    }

    print("DEBUG TOKEN:", token)
    print("DEBUG CHAT ID:", chat_id)
    print("DEBUG URL:", url)

    try:
        resp = requests.post(url, data=data, timeout=8)
        print("DEBUG RESP:", resp.status_code, resp.text)

        if resp.ok and resp.json().get("ok"):
            flash("✅ Pesan test berhasil dikirim ke Telegram!", "success")
        else:
            msg = resp.json().get("description") if resp.content else "Gagal, cek token/chat_id"
            flash(f"❌ Gagal kirim Telegram: {msg}", "danger")

    except Exception as e:
        flash(f"❌ Error kirim Telegram: {e}", "danger")

    return redirect(url_for("telegram_settings_page"))


@app.route("/ont/problem")
@login_required
def ont_problem_list():
    status_filter = request.args.get("status", "ALL")
    page = max(int(request.args.get("page", 1)), 1)

    PER_PAGE = 25
    offset = (page - 1) * PER_PAGE

    conn = get_db()
    cur = conn.cursor()

    # ====== WHERE (FIXED) ======
    where = """
        WHERE
          o.is_active = 1
          AND (
            n.status != 'ONLINE'
            OR (n.rx_power IS NOT NULL AND n.rx_power < -25)
            OR n.diagnosis != 'NORMAL'
          )
    """
    params = []

    if status_filter != "ALL":
        where += " AND n.status = ?"
        params.append(status_filter)

    # ====== TOTAL ======
    cur.execute(f"""
        SELECT COUNT(*) AS total
        FROM onu_status n
        JOIN olt_devices o ON o.id = n.olt_id
        {where}
    """, params)

    total_rows = cur.fetchone()["total"] or 0
    total_pages = (total_rows + PER_PAGE - 1) // PER_PAGE


    # ====== DATA ======
    cur.execute(f"""
        SELECT
            o.name AS olt_name,
            n.olt_id,
            n.pon,
            n.onu_id,
            n.name,
            n.mac,
            n.status,
            n.rx_power,
            n.diagnosis,
            n.alert_telegram,
            n.last_update
        FROM onu_status n
        JOIN olt_devices o ON o.id = n.olt_id
        {where}
        ORDER BY
            n.last_update DESC,
            n.rx_power ASC
        LIMIT ? OFFSET ?
    """, params + [PER_PAGE, offset])

    rows = cur.fetchall()
    conn.close()

    return render_template(
        "ont_problem.html",
        rows=rows,
        page=page,
        total_pages=total_pages,
        status_filter=status_filter,
        active_page="ont_problem",
        show_topbar=True
    )


@app.route("/ont/<int:olt_id>/<pon>/<onu_id>/toggle-telegram", methods=["POST"])
@login_required
def ont_toggle_telegram(olt_id, pon, onu_id):
    conn = get_db()
    cur = conn.cursor()

    row = cur.execute("""
        SELECT alert_telegram
        FROM onu_status
        WHERE olt_id=? AND pon=? AND onu_id=?
    """, (olt_id, pon, onu_id)).fetchone()

    if not row:
        conn.close()
        return jsonify({"success": False}), 404

    new_val = 0 if row["alert_telegram"] else 1

    cur.execute("""
        UPDATE onu_status
        SET alert_telegram=?
        WHERE olt_id=? AND pon=? AND onu_id=?
    """, (new_val, olt_id, pon, onu_id))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "value": new_val
    })
#########        routeros tr069 server management      ###########

@app.route("/tr069")
@login_required
def tr069_servers():
    conn = get_db()
    rows = conn.execute("""
        SELECT *
        FROM tr069_servers
        ORDER BY name
    """).fetchall()
    conn.close()

    return render_template(
        "tr069_servers.html",
        rows=rows,
        active_page="tr069",
        show_topbar=True
    )

@app.route("/tr069/add", methods=["GET", "POST"])
@login_required
def tr069_add():
    if request.method == "POST":
        conn = get_db()
        conn.execute("""
            INSERT INTO tr069_servers
            (name, base_url, is_active)
            VALUES (?, ?, ?)
        """, (
            request.form["name"],
            request.form["base_url"].rstrip("/"),
            1 if request.form.get("is_active") else 0
        ))
        conn.commit()
        conn.close()

        flash("Server GenieACS berhasil ditambahkan", "success")
        return redirect("/tr069")

    return render_template(
        "tr069_add.html",
        active_page="tr069",
        show_topbar=True
    )


@app.route("/tr069/<int:id>/edit", methods=["GET", "POST"])
@login_required
def tr069_edit(id):
    conn = get_db()
    s = conn.execute(
        "SELECT * FROM tr069_servers WHERE id=?",
        (id,)
    ).fetchone()

    if not s:
        conn.close()
        abort(404)

    if request.method == "POST":
        conn.execute("""
            UPDATE tr069_servers
            SET
              name=?,
              base_url=?,
              is_active=?
            WHERE id=?        """, (
            request.form["name"],
            request.form["base_url"].rstrip("/"),
            1 if request.form.get("is_active") else 0,
            id
        ))
        conn.close()

        flash("Server GenieACS diperbarui", "success")
        return redirect("/tr069")

    conn.close()
    return render_template(
        "tr069_edit.html",
        server=s,
        active_page="tr069",
        show_topbar=True
    )



@app.route("/tr069/<int:id>/delete", methods=["POST"])
@login_required
def tr069_delete(id):
    conn = get_db()
    conn.execute("DELETE FROM tr069_servers WHERE id=?", (id,))
    conn.commit()
    conn.close()

    flash("Server TR-069 dihapus", "success")
    return redirect("/tr069")

@app.route("/tr069/<int:id>/test", methods=["POST"])
@login_required
def tr069_test(id):
    conn = get_db()
    s = conn.execute(
        "SELECT * FROM tr069_servers WHERE id=?",
        (id,)
    ).fetchone()
    conn.close()

    try:
        r = requests.get(
            f"{s['base_url']}/devices?limit=1",
            timeout=5
        )

        if r.ok:
            flash("✅ Koneksi GenieACS berhasil", "success")
        else:
            flash(f"❌ GenieACS error ({r.status_code})", "danger")

    except Exception as e:
        flash(f"❌ Error: {e}", "danger")

    return redirect("/tr069")



from math import ceil
from datetime import datetime
import time
import requests
from flask import request, render_template, flash, redirect

def parse_iso(ts):
    try:
        return datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        ).timestamp()
    except Exception:
        return 0


@app.route("/tr069/<int:id>/devices")
@login_required
def tr069_devices_by_server(id):
    # =============================
    # GET ACS SERVER
    # =============================
    conn = get_db()
    acs = conn.execute(
        "SELECT * FROM tr069_servers WHERE id=?",
        (id,)
    ).fetchone()
    conn.close()

    if not acs:
        flash("❌ Server TR-069 tidak ditemukan", "danger")
        return redirect("/tr069")

    search = request.args.get("q", "").strip().lower()
    rx_filter = request.args.get("rx")

    # =============================
    # FETCH DEVICES FROM ACS
    # =============================
    try:
        r = requests.get(
            f"{acs['base_url']}/devices",
            timeout=15
        )
        r.raise_for_status()
        raw_devices = r.json()
    except Exception as e:
        flash(f"❌ Gagal mengambil devices: {e}", "danger")
        raw_devices = []

    # =============================
    # PARSE & NORMALIZE DEVICES
    # =============================
    devices_all = []
    now = time.time()

    for d in raw_devices:
        vp = d.get("VirtualParameters", {})
        did = d.get("_deviceId", {})

        pppoe = (
            vp.get("pppoeUsername", {}).get("_value")
            or "-"
        )

        try:
            rx = float(vp.get("RXPower", {}).get("_value"))
        except Exception:
            rx = None

        try:
            temp = int(vp.get("gettemp", {}).get("_value"))
        except Exception:
            temp = None

        last_inform = d.get("_lastInform")
        last_ts = parse_iso(last_inform) if last_inform else 0
        online = (now - last_ts) < 300  # 5 menit

        devices_all.append({
            "id": d.get("_id", ""),
            "pppoe": pppoe,
            "rx": rx,
            "temp": temp,
            "vendor": did.get("_Manufacturer", "-"),
            "model": did.get("_ProductClass", "-"),
            "online": online,
            "last_inform": last_inform
        })

    # =============================
    # FILTERING (SETELAH DATA ADA)
    # =============================
    if search:
        devices_all = [
            d for d in devices_all
            if search in d["pppoe"].lower()
            or search in d["id"].lower()
            or search in d["model"].lower()
        ]

    if rx_filter == "critical":
        devices_all = [
            d for d in devices_all
            if d["rx"] is not None and d["rx"] < -25
        ]

    # =============================
    # KPI
    # =============================
    total = len(devices_all)
    online_count = sum(1 for d in devices_all if d["online"])
    offline_count = total - online_count

    # =============================
    # PAGINATION
    # =============================
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 20
    total_pages = ceil(total / per_page) if total else 1

    start = (page - 1) * per_page
    end = start + per_page
    devices_page = devices_all[start:end]

    # =============================
    # RENDER
    # =============================
    return render_template(
        "tr069_devices.html",
        acs=acs,
        devices=devices_page,
        total=total,
        online=online_count,
        offline=offline_count,
        page=page,
        total_pages=total_pages,
        active_page="tr069",
        show_topbar=True
    )



@app.route("/tr069/overview")
@login_required
def tr069_overview():
    conn = get_db()
    acs = conn.execute("""
        SELECT *
        FROM tr069_servers
        WHERE is_active=1
        LIMIT 1
    """).fetchone()
    conn.close()

    if not acs:
        flash("❌ Tidak ada server TR-069 aktif", "danger")
        return redirect("/tr069")

    try:
        r = requests.get(f"{acs['base_url']}/devices", timeout=10)
        r.raise_for_status()
        devices = r.json()
    except Exception as e:
        flash(f"❌ Gagal mengambil data TR-069: {e}", "danger")
        devices = []

    # ======================
    # KPI CALCULATION
    # ======================
    total = len(devices)
    online = sum(1 for d in devices if d.get("_lastInform"))
    offline = total - online

    return render_template(
        "tr069_overview.html",
        acs=acs,
        devices=devices,
        total=total,
        online=online,
        offline=offline,
        active_page="tr069",
        show_topbar=True
    )



#if __name__ == "__main__":
#    app.run(debug=True)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
