#!/usr/bin/env python3
import os
import sys
import sqlite3

# ===============================
# PROJECT ROOT PATH
# ===============================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ===============================
# IMPORT PROJECT
# ===============================
from hioso import fetch_onu_hioso
from vsol import fetch_onu_vsol
from alerts.telegram import send as send_telegram

# ===============================
# CONFIG
# ===============================
DEBUG_TELEGRAM = False   # TRUE hanya untuk testing
DB_PATH = os.path.join(BASE_DIR, "data", "dashboard.db")

SCRAPER_MAP = {
    "hioso": fetch_onu_hioso,
    "vsol": fetch_onu_vsol
}

# ===============================
# DIAGNOSIS (FINAL – VENDOR AWARE)
# ===============================
def map_diagnosis(brand: str, raw_status: str, rx):
    brand = (brand or "").lower()
    status = raw_status.upper() if raw_status else "UNKNOWN"

    if status == "UNKNOWN":
        return "Perlu Dicek"

    # ===== HIOSO =====
    if brand == "hioso":
        if status == "POWER_OFF":
            return "ONU Mati / Listrik Pelanggan"
        if status == "DOWN":
            return "Fiber / Kabel Bermasalah"
        if status == "ONLINE":
            if rx is not None and rx < -25:
                return "Redaman Tinggi / Fiber Bermasalah"
            return "NORMAL"

    # ===== VSOL =====
    if brand == "vsol":
        if status in ("DOWN", "POWER_OFF"):
            return "ONU Mati / Listrik Pelanggan"

        if status == "WIRE_DOWN":
            return "Fiber / Kabel Bermasalah"

        if status == "ONLINE":
            if rx is not None and rx < -25:
                return "Redaman Tinggi / Fiber Bermasalah"
            return "NORMAL"


    # ===== FALLBACK =====
    if status != "ONLINE":
        return "ONU Offline"

    if rx is not None and rx < -25:
        return "Redaman Tinggi / Fiber Bermasalah"

    return "NORMAL"


def is_problem_diagnosis(diagnosis):
    return diagnosis != "NORMAL"


def diagnosis_emoji(diagnosis):
    return {
        "Perlu Dicek": "🧪",
        "ONU Mati / Listrik Pelanggan": "🔌",
        "Fiber / Kabel Bermasalah": "🧵",
        "Redaman Tinggi / Fiber Bermasalah": "📉",
        "ONU Offline": "❌",
        "NORMAL": "✅",
    }.get(diagnosis, "⚠️")


# ===============================
# UPSERT ONU
# ===============================
def upsert_onu(cur, olt_id, onu):
    cur.execute("""
        INSERT INTO onu_status (
            olt_id, pon, onu_id,
            sn, mac, name,
            status, rx_power, tx_power,
            diagnosis, last_update
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(olt_id, pon, onu_id)
        DO UPDATE SET
            sn=excluded.sn,
            mac=excluded.mac,
            name=excluded.name,
            status=excluded.status,
            rx_power=excluded.rx_power,
            tx_power=excluded.tx_power,
            diagnosis=excluded.diagnosis,
            last_update=CURRENT_TIMESTAMP
    """, (
        olt_id,
        str(onu.get("pon")),
        str(onu.get("onu_id")),
        onu.get("sn"),
        onu.get("mac"),
        onu.get("name"),
        onu.get("status"),
        onu.get("rx_power"),
        onu.get("tx_power"),
        onu.get("diagnosis")
    ))

# ===============================
# MAIN (SYNC SEMUA OLT)
# ===============================
def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, brand, host, username, password
        FROM olt_devices
        WHERE is_active = 1
    """)
    olts = cur.fetchall()

    for olt in olts:
        brand = olt["brand"]
        scraper = SCRAPER_MAP.get(brand)
        if not scraper:
            continue

        olt_ctx = dict(olt)

        # ONU lama (untuk recovery)
        cur.execute("""
            SELECT pon, onu_id, diagnosis
            FROM onu_status
            WHERE olt_id=?
        """, (olt["id"],))
        old_onu = {
            (str(r["pon"]), str(r["onu_id"])): r["diagnosis"]
            for r in cur.fetchall()
        }

        try:
            onus = scraper(olt_ctx)
        except Exception as e:
            print(f"[OLT {olt['id']}] Fetch gagal:", e)
            continue

        olt_onu_keys = set()

        for onu in onus:
            pon = str(onu.get("pon"))
            onu_id = str(onu.get("onu_id"))
            olt_onu_keys.add((pon, onu_id))

            diagnosis = map_diagnosis(
                brand,
                onu.get("status"),
                onu.get("rx_power")
            )
            onu["diagnosis"] = diagnosis

            upsert_onu(cur, olt["id"], onu)

            prev_diag = old_onu.get((pon, onu_id))

            # ===== RECOVERY =====
            if prev_diag and prev_diag != "NORMAL" and diagnosis == "NORMAL":
                rx = onu.get("rx_power")
                rx_text = "-" if rx is None else f"{rx:.2f} dBm"

                msg = (
                    "✅ <b>ONT RECOVERY</b>\n\n"
                    f"<b>OLT</b>       : {olt['name']}\n"
                    f"<b>PON / ONU</b> : {pon} / {onu_id}\n"
                    f"<b>Nama</b>      : {onu.get('name','-')}\n"
                    f"<b>Status</b>    : ONLINE\n"
                    f"<b>RX Power</b>  : {rx_text}"
                )
                send_telegram(msg)

            # ===== PROBLEM =====
            if not is_problem_diagnosis(diagnosis):
                continue

            cur.execute("""
                SELECT alert_telegram
                FROM onu_status
                WHERE olt_id=? AND pon=? AND onu_id=?
            """, (olt["id"], pon, onu_id))
            row = cur.fetchone()
            if not row or not row["alert_telegram"]:
                continue

            if not DEBUG_TELEGRAM and prev_diag == diagnosis:
                continue

            rx = onu.get("rx_power")
            rx_text = "-" if rx is None else f"{rx:.2f} dBm"
            emoji = diagnosis_emoji(diagnosis)

            msg = (
                "🚨 <b>ONT BERMASALAH</b>\n\n"
                f"<b>OLT</b>       : {olt['name']}\n"
                f"<b>PON / ONU</b> : {pon} / {onu_id}\n"
                f"<b>Nama</b>      : {onu.get('name','-')}\n"
                f"<b>Status</b>    : {onu.get('status')}\n"
                f"<b>RX Power</b>  : {rx_text}\n"
                f"<b>Diagnosis</b> : {emoji} {diagnosis}"
            )
            send_telegram(msg)

        conn.commit()

    conn.close()


if __name__ == "__main__":
    main()
