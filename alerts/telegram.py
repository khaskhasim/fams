import requests
from db.db import get_db

def get_config():
    conn = get_db()
    cfg = conn.execute("""
        SELECT enabled, bot_token, chat_id
        FROM alert_telegram
        WHERE id=1
    """).fetchone()
    conn.close()
    return cfg


def send(message: str):
    cfg = get_config()

    if not cfg:
        return False, "Config not found"

    if not cfg["enabled"]:
        return False, "Telegram disabled"

    if not cfg["bot_token"] or not cfg["chat_id"]:
        return False, "Token / Chat ID kosong"

    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    payload = {
        "chat_id": cfg["chat_id"],
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        r = requests.post(url, data=payload, timeout=5)
        if r.status_code == 200:
            return True, "Message sent"
        else:
            return False, r.text
    except Exception as e:
        return False, str(e)
