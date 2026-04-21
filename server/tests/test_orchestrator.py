"""Tests for the orchestrator module with mocked data client."""

import pytest
from unittest.mock import MagicMock

from models.profile import CandidateProfile
from models.generation import (
    GenerateRequest,
    GenerateOptions,
    GenerateResponse,
    BatchGenerateRequest,
    BatchGenerateResponse,
)
from pipeline.orchestrator import generate_single, generate_batch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ark_config():
    """Minimal ARK company config as returned by sheets_client.get_company_config."""
    return {
        "templates": {
            "パート_初回": {
                "type": "パート_初回",
                "body": (
                    "はじめまして。アーク訪問看護ステーションの黒木と申します。\n\n"
                    "{personalized_text}\n\n"
                    "ご興味をお持ちいただけましたら、ぜひ一度お話する機会をいただけないでしょうか。"
                ),
            },
            "パート_再送": {
                "type": "パート_再送",
                "body": (
                    "度々のご連絡大変申し訳ございません。\n\n"
                    "{personalized_text}\n\n"
                    "ご興味をお持ちいただけましたら、ぜひ一度お話する機会をいただけないでしょうか。"
                ),
            },
        },
        "patterns": [
            {
                "pattern_type": "A",
                "job_category": "nurse",
                "template_text": "10年以上にわたりご活躍されてきたご経歴を、大変心強く拝見しました。{特色}当ステーションで大きな力になると考えております。",
                "feature_variations": ["利用者様一人ひとりと深く向き合う"],
            },
            {
                "pattern_type": "B2",
                "job_category": "nurse",
                "template_text": "看護師として{N}年のご経験をお持ちとのこと、{特色}当ステーションで活かしていただけると考えております。",
                "feature_variations": ["クリニック併設で医師との連携もスムーズな"],
            },
            {
                "pattern_type": "D",
                "job_category": "nurse",
                "employment_variant": "就業中",
                "template_text": "現在も臨床の現場でご活躍されている点に注目しました。{特色}当ステーションで活かしていただけると考えております。",
                "feature_variations": ["認知症の利用者様が多く対応が求められる"],
            },
        ],
        "qualification_modifiers": [],
        "prompt_sections": [
            {
                "section_type": "role_definition",
                "order": 1,
                "content": "あなたはスカウト文生成アシスタントです。",
            },
        ],
        "job_offers": [
            {"id": "1550716", "name": "看護師パート", "label": "看護師 パート", "job_category": "nurse", "employment_type": "パート"},
            {"id": "1550715", "name": "看護師正社員", "label": "看護師 正社員", "job_category": "nurse", "employment_type": "正職員"},
        ],
        "validation_config": {"age_range": {"min": 20, "max": 59}},
        "examples": [],
    }


def _mock_data_client(config):
    """Create a mock data client that returns the given config."""
    mock = MagicMock()
    mock.get_company_config.return_value = config
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateSingle:
    @pytest.mark.asyncio
    async def test_pattern_path(self, ark_config):
        """Single generation with pattern path (no work history)."""
        profile = CandidateProfile(
            member_id="001",
            qualifications="看護師",
            age="44歳",
            experience_years="10年以上",
            employment_status="就業中",
        )
        request = GenerateRequest(
            company_id="ark-visiting-nurse",
            profile=profile,
        )

        mock_client = _mock_data_client(ark_config)
        result = await generate_single(request, mock_client)

        assert isinstance(result, GenerateResponse)
        assert result.member_id == "001"
        assert result.generation_path == "pattern"
        assert result.pattern_type == "A"
        assert result.personalized_text != ""
        assert result.full_scout_text != ""
        assert "10年以上" in result.personalized_text
        assert result.filter_reason is None

    @pytest.mark.asyncio
    async def test_filtered_out_path(self, ark_config):
        """Single generation where candidate is filtered out (already scouted).

        Uses a relative date string ("1日前") so the test stays valid as the
        clock advances — a fixed YYYY-MM-DD date silently breaks once it's
        older than the resend interval.
        """
        profile = CandidateProfile(
            member_id="002",
            qualifications="看護師",
            age="30歳",
            employment_status="就業中",
            scout_sent_date="1日前",
        )
        request = GenerateRequest(
            company_id="ark-visiting-nurse",
            profile=profile,
        )

        mock_client = _mock_data_client(ark_config)
        result = await generate_single(request, mock_client)

        assert isinstance(result, GenerateResponse)
        assert result.member_id == "002"
        assert result.generation_path == "filtered_out"
        assert result.filter_reason is not None
        assert "[送信済み]" in result.filter_reason
        assert result.personalized_text == ""
        assert result.full_scout_text == ""

    @pytest.mark.asyncio
    async def test_missing_template_uses_japanese_label(self, ark_config):
        """When the matching template is missing, the operator-facing
        filter_reason must use the Japanese category label, not the English ID."""
        # Use a config where the only template is for お気に入り (which a non-favorite
        # profile won't trigger), so paths fall through to [テンプレート未設定].
        cfg = dict(ark_config)
        cfg["templates"] = {
            "nurse:お気に入り_お気に入り": {
                "type": "お気に入り_お気に入り",
                "job_category": "nurse",
                "body": "dummy {personalized_text}",
            }
        }
        profile = CandidateProfile(
            member_id="003",
            qualifications="看護師",
            age="30歳",
            employment_status="就業中",
        )
        request = GenerateRequest(
            company_id="ark-visiting-nurse",
            profile=profile,
            options=GenerateOptions(force_seishain=True),
        )
        result = await generate_single(request, _mock_data_client(cfg))
        assert result.filter_reason is not None
        assert "[テンプレート未設定]" in result.filter_reason
        assert "看護師" in result.filter_reason
        assert "nurse" not in result.filter_reason


