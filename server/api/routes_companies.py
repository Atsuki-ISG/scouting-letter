import logging

from fastapi import APIRouter, Depends, HTTPException

from auth.api_key import verify_api_key
from db.sheets_client import sheets_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["companies"])


@router.get("/companies")
async def list_companies(
    operator: dict = Depends(verify_api_key),
):
    """Return list of unique company IDs from all sheets."""
    return {"companies": sheets_client.get_company_list()}


@router.get("/companies/{company_id}/config")
async def get_company_config(
    company_id: str,
    operator: dict = Depends(verify_api_key),
):
    """Return templates, job_offers, validation_config for Chrome extension."""
    try:
        return sheets_client.get_company_config(company_id)
    except Exception as e:
        logger.error(f"Config取得エラー ({company_id}): {e}")
        raise HTTPException(status_code=500, detail=f"設定読み込みエラー: {str(e)}")


@router.post("/reload")
async def reload_config(
    operator: dict = Depends(verify_api_key),
):
    """Reload config from Google Sheets."""
    sheets_client.reload()
    return {"status": "reloaded"}
