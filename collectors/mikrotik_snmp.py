from pysnmp.hlapi import *
import sqlite3

ROUTER_IP = "172.16.81.1"
COMMUNITY = "dashboard"
DB_PATH = "data/dashboard.db"

def walk(oid):
    for (eInd, eStat, eIdx, varBinds) in nextCmd(
        SnmpEngine(),
        CommunityData(COMMUNITY),
        UdpTransportTarget((ROUTER_IP, 161), timeout=2, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False
    ):
        if eInd or eStat:
            return
        for vb in varBinds:
            yield vb

interfaces = {}

# Nama interface
for oid, val in walk("1.3.6.1.2.1.2.2.1.2"):
    idx = oid.prettyPrint().split('.')[-1]
    interfaces[idx] = {"name": str(val)}

# RX
for oid, val in walk("1.3.6.1.2.1.31.1.1.1.6"):
    idx = oid.prettyPrint().split('.')[-1]
    interfaces.setdefault(idx, {})["rx"] = int(val)

# TX
for oid, val in walk("1.3.6.1.2.1.31.1.1.1.10"):
    idx = oid.prettyPrint().split('.')[-1]
    interfaces.setdefault(idx, {})["tx"] = int(val)

conn = sqlite3.connect(DB_PATH, timeout=10)
cur = conn.cursor()

for i in interfaces.values():
    name = i.get("name", "")
    lname = name.lower()

    if "pppoe-" not in lname:
        continue

    # contoh name: <pppoe-lukman@khasnetwork.com>
    clean = name.strip("<>")          # pppoe-lukman@khasnetwork.com
    clean = clean.replace("pppoe-", "")  # lukman@khasnetwork.com

    username = clean.strip()

    # proteksi
    if "@" not in username:
        continue

    cur.execute("""
        INSERT INTO pppoe_active
        (router_id, username, interface, rx_bytes, tx_bytes)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(router_id, username)
        DO UPDATE SET
            rx_bytes=excluded.rx_bytes,
            tx_bytes=excluded.tx_bytes,
            last_update=CURRENT_TIMESTAMP
    """, (
        username,
        name,
        i.get("rx", 0),
        i.get("tx", 0)
    ))


    username = i["name"].replace("pppoe-", "")

    cur.execute("""
        INSERT INTO pppoe_active
        (router_id, username, interface, rx_bytes, tx_bytes)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(router_id, username)
        DO UPDATE SET
            rx_bytes=excluded.rx_bytes,
            tx_bytes=excluded.tx_bytes,
            last_update=CURRENT_TIMESTAMP
    """, (
        username,
        i["name"],
        i.get("rx", 0),
        i.get("tx", 0)
    ))

conn.commit()
conn.close()

print("✔ PPPoE SNMP sync done")