class TestForcePattern:
    """`force_pattern=True` は他媒体（ウェルミー等）で使う。
    候補者に自己PR・職務経歴があっても AI 生成を回さず、常に型はめで処理する。
    型が一致しない場合は filtered_out。
    """

    @pytest.mark.asyncio
    async def test_force_pattern_skips_ai_even_with_work_history(self, ark_config):
        """通常は work_history があるとAI経路。force_pattern=Trueで型はめ固定。"""
        profile = CandidateProfile(
            member_id="001",
            qualifications="看護師",
            age="44歳",
            experience_years="10年以上",
            employment_status="就業中",
            # AI 経路を誘発しうる work_history / self_pr を付けても、
            # force_pattern でパターン経路に固定されることを確認
            work_history_summary="総合病院 内科病棟 10年勤務",
            self_pr="患者様との信頼関係を大切にしてきました",
        )
        request = GenerateRequest(
            company_id="ark-visiting-nurse",
            profile=profile,
            options=GenerateOptions(force_pattern=True),
        )
        result = await generate_single(request, _mock_data_client(ark_config))
        assert result.generation_path == "pattern"
        assert result.pattern_type is not None
        assert result.personalized_text != ""

    @pytest.mark.asyncio
    async def test_force_pattern_filters_out_when_no_pattern_matches(self, ark_config):
        """force_pattern=True なのにパターンが一致しなかったら filtered_out。
        フォールバックでAIを呼ばず、明示的に理由を返す。"""
        cfg = dict(ark_config)
        cfg["patterns"] = []  # パターンを空にして絶対一致しない状況にする
        profile = CandidateProfile(
            member_id="001",
            qualifications="看護師",
            age="44歳",
            employment_status="就業中",
        )
        request = GenerateRequest(
            company_id="ark-visiting-nurse",
            profile=profile,
            options=GenerateOptions(force_pattern=True),
        )
        result = await generate_single(request, _mock_data_client(cfg))
        assert result.generation_path == "filtered_out"
        assert result.filter_reason is not None
        assert "型" in result.filter_reason or "pattern" in result.filter_reason.lower()


class TestGenerateBatch:
    @pytest.mark.asyncio
    async def test_batch_summary_counts(self, ark_config):
        """Batch generation should have correct summary counts."""
        profiles = [
            CandidateProfile(
                member_id="001",
                qualifications="看護師",
                age="44歳",
                experience_years="10年以上",
                employment_status="就業中",
            ),
            CandidateProfile(
                member_id="002",
                qualifications="看護師",
                age="25歳",
                experience_years="3年",
                employment_status="就業中",
            ),
            CandidateProfile(
                member_id="003",
                qualifications="看護師",
                age="30歳",
                employment_status="就業中",
                scout_sent_date="2026-03-10",
            ),
        ]
        request = BatchGenerateRequest(
            company_id="ark-visiting-nurse",
            profiles=profiles,
            concurrency=2,
        )

        mock_client = _mock_data_client(ark_config)
        result = await generate_batch(request, mock_client)

        assert isinstance(result, BatchGenerateResponse)
        assert result.summary["total"] == 3
        assert result.summary["pattern_matched"] == 2
        assert result.summary["filtered_out"] == 1
        assert len(result.results) == 3

        results_by_id = {r.member_id: r for r in result.results}
        assert results_by_id["001"].generation_path == "pattern"
        assert results_by_id["002"].generation_path == "pattern"
        assert results_by_id["003"].generation_path == "filtered_out"
