"""Atomic JSON storage for HAX_NON_ROOT Telegram users and shop data."""
from __future__ import annotations
import copy, json, os, secrets, threading, time
from pathlib import Path
from typing import Any, Callable
from config import DATA_FILE

_LOCK = threading.RLock()
_DEFAULTS = {
    "users": {}, "products": {},
    "settings": {
        "referral_points": 5, "daily_gift_points": 3, "daily_gift_cooldown": 86400,
        "key_durations": {"3600": 2, "10800": 4, "21600": 7, "43200": 12, "86400": 16, "604800": 45, "2592000": 120},
        "required_channels": [], "maintenance_message": "البوت تحت الصيانة مؤقتاً. حاول لاحقاً."
    },
    "stats": {"keys_created": 0, "points_issued": 0, "products_sold": 0}
}

def _normalize(data: dict) -> dict:
    for key, value in _DEFAULTS.items():
        if key not in data or not isinstance(data[key], type(value)):
            data[key] = copy.deepcopy(value)
    for key, value in _DEFAULTS["settings"].items():
        data["settings"].setdefault(key, copy.deepcopy(value))
    for key, value in _DEFAULTS["stats"].items():
        data["stats"].setdefault(key, value)
    return data

def load() -> dict:
    with _LOCK:
        path = Path(DATA_FILE)
        if not path.exists():
            data = copy.deepcopy(_DEFAULTS)
            save(data)
            return data
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict): raise ValueError("JSON root must be an object")
            return _normalize(data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"تعذرت قراءة قاعدة بيانات البوت: {exc}") from exc

def save(data: dict) -> None:
    with _LOCK:
        path = Path(DATA_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

def mutate(operation: Callable[[dict], Any]) -> Any:
    with _LOCK:
        data = load()
        result = operation(data)
        save(data)
        return result

def get_user(uid: int):
    return load()["users"].get(str(uid))

def register_user(uid: int, first_name: str, username: str = "", ref_code: str = ""):
    def op(data):
        users = data["users"]; skey = str(uid)
        if skey in users: return users[skey], False, None
        referrer = None
        for existing_id, candidate in users.items():
            if candidate.get("referral_code", "").upper() == ref_code.strip().upper() and ref_code and int(existing_id) != uid:
                referrer = int(existing_id); break
        user = {
            "user_id": uid, "first_name": first_name[:100], "username": username[:64],
            "points": 0, "referral_code": "HAX" + secrets.token_hex(4).upper(),
            "referred_by": referrer, "total_referrals": 0, "joined_at": int(time.time()),
            "last_daily_gift": 0, "is_banned": False, "keys": [], "purchases": [], "last_reset": {}
        }
        users[skey] = user
        if referrer:
            users[str(referrer)]["total_referrals"] = users[str(referrer)].get("total_referrals", 0) + 1
            reward = int(data["settings"].get("referral_points", 5))
            users[str(referrer)]["points"] = users[str(referrer)].get("points", 0) + reward
            data["stats"]["points_issued"] += reward
        return user, True, referrer
    return mutate(op)

def add_points(uid: int, amount: int):
    def op(data):
        user = data["users"].get(str(uid))
        if not user: return False
        user["points"] = int(user.get("points", 0)) + int(amount)
        if amount > 0: data["stats"]["points_issued"] += amount
        return True
    return bool(mutate(op))

def debit_points(uid: int, amount: int):
    def op(data):
        user = data["users"].get(str(uid))
        if not user or int(user.get("points", 0)) < amount: return False
        user["points"] -= int(amount)
        return True
    return bool(mutate(op))

def add_owned_key(uid: int, key: dict):
    def op(data):
        user = data["users"].get(str(uid))
        if not user: raise KeyError("User not registered")
        user.setdefault("keys", []).append(key)
        data["stats"]["keys_created"] += 1
    mutate(op)

def get_settings(): return load()["settings"]
def update_settings(values: dict): mutate(lambda data: data["settings"].update(values))
def all_users(): return load()["users"]
def all_products(): return load()["products"]

def add_product(name: str, price: int, description: str, content: str):
    product_id = secrets.token_hex(4)
    def op(data):
        data["products"][product_id] = {
            "name": name[:80], "price": int(price), "description": description[:500],
            "content": content, "active": True, "created_at": int(time.time()), "sold_count": 0
        }
    mutate(op)
    return product_id

def record_product_sale(uid: int, product_id: str):
    def op(data):
        product = data["products"][product_id]
        product["sold_count"] = int(product.get("sold_count", 0)) + 1
        data["users"][str(uid)].setdefault("purchases", []).append({
            "product_id": product_id, "name": product["name"], "at": int(time.time())
        })
        data["stats"]["products_sold"] += 1
    mutate(op)

def stats():
    data = load()
    return {**data["stats"], "total_users": len(data["users"]), "total_products": len(data["products"])}
