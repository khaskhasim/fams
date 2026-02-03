import requests
import re
import time
from requests.auth import HTTPBasicAuth

DELAY = 0.5

def fetch_onu_hioso(olt):
    """
    Scraping ONU HIOSO
    return: list of dict ONU (standar sync_onu)
    """

    BASE_URL = f"http://{olt['host']}"
    USERNAME = olt["username"]
    PASSWORD = olt["password"]

    session = requests.Session()
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    session.headers.update({
        "User-Agent": "Mozilla/5.0"
    })
    session.verify = False

    onu_result = []

    # ================= LOGIN TEST =================
    r = session.get(f"{BASE_URL}/", timeout=5)
    if r.status_code != 200:
        return []

    # ================= AMBIL LIST PON =================
    r = session.get(f"{BASE_URL}/onuConfigPonList.asp", timeout=10)
    time.sleep(DELAY)

    pon_list = sorted(set(re.findall(r"'(\d+/\d+/\d+)'", r.text)))
    if not pon_list:
        return []

    # ================= LOOP SETIAP PON =================
    for pon_str in pon_list:
        # contoh pon_str: 1/1/1 → kita ambil angka terakhir
        try:
            pon = int(pon_str.split("/")[-1])
        except:
            continue

        r = session.get(
            f"{BASE_URL}/onuConfigOnuList.asp?oltponno={pon_str}",
            timeout=10
        )
        time.sleep(DELAY)

        html = r.text

        m = re.search(
            r"var\s+ponOnuTable\s*=\s*new Array\s*\((.*?)\);",
            html,
            re.S
        )

        if not m:
            continue

        raw = m.group(1)
        fields = re.findall(r"'(.*?)'", raw)

        ONU_FIELD = 13
        rows = [fields[i:i + ONU_FIELD] for i in range(0, len(fields), ONU_FIELD)]

        # ================= LOOP ONU =================
        for onu in rows:
            if len(onu) < ONU_FIELD:
                continue

            try:
                pon_onu = onu[0]
                onu_id  = int(pon_onu.split(":")[-1])
            except:
                continue

            name        = onu[1]
            mac         = onu[2]
            raw_status  = onu[3].strip()

            temperature = onu[7]
            tx          = onu[9]
            rx          = onu[11]

            # ===== NORMALISASI STATUS =====
            if raw_status == "Up":
                status = "ONLINE"
                diagnosis = "NORMAL"

            elif raw_status == "Down":
                status = "DOWN"
                diagnosis = "KABEL_PUTUS_OR_LOSS_BESAR"

            elif raw_status in ["PwrDown", "Power Down", "PowerOff"]:
                status = "POWER_OFF"
                diagnosis = "ONU_MATI_OR_LISTRIK_PELANGGAN"

            else:
                status = "UNKNOWN"
                diagnosis = "PERLU_CEK"

            onu_result.append({
                "pon": pon,
                "onu_id": onu_id,
                "sn": None,                     # HIOSO tidak expose SN
                "mac": mac or None,
                "name": name or None,
                "status": status,
                "rx_power": float(rx) if rx else None,
                "tx_power": float(tx) if tx else None,
                "diagnosis": diagnosis
            })

    return onu_result
