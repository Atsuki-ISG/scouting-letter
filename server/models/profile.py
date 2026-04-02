from typing import Optional

from pydantic import BaseModel


class CandidateProfile(BaseModel):
    member_id: str
    gender: Optional[str] = None
    age: Optional[str] = None
    area: Optional[str] = None
    qualifications: Optional[str] = None
    experience_type: Optional[str] = None
    experience_years: Optional[str] = None
    employment_status: Optional[str] = None
    desired_job: Optional[str] = None
    desired_area: Optional[str] = None
    desired_employment_type: Optional[str] = None
    desired_start: Optional[str] = None
    self_pr: Optional[str] = None
    special_conditions: Optional[str] = None
    work_history_summary: Optional[str] = None
    scout_sent_date: Optional[str] = None
    is_favorite: bool = False
