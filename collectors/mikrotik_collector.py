from pysnmp.hlapi import *
from db.db import get_db

def snmp_get(host, community, port, oid):
    it = getCmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
        UdpTransportTarget((host, port), timeout=2, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    )
    eInd, eStat, eIdx, varBinds = next(it)
    if eInd or eStat:
        raise Exception(eInd or eStat.prettyPrint())
    return varBinds[0][1]

def run():
    conn = get_db()
    cur = conn.cursor()

    routers = cur.execute("""
        SELECT id, host, snmp_community, snmp_port
        FROM mikrotik_devices
        WHERE enabled=1
    """).fetchall()

    for r in routers:
        try:
            sys_name   = str(snmp_get(r["host"], r["snmp_community"], r["snmp_port"], "1.3.6.1.2.1.1.5.0"))
            sys_descr  = str(snmp_get(r["host"], r["snmp_community"], r["snmp_port"], "1.3.6.1.2.1.1.1.0"))
            sys_uptime = int(snmp_get(r["host"], r["snmp_community"], r["snmp_port"], "1.3.6.1.2.1.1.3.0"))

            cur.execute("""
                UPDATE mikrotik_devices
                SET
                    sys_name   = ?,
                    sys_descr  = ?,
                    sys_uptime = ?,
                    last_seen  = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (sys_name, sys_descr, sys_uptime, r["id"]))

            print(f"[OK] {r['host']}")

        except Exception as e:
            print(f"[FAIL] {r['host']} → {e}")

    conn.close()

if __name__ == "__main__":
    run()
