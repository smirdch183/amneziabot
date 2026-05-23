import json
from datetime import datetime
from pathlib import Path

from utils import now

DB_FILE = Path("users.json")


def load_users():
    try:
        with DB_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_users(data):
    with DB_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def add_user(user_id, username, first_name):
    users = load_users()
    uid = str(user_id)

    if uid in users:
        return False

    users[uid] = {
        "first_name": first_name,
        "username": username,
        "subscription_text": None,
        "subscription_end": None,
        "notified_1day": False,
        "notified_0day": False,
    }
    save_users(users)
    return True


def parse_subscription_end(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_user_status(user):
    sub_text = user.get("subscription_text")
    end = parse_subscription_end(user.get("subscription_end"))

    if not sub_text and not end:
        return "empty"
    if not sub_text:
        return "no_access"
    if not end:
        return "no_date"
    if end < now():
        return "expired"
    return "active"


def summarize_users(users=None):
    users = users if users is not None else load_users()
    summary = {
        "total": len(users),
        "active": 0,
        "expired": 0,
        "empty": 0,
        "no_access": 0,
        "no_date": 0,
    }

    for user in users.values():
        status = get_user_status(user)
        summary[status] = summary.get(status, 0) + 1

    return summary
