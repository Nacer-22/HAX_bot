""""Configuration for the HAX_NON_ROOT Telegram bot.
All credentials are read from environment variables. Never commit a .env file.
"""
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Set it in the hosting environment.")

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()}
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS must contain at least one Telegram user ID.")

HAX_API_BASE_URL = os.getenv(
    "HAX_API_BASE_URL", "https://haxreseller-production.up.railway.app"
).strip().rstrip("/")
HAX_ADMIN_USERNAME = os.getenv("HAX_ADMIN_USERNAME", "").strip()
HAX_ADMIN_PASSWORD = os.getenv("HAX_ADMIN_PASSWORD", "")
DATA_FILE = os.getenv("DATA_FILE", "data.json").strip() or "data.json"
SUPPORT_CHANNEL = os.getenv("SUPPORT_CHANNEL", "").strip()
BOT_BRAND = "HAX_NON_ROOT"
OWNER_BRAND = "Nacer_22"

if not HAX_API_BASE_URL.startswith("https://"):
    raise RuntimeError("HAX_API_BASE_URL must use HTTPS.")
