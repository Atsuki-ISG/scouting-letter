"""Tests for the pattern_matcher module."""

import pytest

from models.profile import CandidateProfile
from pipeline.pattern_matcher import (
    match_pattern,
    should_use_pattern,
    _parse_age,
    _parse_experience_years,
    _determine_age_bracket,
    _select_pattern_type,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal pattern data matching Firestore structure
# ---------------------------------------------------------------------------

@pytest.fixture
def ark_patterns():
    """ARK nurse patterns A through G with feature variations."""
    return [
        {
            "pattern_type": "A",
            "job_category": "nurse",
            "template_text": "10年以上にわたり看護の現場でご活躍されてきたご経歴を、大変心強く拝見しました。豊富な臨床経験で培われた確かな技術とアセスメント力は、{特色}当ステーションにおいて、大きな力になると考えております。",
            "feature_variations": [
                "利用者様一人ひとりと深く向き合う",
                "認知症の利用者様が多く、きめ細かなケアが求められる",
                "介護予防から在宅看取りまで幅広く対応する",
            ],
        },
        {
            "pattern_type": "B1",
            "job_category": "nurse",
            "template_text": "看護師として{N}年以上にわたるご経験に注目しました。臨床の現場で培われた確かなスキルは、{特色}当ステーションにおいて、大きな力になると考えております。",
            "feature_variations": [
                "認知症の利用者様が多く、きめ細かな観察力が求められる",
                "クリニック併設で医師と密に連携しながら訪問看護に取り組む",
                "利用者様一人ひとりの生活に深く寄り添う",
            ],
        },
        {
            "pattern_type": "B2",
            "job_category": "nurse",
            "template_text": "看護師として{N}年のご経験をお持ちとのこと、臨床の現場で培われたスキルは、{特色}当ステーションにおいて活かしていただけると考えております。",
            "feature_variations": [
                "クリニック併設で医師との連携もスムーズな",
                "認知症の利用者様を中心に、地域に根差したケアを提供する",
                "介護予防から在宅看取りまで幅広い看護を経験できる",
            ],
        },
        {
            "pattern_type": "C",
            "job_category": "nurse",
            "template_text": "看護師として臨床のご経験をお持ちとのこと、{特色}当ステーションにおいて、そのご経験を活かしていただけるのではないかと考えご連絡いたしました。",
            "feature_variations": [
                "認知症の利用者様が多く、一人ひとりに寄り添うケアを大切にする",
                "クリニック併設で医師と密に連携できる環境の",
                "介護予防から在宅看取りまで幅広く対応している",
            ],
        },
        {
            "pattern_type": "D",
            "job_category": "nurse",
            "employment_variant": "就業中",
            "template_text": "看護師として現在も臨床の現場でご活躍されている点に注目しました。{特色}当ステーションで、これまでのご経験を活かしていただけると考えております。",
            "feature_variations": [
                "認知症の利用者様が多く、看護師としてのきめ細かな対応が求められる",
                "クリニック併設で医師と連携しながら訪問看護に取り組める環境の",
                "利用者様一人ひとりの生活に寄り添うケアを大切にしている",
            ],
        },
        {
            "pattern_type": "D",
            "job_category": "nurse",
            "employment_variant": "離職中",
            "template_text": "看護師としてこれまで培われてきたご経験に注目しました。{特色}当ステーションで、そのご経験を活かしていただける場面が多いと考えております。",
            "feature_variations": [
                "認知症の利用者様が多く、看護師としてのきめ細かな対応が求められる",
                "クリニック併設で医師と連携しながら訪問看護に取り組める環境の",
                "利用者様一人ひとりの生活に寄り添うケアを大切にしている",
            ],
        },
        {
            "pattern_type": "E",
            "job_category": "nurse",
            "template_text": "看護師として臨床の現場で経験を積まれている点に注目しました。当ステーションではS-QUE訪問看護eラーニングや研修費補助など学びの環境が整っており、訪問看護という新たなフィールドでご経験を広げていただけます。",
            "feature_variations": [],
        },
        {
            "pattern_type": "F",
            "job_category": "nurse",
            "employment_variant": "就業中",
            "template_text": "看護師として現在も臨床の現場でご活躍されている点に注目しました。当ステーションではS-QUE訪問看護eラーニングや研修費補助など、看護師としてのキャリアの幅を広げられる環境が整っております。",
            "feature_variations": [],
        },
        {
            "pattern_type": "F",
            "job_category": "nurse",
            "employment_variant": "離職中",
            "template_text": "看護師の資格をお持ちとのこと、当ステーションではS-QUE訪問看護eラーニングや入社初日からの新任研修など、訪問看護を基礎から学べる環境が整っております。チーム全体でサポートし合いながら取り組める職場です。",
            "feature_variations": [],
        },
        {
            "pattern_type": "G",
            "job_category": "nurse",
            "template_text": "看護師の資格をお持ちで、これからのキャリアを検討されているとのこと、当ステーションではS-QUE訪問看護eラーニングや入社初日からの新任研修など、訪問看護を基礎から学べる環境が整っております。",
            "feature_variations": [],
        },
    ]


@pytest.fixture
def empty_modifiers():
    return []


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestParseAge:
    def test_normal(self):
        assert _parse_age("44歳") == 44

    def test_none(self):
        assert _parse_age(None) is None

    def test_empty(self):
        assert _parse_age("") is None


class TestParseExperienceYears:
    def test_10_plus(self):
        assert _parse_experience_years("10年以上") == 10

    def test_3_years(self):
        assert _parse_experience_years("3年") == 3

    def test_range(self):
        assert _parse_experience_years("6〜9年") == 6

    def test_empty(self):
        assert _parse_experience_years(None) is None
        assert _parse_experience_years("") is None
        assert _parse_experience_years("未入力") is None

    def test_less_than_1(self):
        assert _parse_experience_years("1年未満") == 0


class TestDetermineAgeBracket:
    def test_40s(self):
        assert _determine_age_bracket(44) == "40s+"

    def test_late_30s(self):
        assert _determine_age_bracket(37) == "late_30s"

    def test_young(self):
        assert _determine_age_bracket(25) == "young"

    def test_none_defaults_young(self):
        assert _determine_age_bracket(None) == "young"


# ---------------------------------------------------------------------------
# Pattern type selection tests
# ---------------------------------------------------------------------------

class TestSelectPatternType:
    def test_44_age_10_years_gives_type_A(self):
        """44歳 + 10年以上 -> type A"""
        result = _select_pattern_type("40s+", 10, "就業中")
        assert result == "A"

    def test_25_age_3_years_gives_type_B2(self):
        """25歳 + 3年 -> type B2"""
        result = _select_pattern_type("young", 3, "就業中")
        assert result == "B2"

    def test_50_age_empty_experience_working_gives_type_D(self):
        """50歳 + empty experience + 就業中 -> type D_就業中"""
        result = _select_pattern_type("40s+", None, "就業中")
        assert result == "D_就業中"

    def test_student_gives_type_G(self):
        """在学中 -> type G regardless of age/experience"""
        result = _select_pattern_type("young", None, "在学中")
        assert result == "G"

    def test_young_6_years_gives_B1(self):
        """25歳 + 6年 -> type B1"""
        result = _select_pattern_type("young", 6, "就業中")
        assert result == "B1"

    def test_older_1_year_gives_C(self):
        """45歳 + 1年 -> type C"""
        result = _select_pattern_type("40s+", 1, "離職中")
        assert result == "C"

    def test_young_1_year_gives_E(self):
        """25歳 + 1年 -> type E"""
        result = _select_pattern_type("young", 1, "就業中")
        assert result == "E"

    def test_young_no_exp_not_working_gives_F(self):
        """28歳 + no experience + 離職中 -> type F_離職中"""
        result = _select_pattern_type("young", None, "離職中")
        assert result == "F_離職中"


# ---------------------------------------------------------------------------
# Full match_pattern tests
# ---------------------------------------------------------------------------

class TestMatchPattern:
    def test_44_age_10_years_matches_A(self, ark_patterns, empty_modifiers):
        """44歳 + 10年以上 -> type A with feature variation"""
        profile = CandidateProfile(
            member_id="001",
            qualifications="看護師",
            age="44歳",
            experience_years="10年以上",
            employment_status="就業中",
        )
        pattern_type, text, debug = match_pattern(
            profile, ark_patterns, empty_modifiers, feature_rotation_index=0
        )
        assert pattern_type == "A"
        assert "10年以上" in text
        assert "大変心強く拝見" in text
        assert "利用者様一人ひとりと深く向き合う" in text

    def test_25_age_3_years_matches_B2(self, ark_patterns, empty_modifiers):
        """25歳 + 3年 -> type B2"""
        profile = CandidateProfile(
            member_id="002",
            qualifications="看護師",
            age="25歳",
            experience_years="3年",
            employment_status="就業中",
        )
        pattern_type, text, debug = match_pattern(
            profile, ark_patterns, empty_modifiers, feature_rotation_index=0
        )
        assert pattern_type == "B2"
        assert "3年のご経験" in text

    def test_50_age_empty_exp_working_matches_D(self, ark_patterns, empty_modifiers):
        """50歳 + empty experience + 就業中 -> type D (working variant)"""
        profile = CandidateProfile(
            member_id="003",
            qualifications="看護師",
            age="50歳",
            experience_years="",
            employment_status="就業中",
        )
        pattern_type, text, debug = match_pattern(
            profile, ark_patterns, empty_modifiers, feature_rotation_index=0
        )
        assert pattern_type == "D_就業中"
        assert "現在も臨床の現場でご活躍" in text

    def test_student_matches_G(self, ark_patterns, empty_modifiers):
        """20歳 + 在学中 -> type G"""
        profile = CandidateProfile(
            member_id="004",
            qualifications="看護師",
            age="20歳",
            employment_status="在学中",
        )
        pattern_type, text, debug = match_pattern(
            profile, ark_patterns, empty_modifiers, feature_rotation_index=0
        )
        assert pattern_type == "G"
        assert "これからのキャリアを検討" in text

    def test_feature_rotation_cycles(self, ark_patterns, empty_modifiers):
        """Feature rotation should cycle through variations correctly."""
        profile = CandidateProfile(
            member_id="005",
            qualifications="看護師",
            age="44歳",
            experience_years="10年以上",
            employment_status="就業中",
        )

        # Get all three variations
        texts = []
        for i in range(3):
            _, text, _ = match_pattern(
                profile, ark_patterns, empty_modifiers, feature_rotation_index=i
            )
            texts.append(text)

        # All three should be different
        assert len(set(texts)) == 3

        # Index 3 should cycle back to index 0
        _, text_cycle, _ = match_pattern(
            profile, ark_patterns, empty_modifiers, feature_rotation_index=3
        )
        assert text_cycle == texts[0]

    def test_experience_years_replaced_in_B1(self, ark_patterns, empty_modifiers):
        """B1 pattern should replace {N} with actual years."""
        profile = CandidateProfile(
            member_id="006",
            qualifications="看護師",
            age="35歳",
            experience_years="7年",
            employment_status="就業中",
        )
        pattern_type, text, _ = match_pattern(
            profile, ark_patterns, empty_modifiers, feature_rotation_index=0
        )
        assert pattern_type == "B1"
        assert "7年以上にわたるご経験" in text
        assert "{N}" not in text


class TestShouldUsePattern:
    def test_no_history_no_pr_uses_pattern(self):
        profile = CandidateProfile(
            member_id="001",
            qualifications="看護師",
        )
        assert should_use_pattern(profile) is True

    def test_with_work_history_uses_ai(self):
        profile = CandidateProfile(
            member_id="002",
            qualifications="看護師",
            work_history_summary="急性期病棟で5年勤務",
        )
        assert should_use_pattern(profile) is False

    def test_with_self_pr_uses_ai(self):
        profile = CandidateProfile(
            member_id="003",
            qualifications="看護師",
            self_pr="認知症ケアに力を入れてきました",
        )
        assert should_use_pattern(profile) is False

    def test_placeholder_values_treated_as_empty(self):
        """Values like '未入力' and 'なし' should be treated as empty."""
        profile = CandidateProfile(
            member_id="004",
            qualifications="看護師",
            work_history_summary="未入力",
            self_pr="なし",
        )
        assert should_use_pattern(profile) is True
