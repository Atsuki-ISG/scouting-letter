from __future__ import annotations

import re


# Priority-ordered mapping: first match wins
_QUALIFICATION_MAP: list[tuple[str, str]] = [
    ("看護師", "nurse"),
    ("准看護師", "nurse"),
    ("理学療法士", "rehab_pt"),
    ("言語聴覚士", "rehab_st"),
    ("作業療法士", "rehab_ot"),
    ("管理栄養士", "dietitian"),
    ("栄養士", "dietitian"),
    ("主任相談支援専門員", "counselor"),
    ("相談支援従事者研修", "counselor"),
    ("相談支援専門員", "counselor"),
    ("医療事務", "medical_office"),
]

_DESIRED_JOB_FALLBACK: list[tuple[str, str]] = [
    ("相談支援専門員", "counselor"),
    ("医療事務", "medical_office"),
    ("受付", "medical_office"),
]


def resolve_job_category(qualifications: str, desired_job: str = "") -> str | None:
    """Resolve qualifications string to a job category.

    Args:
        qualifications: Comma or slash separated qualification string.
        desired_job: Desired job string (used for fallback).

    Returns:
        Job category string or None if no match.
    """
    if not qualifications:
        # Check desired_job as fallback
        return _check_desired_job(desired_job)

    # Normalize separators and split
    normalized = qualifications.replace("/", ",").replace("／", ",").replace("、", ",")
    quals = [q.strip() for q in normalized.split(",") if q.strip()]

    for qual_keyword, category in _QUALIFICATION_MAP:
        for q in quals:
            if qual_keyword in q:
                return category

    # Fallback: check desired_job
    return _check_desired_job(desired_job)


def _check_desired_job(desired_job: str) -> str | None:
    """Check desired_job string for category fallback."""
    if not desired_job:
        return None
    for keyword, category in _DESIRED_JOB_FALLBACK:
        if keyword in desired_job:
            return category
    return None
