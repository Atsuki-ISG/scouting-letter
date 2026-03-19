import os

PROJECT_ID: str = os.environ.get("PROJECT_ID", "")
LOCATION: str = os.environ.get("LOCATION", "us-central1")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
MOCK_AI: bool = os.environ.get("MOCK_AI", "").lower() in ("1", "true", "yes")
MAX_BATCH_CONCURRENCY: int = int(os.environ.get("MAX_BATCH_CONCURRENCY", "10"))
CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "*")

# Google Sheets
SPREADSHEET_ID: str = os.environ.get("SPREADSHEET_ID", "")

# API Keys (comma-separated valid keys)
API_KEYS: str = os.environ.get("API_KEYS", "")
API_KEY_DEV: str = os.environ.get("API_KEY_DEV", "")

# Cache TTL (seconds). 0 = manual reload only via /api/v1/reload
CACHE_TTL_SECONDS: int = int(os.environ.get("CACHE_TTL_SECONDS", "0"))
