import os

PROJECT_ID: str = os.environ.get("PROJECT_ID", "")
LOCATION: str = os.environ.get("LOCATION", "us-central1")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
MOCK_AI: bool = os.environ.get("MOCK_AI", "").lower() in ("1", "true", "yes")
MAX_BATCH_CONCURRENCY: int = int(os.environ.get("MAX_BATCH_CONCURRENCY", "10"))
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
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
}


def get_model_pricing(model_name: str) -> dict[str, float]:
    """Get pricing for a model by partial match. Returns {"input": 0, "output": 0} if unknown."""
    for key, pricing in MODEL_PRICING.items():
        if key in model_name:
            return pricing
    return {"input": 0.0, "output": 0.0}
