"""Test-wide fixtures.

We do NOT touch real Supabase / Notion / Gemini in tests. Anything that needs
network is monkey-patched per-test.
"""

from __future__ import annotations

import os

# Set fake env BEFORE any module that reads `Settings`.
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "fake-key")
os.environ.setdefault("GEMINI_API_KEY", "fake-gemini")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:fake")
os.environ.setdefault("TELEGRAM_OWNER_ID", "1")
os.environ.setdefault("NOTION_API_KEY", "fake-notion")
os.environ.setdefault("NOTION_SYNC_ENABLED", "true")
os.environ.setdefault("ENV", "development")
