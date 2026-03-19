from __future__ import annotations

import re


# Priority-ordered mapping: first match wins
_QUALIFICATION_MAP: list[tuple[str, str]] = [
    ("看護師", "nurse"),
    ("准看護師", "nurse"),
    ("理学療法士", "pt"),
    ("言語聴覚士", "st"),
    ("作業療法士", "ot"),
    ("医療事務", "medical_office"),
]

_DESIRED_JOB_MEDICAL_OFFICE_PATTERNS = re.compile(r"医療事務|受付")


def resolve_job_category(qualifications: str, desired_job: str = "") -> str | None:
    """Resolve qualifications string to a job category.

    Args:
        qualifications: Comma or slash separated qualification string.
        desired_job: Desired job string (used for medical_office fallback).

    Returns:
        Job category string or None if no match.
    """
    if not qualifications:
        # Still check desired_job for medical_office
        if desired_job and _DESIRED_JOB_MEDICAL_OFFICE_PATTERNS.search(desired_job):
            return "medical_office"
        return None

    # Normalize separators and split
    normalized = qualifications.replace("/", ",").replace("／", ",").replace("、", ",")
    quals = [q.strip() for q in normalized.split(",") if q.strip()]

    for qual_keyword, category in _QUALIFICATION_MAP:
        for q in quals:
            if qual_keyword in q:
                return category

    # Fallback: check desired_job for medical_office
    if desired_job and _DESIRED_JOB_MEDICAL_OFFICE_PATTERNS.search(desired_job):
        return "medical_office"

    return None
