from typing import List, Literal, Optional

from pydantic import BaseModel

from models.profile import CandidateProfile


class GenerateOptions(BaseModel):
    is_resend: bool = False
    force_seishain: bool = False  # deprecated: use force_employment instead
    force_employment: Optional[str] = None  # "パート" or "正社員" or None (auto)
    job_category_filter: Optional[str] = None  # "nurse", "rehab_pt", etc. or None (all)
    mock_ai: bool = False


class GenerateRequest(BaseModel):
    company_id: str
    profile: CandidateProfile
    options: Optional[GenerateOptions] = None


class BatchGenerateRequest(BaseModel):
    company_id: str
    profiles: List[CandidateProfile]
    options: Optional[GenerateOptions] = None
    concurrency: int = 10


class GenerateResponse(BaseModel):
    member_id: str
    template_type: str
    generation_path: Literal["ai", "pattern", "filtered_out"]
    pattern_type: Optional[str] = None
    personalized_text: str
    full_scout_text: str
    job_offer_id: Optional[str] = None
    job_category: Optional[str] = None
    filter_reason: Optional[str] = None
    validation_warnings: List[str] = []
    is_favorite: bool = False


class BatchGenerateResponse(BaseModel):
    results: List[GenerateResponse]
    summary: dict
