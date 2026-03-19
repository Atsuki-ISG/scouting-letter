from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from config import API_KEYS, API_KEY_DEV

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Parse valid keys from comma-separated env var
_valid_keys: set = set()


def _get_valid_keys() -> set:
    global _valid_keys
    if not _valid_keys:
        if API_KEYS:
            _valid_keys = {k.strip() for k in API_KEYS.split(",") if k.strip()}
    return _valid_keys


async def verify_api_key(
    api_key: str = Security(api_key_header),
) -> dict:
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    # Development mode
    if API_KEY_DEV and api_key == API_KEY_DEV:
        return {"operator_id": "dev", "name": "Development", "role": "admin"}

    # Production: check against env var list
    if api_key in _get_valid_keys():
        return {"operator_id": "operator", "name": "Operator", "role": "operator"}

    raise HTTPException(status_code=401, detail="Invalid API key")
