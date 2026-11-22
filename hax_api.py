"""Client for the user's existing HAX_RESELLER service."""
from __future__ import annotations
import threading
import time
from urllib.parse import quote
from typing import Any
import requests
from config import HAX_API_BASE_URL, HAX_ADMIN_USERNAME, HAX_ADMIN_PASSWORD

class HaxApiError(RuntimeError):
    pass

class HaxApi:
    def __init__(self) -> None:
        self.base_url = HAX_API_BASE_URL.rstrip("/")
        self.session = requests.Session()
        self._token = ""
        self._token_expiry = 0.0
        self._lock = threading.RLock()

    def _login(self) -> None:
        if not HAX_ADMIN_USERNAME or not HAX_ADMIN_PASSWORD:
            raise HaxApiError("أضف HAX_ADMIN_USERNAME و HAX_ADMIN_PASSWORD إلى متغيرات الاستضافة.")
        try:
            response = self.session.post(
                f"{self.base_url}/api/auth/admin/login",
                json={"username": HAX_ADMIN_USERNAME, "password": HAX_ADMIN_PASSWORD},
                timeout=15,
            )
            data = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as exc:
            raise HaxApiError(f"تعذر تسجيل الدخول إلى خادم HAX: {exc}") from exc
        if not response.ok or not data.get("token"):
            raise HaxApiError(str(data.get("error", f"HTTP {response.status_code}")))
        self._token = str(data["token"])
        self._token_expiry = time.time() + max(60, int(data.get("expiresIn", 28800)) - 120)

    def _request(self, method: str, path: str, auth: bool = True, body: dict | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if auth:
            with self._lock:
                if not self._token or time.time() >= self._token_expiry:
                    self._login()
                headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self.session.request(method, self.base_url + path, headers=headers, json=body, timeout=20)
            data = response.json() if response.content else {}
            if response.status_code == 401 and auth:
                with self._lock:
                    self._token = ""
                    self._login()
                    headers["Authorization"] = f"Bearer {self._token}"
                response = self.session.request(method, self.base_url + path, headers=headers, json=body, timeout=20)
                data = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as exc:
            raise HaxApiError(f"تعذر الاتصال بخادم HAX: {exc}") from exc
        if not response.ok:
            raise HaxApiError(str(data.get("error", f"خطأ الخادم HTTP {response.status_code}")))
        return data if isinstance(data, dict) else {}

    def health(self): return self._request("GET", "/health", auth=False)
    def maintenance(self): return self._request("GET", "/api/public/maintenance", auth=False)
    def set_maintenance(self, active: bool):
        return self._request("PATCH", "/api/admin/settings/maintenance", body={"client": bool(active)})
    def overview(self): return self._request("GET", "/api/admin/overview")
    def list_keys(self): return self._request("GET", "/api/admin/keys").get("keys", [])
    def create_keys(self, duration_ms: int, quantity: int = 1, devices: int = 1):
        return self._request("POST", "/api/admin/keys", body={
            "durationMs": int(duration_ms), "quantity": int(quantity), "devices": int(devices)
        }).get("keys", [])
    def reset_key(self, key_id: str):
        return self._request("POST", f"/api/admin/keys/{quote(key_id, safe='')}/reset", body={})
    def check_key(self, code: str):
        return self._request("POST", "/api/check", auth=False, body={"code": code})

hax_api = HaxApi()
