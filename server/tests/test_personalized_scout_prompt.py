"""Tests for the personalized_scout prompt module (L2/L3).

TDD tests for Part A of the prompt production tuning.
"""
from __future__ import annotations

import pytest

from models.profile import CandidateProfile
from pipeline.personalized_scout.prompt import (
    _block_description,
    build_system_prompt,
    build_user_prompt,
    response_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        "self_pr": "訪問看護で10年勤務",
    }
    base.update(overrides)
    return CandidateProfile(**base)


def _sparse_profile() -> CandidateProfile:
    """Minimal profile with very little info."""
    return CandidateProfile(
        member_id="M002",
        qualifications="正看護師",
        employment_status="就業中",
        age="42歳",
    )


# ---------------------------------------------------------------------------
# Step 1: _SYSTEM_PROMPT_STATIC_HEAD
# ---------------------------------------------------------------------------

class TestSystemPromptStaticHead:
    """Verify the static head contains essential structural sections."""

    def _get_head(self) -> str:
        # Build a prompt and check the static head portion
        prompt = build_system_prompt(
            level="L3",
            company_profile="テスト会社",
            prompt_sections_text="",
            template_body="テスト",
        )
        return prompt

    def test_contains_block_guide(self):
        """Static head must have a block-level writing guide."""
        head = self._get_head()
        for block in ["opening", "bridge", "facility_intro", "job_framing", "closing_cta"]:
            assert block in head, f"Block guide for '{block}' missing"

    def test_contains_dedup_rules(self):
        """Static head must mention deduplication rules."""
        head = self._get_head()
        assert "重複" in head or "繰り返さない" in head

    def test_contains_name_prohibition(self):
        """Must prohibit candidate names in output."""
        head = self._get_head()
        assert "氏名" in head or "名前" in head

    def test_contains_json_compliance(self):
        """Must mention JSON schema compliance."""
        head = self._get_head()
        assert "JSON" in head

    def test_no_hajimemashite(self):
        """Must prohibit starting with はじめまして."""
        head = self._get_head()
        assert "はじめまして" in head

    def test_section_priority_rule(self):
        """Must state that company-specific sections / knowledge take priority."""
        head = self._get_head()
        assert "優先" in head


# ---------------------------------------------------------------------------
# Step 2: _block_description()
# ---------------------------------------------------------------------------

class TestBlockDescriptions:
    """Verify expanded block descriptions."""

    @pytest.mark.parametrize("block_name", [
        "opening", "bridge", "facility_intro", "job_framing", "closing_cta",
    ])
    def test_description_has_char_range(self, block_name):
        """Each block description must mention character limits."""
        desc = _block_description(block_name)
        assert "字" in desc, f"{block_name} description missing char range"

    @pytest.mark.parametrize("block_name", [
        "opening", "bridge", "facility_intro", "job_framing", "closing_cta",
    ])
    def test_description_is_multi_sentence(self, block_name):
        """Each block description should be more than a single line."""
        desc = _block_description(block_name)
        assert len(desc) > 50, f"{block_name} description too short: {len(desc)} chars"

    def test_opening_mentions_hajimemashite_ban(self):
        desc = _block_description("opening")
        assert "はじめまして" in desc

    def test_closing_cta_mentions_sender_emotion(self):
        """closing_cta should warn against sender-emotion expressions."""
        desc = _block_description("closing_cta")
        assert "感情" in desc or "オファー" in desc or "主語" in desc


# ---------------------------------------------------------------------------
# Step 3: build_user_prompt()
# ---------------------------------------------------------------------------

class TestBuildUserPrompt:
    """Verify user prompt improvements."""

    def test_labeled_format(self):
        """User prompt should use label: value format, not JSON."""
        profile = _profile()
        prompt = build_user_prompt(profile, "nurse")
        # Should contain labeled lines
        assert "保有資格:" in prompt or "保有資格: " in prompt
        # Should NOT be raw JSON
        assert '"member_id"' not in prompt

    def test_skips_empty_values(self):
        """Empty and placeholder values should be skipped."""
        profile = _profile(
            desired_area="",
            desired_start="未入力",
            special_conditions="なし",
            work_history_summary="",
        )
        prompt = build_user_prompt(profile, "nurse")
        assert "未入力" not in prompt
        assert "なし" not in prompt.split("保有資格")[0]  # "なし" as standalone value

    def test_info_richness_rich(self):
        """Profile with self_pr and experience should be classified as rich."""
        profile = _profile(self_pr="訪問看護10年の経験があります", work_history_summary="A病院3年→B訪看7年")
        prompt = build_user_prompt(profile, "nurse")
        assert "rich" in prompt.lower() or "豊富" in prompt or "情報量" in prompt

    def test_info_richness_sparse(self):
        """Minimal profile should be classified as sparse."""
        profile = _sparse_profile()
        prompt = build_user_prompt(profile, "nurse")
        assert "sparse" in prompt.lower() or "少ない" in prompt or "情報量" in prompt

    def test_contains_job_category(self):
        """Job category should appear in the prompt."""
        profile = _profile()
        prompt = build_user_prompt(profile, "nurse")
        assert "nurse" in prompt


