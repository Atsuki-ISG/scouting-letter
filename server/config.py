import os

PROJECT_ID: str = os.environ.get("PROJECT_ID", "")
LOCATION: str = os.environ.get("LOCATION", "us-central1")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
# Pro model for analysis / template improvement (low-frequency, higher quality)
GEMINI_PRO_MODEL: str = os.environ.get("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview")
# Fallback chain used when the primary model returns 429 (RPD/TPM exhausted).
# Tried in order. Accepts "|" or "," as separator so it can be set via
# `gcloud run deploy --update-env-vars` without conflicting with gcloud's own
# comma delimiter. Empty string disables fallback.
GEMINI_FALLBACK_MODELS: str = os.environ.get(
    "GEMINI_FALLBACK_MODELS", "gemini-2.5-flash"
)
# Thinking budget for models that support it (gemini-3-*, gemini-2.5-*).
# 0 = disable thinking. Typical values: 1024 (low), 4096 (medium), 8192 (high).
GEMINI_THINKING_BUDGET: int = int(os.environ.get("GEMINI_THINKING_BUDGET", "8192"))
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
MOCK_AI: bool = os.environ.get("MOCK_AI", "").lower() in ("1", "true", "yes")
MAX_BATCH_CONCURRENCY: int = int(os.environ.get("MAX_BATCH_CONCURRENCY", "10"))
# Per-request timeout for individual Gemini calls (seconds). When a single
# call hangs longer than this, asyncio raises TimeoutError so the batch's
# semaphore slot is released and the remaining candidates can proceed.
GEMINI_REQUEST_TIMEOUT: float = float(os.environ.get("GEMINI_REQUEST_TIMEOUT", "90"))
CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "*")

# Google Sheets
SPREADSHEET_ID: str = os.environ.get("SPREADSHEET_ID", "")

# Authentication
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")

# Cache TTL (seconds). 0 = manual reload only via /api/v1/reload
CACHE_TTL_SECONDS: int = int(os.environ.get("CACHE_TTL_SECONDS", "0"))

# Cost monitoring
GOOGLE_CHAT_WEBHOOK_URL: str = os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", "")
COST_ALERT_THRESHOLD_USD: float = float(os.environ.get("COST_ALERT_THRESHOLD_USD", "100.0"))

# Model pricing (USD per 1M tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-flash-preview": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}


def get_model_pricing(model_name: str) -> dict[str, float]:
    """Get pricing for a model by partial match. Returns {"input": 0, "output": 0} if unknown."""
    for key, pricing in MODEL_PRICING.items():
        if key in model_name:
            return pricing
    return {"input": 0.0, "output": 0.0}
