"""Tests for the multi-pass competitor research pipeline.

Covers:
  - Helper utilities (_extract_area_from_profile, _merge_citations).
  - Per-pass behavior with ai_generator mocked so we don't burn quota.
  - End-to-end run_research happy path.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from pipeline import competitor_research as cr
from pipeline.ai_generator import GenerationResult


def _gen_result(text: str = "ok", citations: list[dict] | None = None) -> GenerationResult:
    return GenerationResult(text=text, citations=citations or [])


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

class TestExtractAreaFromProfile:
    def test_extracts_location_from_bullet(self):
        assert cr._extract_area_from_profile("- **所在地**: 東京都港区西麻布1-14-2") == "東京都港区西麻布1-14-2"

    def test_uses_first_matching_line(self):
        profile = "- 代表: 山田\n- **所在地**: 神奈川県横浜市南区\n- 拠点: 複数"
        assert cr._extract_area_from_profile(profile) == "神奈川県横浜市南区"

    def test_returns_empty_when_no_keyword(self):
        assert cr._extract_area_from_profile("- 代表: 山田\n- 業態: 訪問看護") == ""

    def test_handles_japanese_fullwidth_colon(self):
        assert cr._extract_area_from_profile("所在地：東京都港区") == "東京都港区"

    def test_returns_empty_on_empty_input(self):
        assert cr._extract_area_from_profile("") == ""


class TestMergeCitations:
    def test_deduplicates_across_groups(self):
        groups = [
            [{"uri": "a", "title": "A"}],
            [{"uri": "a", "title": "A dup"}, {"uri": "b", "title": "B"}],
        ]
        merged = cr._merge_citations(groups)
        assert merged == [{"uri": "a", "title": "A"}, {"uri": "b", "title": "B"}]

    def test_skips_empty_uris(self):
        groups = [[{"uri": "", "title": "empty"}, {"uri": "x", "title": "X"}]]
        assert cr._merge_citations(groups) == [{"uri": "x", "title": "X"}]

    def test_handles_none_entries(self):
        assert cr._merge_citations([None, [{"uri": "x", "title": "X"}]]) == [{"uri": "x", "title": "X"}]


# ---------------------------------------------------------------------------
# Pass 1 tests
# ---------------------------------------------------------------------------

class TestPass1ListCompetitors:
    @pytest.mark.asyncio
    async def test_filters_out_self_and_job_sites(self):
        gen_text = _gen_result(
            "ソフィアメディ白金高輪、マイナビ看護師、ジョブメドレー、ガイア訪問看護 港",
            citations=[{"uri": "https://example.com", "title": "Ex"}],
        )
        structured_output = {
            "competitors": [
                {"name": "LCC訪問看護"},  # self — must be filtered
                {"name": "ソフィアメディ白金高輪"},
                {"name": "マイナビ看護師"},  # job site — must be filtered
                {"name": "ジョブメドレー"},  # job site — must be filtered
                {"name": "ガイア訪問看護 港"},
            ]
        }
        with patch.object(cr, "generate_personalized_text", AsyncMock(return_value=gen_text)), \
             patch.object(cr, "generate_structured", AsyncMock(return_value=(structured_output, _gen_result()))):
            competitors, citations, _ = await cr.pass1_list_competitors(
                target_company_display="LCC訪問看護",
                area="東京都港区",
                category_label="看護師",
                query_template="{area} 訪問看護ステーション 一覧 採用",
            )
        names = [c.name for c in competitors]
        assert names == ["ソフィアメディ白金高輪", "ガイア訪問看護 港"]
        assert citations == [{"uri": "https://example.com", "title": "Ex"}]

    @pytest.mark.asyncio
    async def test_caps_at_max_competitors(self):
        structured_output = {
            "competitors": [{"name": f"施設{i}"} for i in range(20)]
        }
        with patch.object(cr, "generate_personalized_text", AsyncMock(return_value=_gen_result())), \
             patch.object(cr, "generate_structured", AsyncMock(return_value=(structured_output, _gen_result()))):
            competitors, _, _ = await cr.pass1_list_competitors(
                target_company_display="対象会社",
                area="エリア",
                category_label="看護師",
                query_template="{area}",
            )
        assert len(competitors) == cr.MAX_COMPETITORS

    @pytest.mark.asyncio
    async def test_structuring_failure_returns_empty_list(self):
        with patch.object(cr, "generate_personalized_text", AsyncMock(return_value=_gen_result())), \
             patch.object(cr, "generate_structured", AsyncMock(side_effect=RuntimeError("boom"))):
            competitors, _, _ = await cr.pass1_list_competitors(
                target_company_display="x", area="a", category_label="c", query_template="{area}",
            )
        assert competitors == []


# ---------------------------------------------------------------------------
# Pass 2 tests
# ---------------------------------------------------------------------------

class TestPass2ResearchCompetitor:
    @pytest.mark.asyncio
    async def test_merges_three_sub_calls(self):
        import asyncio
        calls = []

        async def fake_generate(*, system_prompt, user_prompt, **kwargs):
            calls.append(user_prompt)
            if "求人条件" in user_prompt:
                return _gen_result("給与: 月30万", citations=[{"uri": "cond", "title": "C"}])
            if "評判・口コミ" in user_prompt:
                return _gen_result("良: 研修手厚い", citations=[{"uri": "rep", "title": "R"}])
            return _gen_result("新人研修1週間", citations=[{"uri": "train", "title": "T"}])

        competitor = cr.Competitor(name="テスト訪問看護")
        sem = asyncio.Semaphore(3)
        with patch.object(cr, "generate_personalized_text", side_effect=fake_generate):
            findings = await cr.pass2_research_competitor(
                competitor,
                conditions_query="{competitor} 求人",
                reputation_query="{competitor} 評判",
                training_query="{competitor} 研修",
                sem=sem,
            )
        assert "給与: 月30万" in findings.conditions_text
        assert "良: 研修手厚い" in findings.culture_text
        assert "新人研修1週間" in findings.culture_text
        uris = [c["uri"] for c in findings.citations]
        assert set(uris) == {"cond", "rep", "train"}
        # Three calls: conditions, reputation, training
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_sub_call_failure_is_isolated(self):
        import asyncio
        async def fake_generate(*, system_prompt, user_prompt, **kwargs):
            if "求人条件" in user_prompt:
                raise RuntimeError("API down")
            return _gen_result("ok")

        competitor = cr.Competitor(name="x")
        with patch.object(cr, "generate_personalized_text", side_effect=fake_generate):
            findings = await cr.pass2_research_competitor(
                competitor,
                conditions_query="{competitor}",
                reputation_query="{competitor}",
                training_query="{competitor}",
                sem=asyncio.Semaphore(3),
            )
        assert "（取得失敗）" in findings.conditions_text
        assert "ok" in findings.culture_text  # other calls still succeed


# ---------------------------------------------------------------------------
# Pass 3 tests
# ---------------------------------------------------------------------------

class TestPass3Synthesize:
    @pytest.mark.asyncio
    async def test_passes_findings_into_prompt(self):
        captured = {}

        async def fake_structured(*, system_prompt, user_prompt, response_schema, **kwargs):
            captured["user_prompt"] = user_prompt
            captured["schema"] = response_schema
            return {
                "conditions_table": "| 施設 | 給与 |\n| --- | --- |\n| A | 30万 |",
                "culture_narrative": "雰囲気まとめ",
                "hidden_strengths": "1. 発見: 教育投資が大きい",
            }, _gen_result()

        findings = [
            cr.CompetitorFindings(
                competitor=cr.Competitor(name="A", url="https://a"),
                conditions_text="月給30万",
                culture_text="研修手厚い",
            ),
        ]
        with patch.object(cr, "generate_structured", side_effect=fake_structured):
            result, _ = await cr.pass3_synthesize(
                target_company_display="対象会社",
                category_label="看護師",
                profile="会社プロフィール本文",
                findings=findings,
            )

        assert "対象会社" in captured["user_prompt"]
        assert "会社プロフィール本文" in captured["user_prompt"]
        assert "月給30万" in captured["user_prompt"]
        assert "https://a" in captured["user_prompt"]
        assert result["conditions_table"].startswith("| 施設")
        assert "教育投資" in result["hidden_strengths"]

    @pytest.mark.asyncio
    async def test_handles_empty_findings(self):
        async def fake_structured(**_):
            return {
                "conditions_table": "",
                "culture_narrative": "",
                "hidden_strengths": "",
            }, _gen_result()

        with patch.object(cr, "generate_structured", side_effect=fake_structured):
            result, _ = await cr.pass3_synthesize(
                target_company_display="x",
                category_label="y",
                profile="",
                findings=[],
            )
        assert result["conditions_table"] == ""


# ---------------------------------------------------------------------------
# Pass 4 tests
# ---------------------------------------------------------------------------

class TestPass4ExtractHooks:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_strengths(self):
        result = await cr.pass4_extract_hooks("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_llm_text(self):
        with patch.object(cr, "generate_personalized_text", AsyncMock(return_value=_gen_result("- フック1\n- フック2"))):
            result = await cr.pass4_extract_hooks("隠れた強み本文")
        assert result == "- フック1\n- フック2"


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------

class TestRunResearchEndToEnd:
    @pytest.mark.asyncio
    async def test_end_to_end_happy_path(self):
        """Mocked end-to-end: verifies shape of the ResearchResult."""
        import asyncio

        async def fake_personalized(*, system_prompt, user_prompt, **kwargs):
            # Pass 1 grounded search
            if "競合施設" in user_prompt:
                return _gen_result(
                    "ソフィアメディ白金高輪、ガイア訪問看護 港",
                    citations=[{"uri": "https://pass1.example", "title": "P1"}],
                )
            # Pass 2: conditions / reputation / training — distinguish by content
            if "求人条件を調べ" in user_prompt:
                return _gen_result("月給30万", citations=[{"uri": "https://cond.example", "title": "Cond"}])
            if "評判・口コミを調べ" in user_prompt:
                return _gen_result("OpenWork 3.5点", citations=[{"uri": "https://rep.example", "title": "Rep"}])
            if "研修・教育体制" in user_prompt:
                return _gen_result("新人研修1週間", citations=[{"uri": "https://train.example", "title": "Train"}])
            # Pass 4: hook extraction
            if "スカウト文で使えるフック" in user_prompt:
                return _gen_result("- 東京都指定の教育ステーション\n- 大病院連携")
            return _gen_result("fallback")

        async def fake_structured(*, system_prompt, user_prompt, response_schema, **kwargs):
            # Pass 1 structuring
            if "施設を抽出" in user_prompt:
                return {
                    "competitors": [
                        {"name": "ソフィアメディ白金高輪", "url": "https://sophia.example"},
                        {"name": "ガイア訪問看護 港", "url": "https://gaia.example"},
                    ]
                }, _gen_result()
            # Pass 3 synthesis
            return {
                "conditions_table": "| 施設 | 給与 |\n| --- | --- |\n| A | 30万 |",
                "culture_narrative": "雰囲気サマリ",
                "hidden_strengths": "1. 発見: 東京都指定の教育拠点であること",
            }, _gen_result()

        with patch.object(cr, "generate_personalized_text", side_effect=fake_personalized), \
             patch.object(cr, "generate_structured", side_effect=fake_structured):
            result = await cr.run_research(
                company_id="lcc-visiting-nurse",
                target_company_display="LCC訪問看護",
                category_label="看護師",
                profile="- **所在地**: 東京都港区西麻布",
                job_category="nurse",
            )

        assert isinstance(result, cr.ResearchResult)
        assert result.conditions_table.startswith("| 施設")
        assert "雰囲気サマリ" in result.culture_narrative
        assert "発見" in result.hidden_strengths
        assert result.hooks.startswith("- 東京都指定")
        names = [c["name"] for c in result.competitors_list]
        assert names == ["ソフィアメディ白金高輪", "ガイア訪問看護 港"]
        # Sources should include at least pass1 + pass2 citations (deduplicated)
        uris = {s["uri"] for s in result.sources}
        assert "https://pass1.example" in uris
        assert any("cond" in u or "rep" in u or "train" in u for u in uris)

    @pytest.mark.asyncio
    async def test_sheet_dict_has_all_required_columns(self):
        from db.sheets_client import COMPETITOR_RESEARCH_HEADERS
        result = cr.ResearchResult(
            conditions_table="t",
            culture_narrative="c",
            hidden_strengths="h",
            hooks="- x",
            sources=[{"uri": "u", "title": "T"}],
            competitors_list=[{"name": "A"}],
            model_used="pass1-2:flash / pass3:pro",
        )
        d = result.to_sheet_dict()
        # All non-key columns should be present as strings.
        for col in COMPETITOR_RESEARCH_HEADERS:
            if col in ("company", "job_category", "updated_at", "updated_by"):
                continue  # filled by the writer
            assert col in d, f"missing column: {col}"
            assert isinstance(d[col], str), f"column {col} must be str, got {type(d[col])}"
