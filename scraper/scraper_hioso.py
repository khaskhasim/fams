#!/usr/bin/env python3
import requests
import re
import time
import json
import os
import sqlite3
from datetime import datetime
from requests.auth import HTTPBasicAuth

# =================================================
# PATH PROJECT
# =================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH  = os.path.join(BASE_DIR, "db", "olt.db")   # sesuaikan jika beda

os.makedirs(DATA_DIR, exist_ok=True)

DELAY = 0.5

# =================================================
# AMBIL OLT DARI DATABASE
# =================================================
def get_hioso_olts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, host, username, password
        FROM olt_devices
        WHERE brand='hioso' AND is_active=1
    """)

    rows = cur.fetchall()
    conn.close()
    return rows

# =================================================
# SCRAPE 1 OLT HIOSO
# =================================================
def scrape_hioso(olt):
    BASE_URL = f"http://{olt['host']}"
    USERNAME = olt["username"]
    PASSWORD = olt["password"]

    OLT_NAME = olt["name"]
    BRAND    = "HIOSO"

    OUTPUT_FILE = os.path.join(
        DATA_DIR,
        f"olt_{OLT_NAME.replace(' ', '_')}.json"
    )

    print(f"\n🔐 Login ke OLT HIOSO: {OLT_NAME}")

    session = requests.Session()
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    r = session.get(f"{BASE_URL}/", timeout=5)
    if r.status_code != 200:
        print(f"❌ Login gagal ke {OLT_NAME}")
        return

    print("✅ Login sukses")

    result = {
        "olt_name": OLT_NAME,
        "brand": BRAND,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pon": {}
    }

    # =================================================
    # AMBIL LIST PON
    # =================================================
    print("📡 Mengambil daftar PON ...")
    r = session.get(f"{BASE_URL}/onuConfigPonList.asp", timeout=10)
    time.sleep(DELAY)

    pon_list = sorted(set(re.findall(r"'(\d+/\d+/\d+)'", r.text)))
    if not pon_list:
        print("❌ Tidak ada PON ditemukan")
        return

    # =================================================
    # LOOP PON
    # =================================================
    for pon in pon_list:
        print(f"  🔌 PON {pon}")

        r = session.get(
            f"{BASE_URL}/onuConfigOnuList.asp?oltponno={pon}",
            timeout=10
        )
        time.sleep(DELAY)

        m = re.search(
            r"var\s+ponOnuTable\s*=\s*new Array\s*\((.*?)\);",
            r.text,
            re.S
        )

        if not m:
            continue

        fields = re.findall(r"'(.*?)'", m.group(1))
        ONU_FIELD = 13
        rows = [fields[i:i + ONU_FIELD] for i in range(0, len(fields), ONU_FIELD)]

        pon_data = {
            "total": 0,
            "online": 0,
            "down": 0,
            "power_off": 0,
            "unknown": 0,
            "onu": []
        }

        for onu in rows:
            if len(onu) < ONU_FIELD:
                continue

            pon_data["total"] += 1

            onu_id = int(onu[0].split(":")[-1])
            name   = onu[1]
            mac    = onu[2]
            raw    = onu[3].strip()

            temperature = onu[7]
            tx = onu[9]
            rx = onu[11]
            distance = onu[12]

            # ===== NORMALISASI STATUS =====
            if raw == "Up":
                status = "ONLINE"
                diagnosis = "NORMAL"
                pon_data["online"] += 1

            elif raw == "Down":
                status = "DOWN"
                diagnosis = "KABEL_PUTUS_OR_LOSS_BESAR"
                pon_data["down"] += 1

            elif raw in ["PwrDown", "Power Down", "PowerOff"]:
                status = "POWER_OFF"
                diagnosis = "ONU_MATI_OR_LISTRIK_PELANGGAN"
                pon_data["power_off"] += 1

            else:
                status = "UNKNOWN"
                diagnosis = "PERLU_CEK"
                pon_data["unknown"] += 1

            pon_data["onu"].append({
                "onu_id": onu_id,
                "name": name,
                "mac": mac,
                "raw_status": raw,
                "status": status,
                "diagnosis": diagnosis,
                "rx_power": float(rx) if rx else None,
                "tx_power": float(tx) if tx else None,
                "temperature": float(temperature) if temperature else None,
                "distance": int(distance) if distance else None
            })

        result["pon"][pon] = pon_data

    # =================================================
    # SIMPAN JSON
    # =================================================
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"📄 Data disimpan: {OUTPUT_FILE}")



# =================================================
# WRAPPER UNTUK DASHBOARD SYNC
# =================================================
def fetch_onu_hioso(olt):
    """
    Wrapper untuk dashboard sync
    return: list of ONU dict (standar onu_status)
    """

    BASE_URL = f"http://{olt['host']}"
    USERNAME = olt["username"]
    PASSWORD = olt["password"]

    session = requests.Session()
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    session.verify = False

    onu_result = []

    # login test
    r = session.get(f"{BASE_URL}/", timeout=5)
    if r.status_code != 200:
        return []

    r = session.get(f"{BASE_URL}/onuConfigPonList.asp", timeout=10)
    time.sleep(DELAY)

    pon_list = sorted(set(re.findall(r"'(\d+/\d+/\d+)'", r.text)))
    if not pon_list:
        return []

    for pon_str in pon_list:
        try:
            pon = int(pon_str.split("/")[-1])
        except:
            continue

        r = session.get(
            f"{BASE_URL}/onuConfigOnuList.asp?oltponno={pon_str}",
            timeout=10
        )
        time.sleep(DELAY)

        m = re.search(
            r"var\s+ponOnuTable\s*=\s*new Array\s*\((.*?)\);",
            r.text,
            re.S
        )
        if not m:
            continue

        fields = re.findall(r"'(.*?)'", m.group(1))
        ONU_FIELD = 13
        rows = [fields[i:i + ONU_FIELD] for i in range(0, len(fields), ONU_FIELD)]

        for onu in rows:
            if len(onu) < ONU_FIELD:
                continue

            try:
                onu_id = int(onu[0].split(":")[-1])
            except:
                continue

            name = onu[1]
            mac  = onu[2]
            raw  = onu[3].strip()
            tx   = onu[9]
            rx   = onu[11]

            if raw == "Up":
                status = "ONLINE"
                diagnosis = "NORMAL"
            elif raw == "Down":
                status = "DOWN"
                diagnosis = "KABEL_PUTUS"
            elif raw in ["PwrDown", "Power Down", "PowerOff"]:
                status = "POWER_OFF"
                diagnosis = "ONU_MATI"
            else:
                status = "UNKNOWN"
                diagnosis = "PERLU_CEK"

            onu_result.append({
                "pon": pon,
                "onu_id": onu_id,
                "sn": None,
                "mac": mac or None,
                "name": name or None,
                "status": status,
                "rx_power": float(rx) if rx else None,
                "tx_power": float(tx) if tx else None,
                "diagnosis": diagnosis
            })

    return onu_result




# =================================================
# MAIN
# =================================================
if __name__ == "__main__":
    olts = get_hioso_olts()

    if not olts:
        print("❌ Tidak ada OLT HIOSO di database")
        exit(1)

    for olt in olts:
        scrape_hioso(olt)

    print("\n✅ Semua OLT HIOSO selesai diproses")