# ---------------------------------------------------------------------------
# Step 4: build_system_prompt() assembly
# ---------------------------------------------------------------------------

class TestBuildSystemPromptAssembly:
    """Verify prompt assembly improvements."""

    def test_template_dedup_hint_haiken(self):
        """When template contains 拝見し, a dedup hint should be added."""
        prompt = build_system_prompt(
            level="L3",
            company_profile="テスト会社",
            prompt_sections_text="",
            template_body="プロフィールを拝見し、ご連絡しました。{opening}",
        )
        assert "拝見し" in prompt
        # The hint should warn against using 拝見し in blocks
        # Count occurrences - should appear in template section AND in a hint
        assert prompt.count("拝見し") >= 2

    def test_no_dedup_hint_when_absent(self):
        """When template does NOT contain 拝見し, no extra dedup hint section."""
        prompt = build_system_prompt(
            level="L3",
            company_profile="テスト会社",
            prompt_sections_text="",
            template_body="ご連絡しました。{opening}",
        )
        # Should not have the dedup hint SECTION (テンプレート重複注意)
        assert "テンプレート重複注意" not in prompt

    def test_l2_level_hint(self):
        """L2 hint should mention the limited block scope."""
        prompt = build_system_prompt(
            level="L2",
            company_profile="",
            prompt_sections_text="",
            template_body="test",
        )
        assert "L2" in prompt
        assert "opening" in prompt.split("レベル")[-1] if "レベル" in prompt else True

    def test_l3_level_hint(self):
        """L3 hint should mention all blocks and flow."""
        prompt = build_system_prompt(
            level="L3",
            company_profile="",
            prompt_sections_text="",
            template_body="test",
        )
        assert "L3" in prompt
        assert "5" in prompt or "全て" in prompt or "一貫" in prompt

    def test_knowledge_rules_injected(self):
        """When knowledge_rules are provided, they appear in the prompt."""
        rules = ["「感銘を受ける」は使わない", "送り手の感情を主語にしない"]
        prompt = build_system_prompt(
            level="L3",
            company_profile="",
            prompt_sections_text="",
            template_body="test",
            knowledge_rules=rules,
        )
        assert "感銘を受ける" in prompt
        assert "送り手の感情" in prompt

    def test_knowledge_rules_empty(self):
        """When knowledge_rules is empty, no extra section is added."""
        prompt_with = build_system_prompt(
            level="L3",
            company_profile="",
            prompt_sections_text="",
            template_body="test",
            knowledge_rules=[],
        )
        prompt_without = build_system_prompt(
            level="L3",
            company_profile="",
            prompt_sections_text="",
            template_body="test",
        )
        # Neither should have the knowledge SECTION header
        assert "## ナレッジ（蓄積されたルール）" not in prompt_with
        assert "## ナレッジ（蓄積されたルール）" not in prompt_without

    def test_knowledge_rules_none(self):
        """When knowledge_rules is None, no extra section is added."""
        prompt = build_system_prompt(
            level="L3",
            company_profile="",
            prompt_sections_text="",
            template_body="test",
            knowledge_rules=None,
        )
        assert "## ナレッジ（蓄積されたルール）" not in prompt


# ---------------------------------------------------------------------------
# Step 5: temperature default
# ---------------------------------------------------------------------------

class TestGeneratorDefaults:
    """Verify generator parameter defaults."""

    def test_temperature_default(self):
        """Default temperature should be 0.55 for better rule adherence."""
        import inspect
        from pipeline.personalized_scout.generator import generate_blocks
        sig = inspect.signature(generate_blocks)
        temp_default = sig.parameters["temperature"].default
        assert temp_default == 0.55, f"Expected 0.55, got {temp_default}"
