from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from config import ADMIN_PASSWORD

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str = Security(api_key_header),
) -> dict:
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    if ADMIN_PASSWORD and api_key == ADMIN_PASSWORD:
        return {"operator_id": "operator", "name": "Operator", "role": "admin"}

    raise HTTPException(status_code=401, detail="Invalid password")
