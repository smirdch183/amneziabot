from datetime import datetime
from zoneinfo import ZoneInfo

# ---------------- TIME ----------------

def now():
    return datetime.now(ZoneInfo("Europe/Moscow")).replace(microsecond=0, tzinfo=None)


# ---------------- BACKUP ----------------

def backup_json(filename):
    import json
    
    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    backup_filename = f"backup_{now().strftime('%d.%m.%Y')}.json"
    
    with open(backup_filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    return backup_filename