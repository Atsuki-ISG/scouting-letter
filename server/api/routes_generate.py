import logging

from fastapi import APIRouter, Depends, HTTPException

from auth.api_key import verify_api_key
from db.sheets_client import sheets_client
from models import GenerateRequest, GenerateResponse, BatchGenerateRequest, BatchGenerateResponse
from pipeline.orchestrator import generate_single, generate_batch

logger = logging.getLogger(__name__)
router = APIRouter(tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
async def generate_scout(
    request: GenerateRequest,
    operator: dict = Depends(verify_api_key),
):
    try:
        return await generate_single(request, sheets_client)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[{request.profile.member_id}] 生成エラー: {error_msg}")
        if "quota" in error_msg.lower() or "resource_exhausted" in error_msg.lower() or "429" in error_msg:
            raise HTTPException(status_code=429, detail="Gemini APIの枠を超過しました。しばらく待つか、APIキーの課金設定を確認してください")
        raise HTTPException(status_code=500, detail=f"生成エラー: {error_msg}")


@router.post("/generate/batch", response_model=BatchGenerateResponse)
async def batch_generate_scout(
    request: BatchGenerateRequest,
    operator: dict = Depends(verify_api_key),
):
    return await generate_batch(request, sheets_client)
