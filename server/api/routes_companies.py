import logging

from fastapi import APIRouter, Depends, HTTPException

from auth.api_key import verify_api_key
from db.sheets_client import sheets_client
from db.sheets_writer import sheets_writer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["companies"])


@router.get("/companies")
async def list_companies(
    operator: dict = Depends(verify_api_key),
):
    """Return list of companies with detection keywords."""
    return {"companies": sheets_client.get_companies_with_keywords()}


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
    """Reload config from Google Sheets and ensure sheet headers are up to date."""
    # Directly update profile sheet header row
    try:
        sheets_writer.update_row("プロフィール", 1, ["company", "content", "detection_keywords"])
    except Exception as e:
        logger.warning(f"Profile header update failed: {e}")
    sheets_client.reload()
    return {"status": "reloaded"}
