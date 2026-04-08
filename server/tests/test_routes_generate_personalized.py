"""End-to-end route tests for POST /api/v1/generate/personalized.

Patches the Sheets client, AI generator, and validators so nothing
external is hit.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app
from pipeline.ai_generator import GenerationResult


def _fake_operator():
    return {"operator_id": "t", "name": "t", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


TEMPLATE_L3 = """{opening}

{bridge}

{facility_intro}

{job_framing}

{closing_cta}

## 募集要項
給与: 30万円
"""


FAKE_CONFIG = {
    "templates": {
        "nurse:パート_初回": {
            "type": "パート_初回",
            "job_category": "nurse",
            "body": TEMPLATE_L3,
            "_row_index": 2,
        },
    },
    "patterns": [],
    "qualification_modifiers": [],
    "prompt_sections": [],
    "job_offers": [
        {"job_category": "nurse", "employment_type": "パート", "id": "job_001", "name": "看護師"}
    ],
    "validation_config": {
        "age_min": 18,
        "age_max": 70,
        "qualification_rules": [],
        "category_exclusions": [],
    },
    "examples": [],
    "job_category_keywords": [],
}


def _profile_body():
    return {
        "member_id": "M100",
        "gender": "女性",
        "age": "35歳",
        "area": "東京都",
        "qualifications": "正看護師",
        "experience_type": "訪問看護",
        "experience_years": "10年",
        "employment_status": "離職中",
        "desired_job": "看護師",
        "desired_employment_type": "パート",
    }


@pytest.fixture
def all_mocks():
    async def fake_structured(system_prompt, user_prompt, response_schema, **kw):
        return {
            "opening": "固有導入文",
            "bridge": "橋渡し",
            "facility_intro": "施設紹介",
            "job_framing": "求人フレーム",
            "closing_cta": "CTA",
        }, GenerationResult(text="ok", model_name="mock")

    async def fake_filter(profile, company_id, job_category, validation_config):
        return None, []

    def fake_resolve(profile, categories, keywords, explicit=None):
        class R:
            category = "nurse"
            method = "m"
            debug = "m"
            warnings: list = []
            failure = None
        return R()

    with patch(
        "pipeline.personalized_scout.pipeline.sheets_client"
    ) as sc, patch(
        "pipeline.personalized_scout.generator.generate_structured",
        side_effect=fake_structured,
    ), patch(
        "pipeline.personalized_scout.pipeline.filter_candidate",
        side_effect=fake_filter,
    ), patch(
        "pipeline.personalized_scout.pipeline.resolve_job_category",
        side_effect=fake_resolve,
    ), patch(
        "pipeline.personalized_scout.pipeline.validate_output_text",
        return_value=[],
    ):
        sc.get_company_config.return_value = FAKE_CONFIG
        sc.get_company_profile.return_value = "会社プロフィール"
        yield sc


class TestGeneratePersonalizedRoute:
    def test_l3_returns_block_contents_and_stats(self, client, all_mocks):
        res = client.post(
            "/api/v1/generate/personalized",
            json={
                "company_id": "ark",
                "profile": _profile_body(),
                "options": {"level": "L3", "is_resend": False},
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["generation_path"] == "ai_structured"
        assert body["block_contents"]["opening"] == "固有導入文"
        assert set(body["block_contents"].keys()) == {
            "opening", "bridge", "facility_intro", "job_framing", "closing_cta"
        }
        assert "## 募集要項" in body["full_scout_text"]
        stats = body["personalization_stats"]
        assert stats["level"] == "L3"
        assert stats["personalized_chars"] > 0
        assert stats["fixed_chars"] > 0
        assert 0 < stats["ratio"] < 1

    def test_l2_empty_template_returns_filtered(self, client, all_mocks):
        # Override config to a template with no block placeholders
        all_mocks.get_company_config.return_value = {
            **FAKE_CONFIG,
            "templates": {
                "nurse:パート_初回": {
                    "type": "パート_初回",
                    "job_category": "nurse",
                    "body": "旧式 {personalized_text} のみ",
                    "_row_index": 2,
                }
            },
        }
        res = client.post(
            "/api/v1/generate/personalized",
            json={
                "company_id": "ark",
                "profile": _profile_body(),
                "options": {"level": "L2"},
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["generation_path"] == "filtered_out"
        assert "L2/L3 テンプレ未対応" in (body.get("filter_reason") or "")

    def test_missing_level_fails_validation(self, client):
        res = client.post(
            "/api/v1/generate/personalized",
            json={
                "company_id": "ark",
                "profile": _profile_body(),
                "options": {},
            },
        )
        assert res.status_code == 422
