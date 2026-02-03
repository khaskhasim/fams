from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time

WAIT_TIME = 15


def fetch_onu_vsol(olt):
    """
    Scraping ONU VSOL via Selenium
    Return DATA MENTAH:
    - status ASLI dari VSOL
    - rx / tx
    - TANPA LOGIKA DIAGNOSIS
    """

    BASE_URL   = f"http://{olt['host']}"
    LOGIN_URL  = BASE_URL + "/action/login.html"
    STATUS_URL = BASE_URL + "/action/onustatusinfo.html"
    OPM_URL    = BASE_URL + "/action/onuopmdiag.html"

    USERNAME = olt["username"]
    PASSWORD = olt["password"]
    TOTAL_PON = int(olt.get("pon_count") or 4)

    # ===================== SELENIUM =====================
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--log-level=3")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    wait = WebDriverWait(driver, WAIT_TIME)

    onu_result = []

    # ===================== HELPER =====================
    def wait_table_loaded(timeout=15):
        WebDriverWait(driver, timeout).until(
            lambda d: len(
                d.find_elements(By.CSS_SELECTOR, "table[border='1'] tr")
            ) > 1
        )

    def change_pon(select, pon_id):
        driver.execute_script(
            """
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
            """,
            select,
            str(pon_id),
        )
        time.sleep(0.5)

    try:
        # ===================== LOGIN =====================
        driver.get(LOGIN_URL)

        wait.until(EC.presence_of_element_located((By.NAME, "user"))).send_keys(USERNAME)
        wait.until(EC.presence_of_element_located((By.NAME, "pass"))).send_keys(PASSWORD)
        driver.find_element(By.ID, "loginBtn").click()

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

        # ===================== LOOP PON =====================
        for pon_loop in range(1, TOTAL_PON + 1):

            # ---------- STATUS ----------
            driver.get(STATUS_URL)
            select = wait.until(EC.presence_of_element_located((By.NAME, "select")))
            change_pon(select, pon_loop)

            try:
                wait_table_loaded()
                soup = BeautifulSoup(driver.page_source, "html.parser")
                table = soup.find_all("table", border="1")[-1]
                rows = table.find_all("tr")[1:]
            except Exception:
                continue

            onu_status = {}

            for row in rows:
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                if len(cols) < 10:
                    continue

                onu_id_str = cols[0]
                status_raw = cols[1]
                mac = cols[2]
                name = cols[3]
                reason = cols[8]

                try:
                    port_part = onu_id_str.split("/")[-1]
                    pon_num, onu_num = port_part.split(":")
                    pon_num = int(pon_num)
                    onu_num = int(onu_num)
                except Exception:
                    continue

                # ===============================
                # STATUS RAW VSOL (APA ADANYA)
                # ===============================
                status = "UNKNOWN"

                if status_raw == "Online":
                    status = "ONLINE"
                elif reason == "Power Off":
                    status = "POWER_OFF"
                elif reason == "Wire Down":
                    status = "WIRE_DOWN"
                else:
                    status = "UNKNOWN"

                onu_status[(pon_num, onu_num)] = {
                    "mac": mac,
                    "name": name,
                    "status": status,
                }

            # ===================== OPM (RX / TX) =====================
            ONLINE_ONU = {
                k for k, v in onu_status.items() if v["status"] == "ONLINE"
            }

            opm_data = {}

            if ONLINE_ONU:
                driver.get(OPM_URL)
                select = wait.until(EC.presence_of_element_located((By.NAME, "select")))
                change_pon(select, pon_loop)

                try:
                    wait_table_loaded()
                    soup = BeautifulSoup(driver.page_source, "html.parser")
                    table = soup.find_all("table", border="1")[-1]
                    rows = table.find_all("tr")[1:]
                except Exception:
                    rows = []

                for row in rows:
                    cols = [c.get_text(strip=True) for c in row.find_all("td")]
                    if len(cols) < 9:
                        continue

                    onu_id_str = cols[0]

                    try:
                        port_part = onu_id_str.split("/")[-1]
                        pon_num, onu_num = port_part.split(":")
                        pon_num = int(pon_num)
                        onu_num = int(onu_num)
                    except Exception:
                        continue

                    if (pon_num, onu_num) not in ONLINE_ONU:
                        continue

                    try:
                        tx = float(cols[7]) if cols[7] else None
                    except Exception:
                        tx = None

                    try:
                        rx = float(cols[8]) if cols[8] else None
                    except Exception:
                        rx = None

                    opm_data[(pon_num, onu_num)] = {
                        "tx": tx,
                        "rx": rx,
                    }

            # ===================== MERGE DATA =====================
            for (pon_num, onu_num), info in onu_status.items():
                opm = opm_data.get((pon_num, onu_num), {})

                onu_result.append({
                    "pon": pon_num,
                    "onu_id": onu_num,
                    "sn": None,
                    "mac": info["mac"] or None,
                    "name": info["name"] or None,
                    "status": info["status"],      # RAW STATUS
                    "rx_power": opm.get("rx"),
                    "tx_power": opm.get("tx"),
                    "diagnosis": None,             # ⛔ TIDAK DIHITUNG DI SINI
                })

        return onu_result

    finally:
        driver.quit()
