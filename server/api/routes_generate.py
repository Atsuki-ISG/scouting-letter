import logging

from fastapi import APIRouter, Depends, HTTPException

from auth.api_key import verify_api_key
from db.sheets_client import sheets_client
from models import (
    GenerateRequest,
    GenerateResponse,
    BatchGenerateRequest,
    BatchGenerateResponse,
    PersonalizedGenerateRequest,
    PersonalizedGenerateResponse,
)
from pipeline.orchestrator import generate_single, generate_batch
from pipeline.personalized_scout.pipeline import generate_personalized_scout

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
    try:
        return await generate_batch(request, sheets_client)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"バッチ生成エラー ({request.company_id}): {error_msg}")
        if "quota" in error_msg.lower() or "resource_exhausted" in error_msg.lower() or "429" in error_msg:
            raise HTTPException(status_code=429, detail="Gemini APIの枠を超過しました。しばらく待つか、APIキーの課金設定を確認してください")
        raise HTTPException(status_code=500, detail=f"生成エラー: {error_msg}")


@router.post("/generate/personalized", response_model=PersonalizedGenerateResponse)
async def generate_personalized_endpoint(
    request: PersonalizedGenerateRequest,
    operator: dict = Depends(verify_api_key),
):
    """Developer-mode endpoint. Runs the L2/L3 personalized_scout
    pipeline (structured JSON output). Completely parallel to the
    L1 `/generate` — nothing in the existing flow is shared at the
    endpoint level.
    """
    opts = request.options
    try:
        result_dict = await generate_personalized_scout(
            company_id=request.company_id,
            profile=request.profile,
            level=opts.level,
            template_row_index=opts.template_row_index,
            force_employment=opts.force_employment,
            job_category_filter=opts.job_category_filter,
            is_resend=opts.is_resend,
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"[{request.profile.member_id}] personalized生成エラー: {error_msg}"
        )
        if "quota" in error_msg.lower() or "resource_exhausted" in error_msg.lower() or "429" in error_msg:
            raise HTTPException(
                status_code=429,
                detail="Gemini APIの枠を超過しました。しばらく待つか、APIキーの課金設定を確認してください",
            )
        raise HTTPException(status_code=500, detail=f"生成エラー: {error_msg}")

    # Strip internal-only token usage before serialization (it's not in
    # the response model).
    result_dict.pop("token_usage", None)
    return PersonalizedGenerateResponse(**result_dict)
