#!/usr/bin/env python3
import os
import sqlite3

from scraper import scraper_hioso
from scraper import scraper_vsol
from alerts.telegram import send as send_telegram

# ===============================
# PATH & DB
# ===============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "dashboard.db")

fetch_onu_hioso = scraper_hioso.fetch_onu_hioso
fetch_onu_vsol  = scraper_vsol.fetch_onu_vsol

SCRAPER_MAP = {
    "hioso": fetch_onu_hioso,
    "vsol": fetch_onu_vsol
}

# ===============================
# DIAGNOSIS (VENDOR AWARE)
# ===============================
def map_diagnosis(brand: str, raw_status: str, rx):
    brand = brand.lower()
    status = raw_status.upper() if raw_status else "UNKNOWN"

    # UNKNOWN
    if status == "UNKNOWN":
        return "Perlu Dicek"

    # ===============================
    # HIOSO
    # ===============================
    if brand == "hioso":
        if status == "POWER_OFF":
            # RX masih bisa ada → tetap power issue
            return "ONU Mati / Listrik Pelanggan"

        if status == "DOWN":
            return "Fiber / Kabel Bermasalah"

        if status == "ONLINE" and rx is not None and rx < -25:
            return "Redaman Tinggi / Fiber Bermasalah"

    # ===============================
    # VSOL
    # ===============================
    if brand == "vsol":
        if status in ("DOWN", "POWER_OFF"):
            return "ONU Mati / Listrik Pelanggan"

        if status == "WIRE_DOWN":
            return "Fiber / Kabel Bermasalah"

        if status == "ONLINE":
            if rx is not None and rx < -25:
                return "Redaman Tinggi / Fiber Bermasalah"
            return "NORMAL"





    # ===============================
    # FALLBACK UMUM
    # ===============================
    if status != "ONLINE":
        return "ONU Offline"

    return "NORMAL"


# ===============================
# HELPER
# ===============================
def is_problem_diagnosis(diagnosis: str) -> bool:
    return diagnosis != "NORMAL"


def is_recovery(prev_diag: str, curr_diag: str) -> bool:
    return prev_diag != "NORMAL" and curr_diag == "NORMAL"


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
        onu.get("status"),       # RAW STATUS
        onu.get("rx_power"),
        onu.get("tx_power"),
        onu.get("diagnosis")
    ))


# ===============================
# SYNC SINGLE OLT
# ===============================
def sync_single_olt(olt):
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")

    cur = conn.cursor()

    scraper = SCRAPER_MAP.get(olt["brand"])
    if not scraper:
        conn.close()
        return False, f"Unsupported OLT brand: {olt['brand']}"

    try:
        # ===============================
        # DATA ONU SEBELUM SYNC (ANTI-SPAM)
        # ===============================
        cur.execute("""
            SELECT pon, onu_id, status, rx_power, diagnosis
            FROM onu_status
            WHERE olt_id=?
        """, (olt["id"],))

        old_onu = {
            (str(r["pon"]), str(r["onu_id"])): r
            for r in cur.fetchall()
        }

        # ===============================
        # SCRAPE ONU
        # ===============================
        onus = scraper(olt)

        cur.execute("BEGIN IMMEDIATE")

        olt_onu_keys = set()
        alert_count = 0
        recovery_count = 0

        for onu in onus:
            pon = str(onu.get("pon"))
            onu_id = str(onu.get("onu_id"))
            olt_onu_keys.add((pon, onu_id))

            raw_status = onu.get("status")
            rx = onu.get("rx_power")

            # STATUS = RAW OLT
            onu["status"] = raw_status

            # DIAGNOSIS = LOGIKA FAMS
            onu["diagnosis"] = map_diagnosis(
                olt["brand"],
                raw_status,
                rx
            )

            prev = old_onu.get((pon, onu_id))
            prev_diag = prev["diagnosis"] if prev else None

            # SIMPAN ONU
            upsert_onu(cur, olt["id"], onu)

            curr_diag = onu["diagnosis"]

            # ===============================
            # CEK TOGGLE TELEGRAM
            # ===============================
            cur.execute("""
                SELECT alert_telegram
                FROM onu_status
                WHERE olt_id=? AND pon=? AND onu_id=?
            """, (olt["id"], pon, onu_id))
            row = cur.fetchone()
            if not row or not row["alert_telegram"]:
                continue

            # ===============================
            # RECOVERY ALERT
            # ===============================
            if prev and is_recovery(prev_diag, curr_diag):
                rx_text = "-" if rx is None else f"{rx:.2f} dBm"

                msg = (
                    "✅ <b>ONT RECOVERY</b>\n\n"
                    f"<b>OLT</b>       : {olt['name']}\n"
                    f"<b>PON / ONU</b> : {pon} / {onu_id}\n"
                    f"<b>Nama</b>      : {onu.get('name','-')}\n"
                    f"<b>Status OLT</b>: {raw_status}\n"
                    f"<b>RX Power</b>  : {rx_text}\n"
                    f"<b>Keterangan</b>: ONT kembali normal"
                )

                send_telegram(msg)
                recovery_count += 1
                continue

            # ===============================
            # ALERT BERMASALAH
            # ===============================
            if not is_problem_diagnosis(curr_diag):
                continue

            # ANTI-SPAM (diagnosis & rx tidak berubah)
            if prev:
                if prev_diag == curr_diag and prev["rx_power"] == rx:
                    continue

            rx_text = "-" if rx is None else f"{rx:.2f} dBm"

            msg = (
                "🚨 <b>ONT BERMASALAH</b>\n\n"
                f"<b>OLT</b>       : {olt['name']}\n"
                f"<b>PON / ONU</b> : {pon} / {onu_id}\n"
                f"<b>Nama</b>      : {onu.get('name','-')}\n"
                f"<b>Status OLT</b>: {raw_status}\n"
                f"<b>RX Power</b>  : {rx_text}\n"
                f"<b>Diagnosis</b> : {curr_diag}"
            )

            send_telegram(msg)
            alert_count += 1

        # ===============================
        # HAPUS ONU SUDAH TIDAK ADA
        # ===============================
        cur.execute("""
            SELECT pon, onu_id
            FROM onu_status
            WHERE olt_id=?
        """, (olt["id"],))

        db_onu_keys = {
            (str(r["pon"]), str(r["onu_id"]))
            for r in cur.fetchall()
        }

        to_delete = db_onu_keys - olt_onu_keys
        if to_delete:
            cur.executemany("""
                DELETE FROM onu_status
                WHERE olt_id=? AND pon=? AND onu_id=?
            """, [
                (olt["id"], pon, onu_id)
                for pon, onu_id in to_delete
            ])

        conn.commit()

        msg = (
            f"Sync OK ({len(onus)} ONT)"
            f", Alert: {alert_count}"
            f", Recovery: {recovery_count}"
        )
        if to_delete:
            msg += f", {len(to_delete)} ONU dihapus"

        return True, msg

    except Exception as e:
        conn.rollback()
        return False, str(e)

    finally:
        conn.close()
