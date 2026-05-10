"""
config.py — Central configuration for the Cattle Spreads Dashboard.
All paths, host/port, and environment overrides live here.
"""
import os
from pathlib import Path

BASE_DIR     = Path(__file__).parent
XLSX_PATH    = BASE_DIR / "Copy of Cattle_Spreads.xlsx"
CACHE_PATH   = BASE_DIR / "cache" / "stats.json"
ARCHIVE_DIR  = BASE_DIR / "data" / "archive"

HOST  = os.environ.get("HOST", "0.0.0.0")
PORT  = int(os.environ.get("PORT", "5000"))
DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
