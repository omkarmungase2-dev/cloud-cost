"""
Configuration loader.
Reads all settings from environment variables (loaded from .env by python-dotenv).
Provider keys never leave this module — they are only used when building the
Authorization header for upstream calls.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Provider ---
UPSTREAM_URL: str = os.getenv("UPSTREAM_URL", "http://127.0.0.1:9000/v1/chat/completions")
UPSTREAM_KEY: str = os.getenv("UPSTREAM_KEY", "")

# --- Infrastructure ---
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://firewall:firewall@localhost:5432/firewall")

# --- Telegram (optional, both must be set to enable) ---
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Advanced ---
# Some providers use max_completion_tokens instead of max_tokens.
MAX_TOKENS_FIELD: str = os.getenv("MAX_TOKENS_FIELD", "max_tokens")
