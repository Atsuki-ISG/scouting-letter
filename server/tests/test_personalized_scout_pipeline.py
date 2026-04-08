"""Integration tests for `generate_personalized_scout`.

We mock `sheets_client.get_company_config`, `get_company_profile`, and
`pipeline.ai_generator.generate_structured` so the test runs offline
with no Sheets or Gemini calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from models.profile import CandidateProfile
from pipeline.ai_generator import GenerationResult
from pipeline.personalized_scout import pipeline as ps_pipeline


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
    "prompt_sections": [
        {
            "section_type": "station_features",
            "job_category": "nurse",
            "order": 2,
            "content": "当ステーションの特色...",
        },
    ],
    "job_offers": [
        {
            "job_category": "nurse",
            "employment_type": "パート",
            "id": "job_001",
            "name": "訪問看護師",
        },
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


def _profile(**overrides) -> CandidateProfile:
    base = {
        "member_id": "M001",
        "gender": "女性",
        "age": "35歳",
        "area": "東京都練馬区",
        "qualifications": "正看護師",
        "experience_type": "訪問看護",
        "experience_years": "10年",
        "employment_status": "離職中",
        "desired_job": "看護師",
        "desired_employment_type": "パート",
        "self_pr": "訪問看護経験あり",
    }
    base.update(overrides)
    return CandidateProfile(**base)


@pytest.fixture
def mock_structured():
    async def fake(system_prompt, user_prompt, response_schema, **kwargs):
        parsed = {
            "opening": "候補者固有の導入文",
            "bridge": "経歴と求人の接続",
            "facility_intro": "施設紹介",
            "job_framing": "求人フレーミング",
            "closing_cta": "CTA",
        }
        meta = GenerationResult(
            text="mocked", prompt_tokens=100, output_tokens=50,
            total_tokens=150, model_name="mock",
        )
        return parsed, meta
    with patch(
        "pipeline.personalized_scout.generator.generate_structured",
        side_effect=fake,
    ) as m:
        yield m


@pytest.fixture
def mock_sheets():
    with patch("pipeline.personalized_scout.pipeline.sheets_client") as sc:
        sc.get_company_config.return_value = FAKE_CONFIG
        sc.get_company_profile.return_value = "会社プロフィール本文"
        yield sc


@pytest.fixture
def mock_validate_output():
    with patch(
        "pipeline.personalized_scout.pipeline.validate_output_text",
        return_value=[],
    ) as m:
        yield m


@pytest.fixture
def mock_filter():
    async def fake_filter(profile, company_id, job_category, validation_config):
        return None, []
    with patch(
        "pipeline.personalized_scout.pipeline.filter_candidate",
        side_effect=fake_filter,
    ) as m:
        yield m


@pytest.fixture
def mock_resolve_jc():
    def fake(profile, categories, keywords, explicit=None):
        class R:
            category = "nurse"
            method = "explicit"
            debug = "mock"
            warnings: list = []
            failure = None
        return R()
    with patch(
        "pipeline.personalized_scout.pipeline.resolve_job_category",
        side_effect=fake,
    ) as m:
        yield m


class TestGeneratePersonalizedScout:
    @pytest.mark.asyncio
    async def test_l3_happy_path(
        self,
        mock_structured,
        mock_sheets,
        mock_validate_output,
        mock_filter,
        mock_resolve_jc,
    ):
        result = await ps_pipeline.generate_personalized_scout(
            company_id="ark",
            profile=_profile(),
            level="L3",
        )
        assert result["generation_path"] == "ai_structured"
        assert result["member_id"] == "M001"
        assert result["job_category"] == "nurse"
        assert result["block_contents"]["opening"] == "候補者固有の導入文"
        # Final scout text has fixed section preserved
        assert "## 募集要項" in result["full_scout_text"]
        assert "候補者固有の導入文" in result["full_scout_text"]
        # Stats
        stats = result["personalization_stats"]
        assert stats["level"] == "L3"
        assert stats["personalized_chars"] > 0
        assert stats["fixed_chars"] > 0
        assert 0 < stats["ratio"] < 1
        # No braces leaked
        assert "{opening}" not in result["full_scout_text"]

    @pytest.mark.asyncio
    async def test_l2_happy_path(
        self,
        mock_sheets,
        mock_validate_output,
        mock_filter,
        mock_resolve_jc,
    ):
        # L2 schema only has 2 blocks
        async def fake(system_prompt, user_prompt, response_schema, **kwargs):
            return {"opening": "L2 opening", "closing_cta": "L2 CTA"}, GenerationResult(
                text="ok", model_name="mock"
            )
        with patch(
            "pipeline.personalized_scout.generator.generate_structured",
            side_effect=fake,
        ):
            result = await ps_pipeline.generate_personalized_scout(
                company_id="ark",
                profile=_profile(),
                level="L2",
            )
        assert result["generation_path"] == "ai_structured"
        assert result["block_contents"].get("opening") == "L2 opening"
        assert result["block_contents"].get("closing_cta") == "L2 CTA"
        # L2 doesn't populate these
        assert "bridge" not in result["block_contents"]

    @pytest.mark.asyncio
    async def test_template_without_placeholders_rejected(
        self,
        mock_sheets,
        mock_validate_output,
        mock_filter,
        mock_resolve_jc,
        mock_structured,
    ):
        # Replace the template with an L1-style one
        bad_config = {**FAKE_CONFIG, "templates": {
            "nurse:パート_初回": {
                "type": "パート_初回",
                "job_category": "nurse",
                "body": "古いテンプレ {personalized_text} です",
                "_row_index": 2,
            },
        }}
        mock_sheets.get_company_config.return_value = bad_config

        result = await ps_pipeline.generate_personalized_scout(
            company_id="ark",
            profile=_profile(),
            level="L3",
        )
        assert result["generation_path"] == "filtered_out"
        assert "L2/L3 テンプレ未対応" in result["filter_reason"]
        # Did NOT call Gemini
        mock_structured.assert_not_called()

    @pytest.mark.asyncio
    async def test_output_validation_failure(
        self,
        mock_structured,
        mock_sheets,
        mock_filter,
        mock_resolve_jc,
    ):
        with patch(
            "pipeline.personalized_scout.pipeline.validate_output_text",
            return_value=["他社名 X が混入しています"],
        ):
            result = await ps_pipeline.generate_personalized_scout(
                company_id="ark",
                profile=_profile(),
                level="L3",
            )
        assert result["generation_path"] == "filtered_out"
        assert "他社名" in result["filter_reason"]

    @pytest.mark.asyncio
    async def test_hard_filter_block(
        self,
        mock_structured,
        mock_sheets,
        mock_validate_output,
        mock_resolve_jc,
    ):
        async def blocker(profile, company_id, job_category, validation_config):
            return "年齢制限", ["warn1"]
        with patch(
            "pipeline.personalized_scout.pipeline.filter_candidate",
            side_effect=blocker,
        ):
            result = await ps_pipeline.generate_personalized_scout(
                company_id="ark",
                profile=_profile(),
                level="L3",
            )
        assert result["generation_path"] == "filtered_out"
        assert result["filter_reason"] == "年齢制限"
        assert result["validation_warnings"] == ["warn1"]
        mock_structured.assert_not_called()

    @pytest.mark.asyncio
    async def test_gemini_error_becomes_filtered(
        self,
        mock_sheets,
        mock_validate_output,
        mock_filter,
        mock_resolve_jc,
    ):
        async def boom(*args, **kwargs):
            raise RuntimeError("rate limit")
        with patch(
            "pipeline.personalized_scout.generator.generate_structured",
            side_effect=boom,
        ):
            result = await ps_pipeline.generate_personalized_scout(
                company_id="ark",
                profile=_profile(),
                level="L3",
            )
        assert result["generation_path"] == "filtered_out"
        assert "AI生成エラー" in result["filter_reason"]
