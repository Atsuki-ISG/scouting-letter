"""Tests for the filter module."""

from datetime import datetime, timedelta

import pytest

from models.profile import CandidateProfile
from pipeline.filter import filter_candidate, _parse_scout_dates


@pytest.fixture
def ark_validation_config():
    return {"min_age": 20, "max_age": 59}


@pytest.mark.asyncio
class TestFilterCandidate:
    """filter_candidate returns None (pass) or a reason string (exclude)."""

    async def test_nurse_with_valid_qualification_passes(self, ark_validation_config):
        """Nurse with 看護師 qualification should pass all filters."""
        profile = CandidateProfile(
            member_id="001",
            qualifications="看護師",
            age="35歳",
            experience_type="病棟",
            experience_years="5年",
            employment_status="就業中",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    async def test_non_nurse_qualification_is_filtered(self, ark_validation_config):
        """PT qualification should not pass nurse filter."""
        profile = CandidateProfile(
            member_id="002",
            qualifications="理学療法士",
            age="30歳",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "資格不一致" in result

    async def test_already_scouted_max_count_reached(self, ark_validation_config):
        """Candidate with 2+ scout sends should be excluded (default max_scout_count=2)."""
        profile = CandidateProfile(
            member_id="003",
            qualifications="看護師",
            age="40歳",
            scout_sent_date="2026-01-15, 2026-02-20",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "スカウト送信済み(2回)" in result

    async def test_already_scouted_too_recent(self, ark_validation_config):
        """Candidate scouted within resend_interval_days should be excluded."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
        profile = CandidateProfile(
            member_id="003b",
            qualifications="看護師",
            age="40歳",
            scout_sent_date=yesterday,
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "日未満" in result

    async def test_scouted_once_and_old_enough_passes(self, ark_validation_config):
        """Candidate scouted once, long ago, should pass (eligible for resend)."""
        old_date = (datetime.now() - timedelta(days=30)).strftime("%Y/%m/%d")
        profile = CandidateProfile(
            member_id="003c",
            qualifications="看護師",
            age="40歳",
            scout_sent_date=old_date,
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    async def test_non_clinical_only_experience_is_filtered(self, ark_validation_config):
        """Candidate with only non-clinical experience should be excluded."""
        profile = CandidateProfile(
            member_id="004",
            qualifications="看護師",
            age="35歳",
            experience_type="保健師, 事務",
            employment_status="離職中",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "非臨床経験のみ" in result

    async def test_empty_experience_and_employed_passes(self, ark_validation_config):
        """Candidate with no experience listed but currently employed should pass.

        Per the rules: 経験未入力で就業中の場合は臨床経験ありと推定し、対象とする
        """
        profile = CandidateProfile(
            member_id="005",
            qualifications="看護師",
            age="28歳",
            experience_type="",
            employment_status="就業中",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    async def test_age_below_minimum_is_filtered(self, ark_validation_config):
        """Candidate below minimum age should be excluded."""
        profile = CandidateProfile(
            member_id="006",
            qualifications="看護師",
            age="18歳",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "年齢下限" in result

    async def test_age_above_maximum_is_filtered(self, ark_validation_config):
        """Candidate above maximum age should be excluded."""
        profile = CandidateProfile(
            member_id="007",
            qualifications="看護師",
            age="62歳",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "年齢上限" in result

    async def test_junkangoushi_passes_nurse_filter(self, ark_validation_config):
        """准看護師 should also pass the nurse filter."""
        profile = CandidateProfile(
            member_id="008",
            qualifications="准看護師",
            age="45歳",
            employment_status="就業中",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    async def test_clinical_keyword_overrides_non_clinical(self, ark_validation_config):
        """Clinical keyword in experience should override non-clinical match."""
        profile = CandidateProfile(
            member_id="009",
            qualifications="看護師",
            age="40歳",
            experience_type="保健師, 病棟看護師",
            employment_status="離職中",
        )
        result = await filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    async def test_custom_max_scout_count(self):
        """Custom max_scout_count=3 allows 2 sends."""
        config = {
            "min_age": 20,
            "max_age": 59,
            "qualification_rules": {
                "builtin": {
                    "require_qualification": True,
                    "reject_non_clinical": True,
                    "reject_already_scouted": True,
                    "max_scout_count": 3,
                    "resend_interval_days": 7,
                },
            },
        }
        old1 = (datetime.now() - timedelta(days=30)).strftime("%Y/%m/%d")
        old2 = (datetime.now() - timedelta(days=14)).strftime("%Y/%m/%d")
        profile = CandidateProfile(
            member_id="010",
            qualifications="看護師",
            age="35歳",
            scout_sent_date=f"{old1}, {old2}",
        )
        result = await filter_candidate(profile, "ark-visiting-nurse", "nurse", config)
        assert result is None  # 2回 < max_scout_count=3 → 通過

    async def test_custom_resend_interval_days(self):
        """Custom resend_interval_days=3 allows resend after 4 days."""
        config = {
            "min_age": 20,
            "max_age": 59,
            "qualification_rules": {
                "builtin": {
                    "require_qualification": True,
                    "reject_non_clinical": True,
                    "reject_already_scouted": True,
                    "max_scout_count": 2,
                    "resend_interval_days": 3,
                },
            },
        }
        four_days_ago = (datetime.now() - timedelta(days=4)).strftime("%Y/%m/%d")
        profile = CandidateProfile(
            member_id="011",
            qualifications="看護師",
            age="35歳",
            scout_sent_date=four_days_ago,
        )
        result = await filter_candidate(profile, "ark-visiting-nurse", "nurse", config)
        assert result is None  # 4日 >= interval=3 → 通過


class TestParseScoutDates:
    """Tests for _parse_scout_dates helper."""

    def test_empty_string(self):
        assert _parse_scout_dates("") == []

    def test_single_date_slash(self):
        dates = _parse_scout_dates("2026/03/01")
        assert len(dates) == 1
        assert dates[0] == datetime(2026, 3, 1)

    def test_single_date_hyphen(self):
        dates = _parse_scout_dates("2026-03-01")
        assert len(dates) == 1

    def test_single_date_japanese(self):
        dates = _parse_scout_dates("2026年03月01日")
        assert len(dates) == 1

    def test_multiple_dates_comma_separated(self):
        dates = _parse_scout_dates("2026/01/15, 2026/03/01")
        assert len(dates) == 2
        assert dates[0] < dates[1]

    def test_multiple_dates_mixed_format(self):
        dates = _parse_scout_dates("2026/01/15, 2026-03-01")
        assert len(dates) == 2

    def test_relative_hours(self):
        dates = _parse_scout_dates("1時間前")
        assert len(dates) == 1
        diff = datetime.now() - dates[0]
        assert 0.9 < diff.total_seconds() / 3600 < 1.1

    def test_relative_days(self):
        dates = _parse_scout_dates("3日前")
        assert len(dates) == 1
        diff = datetime.now() - dates[0]
        assert 2.9 < diff.days + diff.seconds / 86400 < 3.1

    def test_relative_minutes(self):
        dates = _parse_scout_dates("30分前")
        assert len(dates) == 1
        diff = datetime.now() - dates[0]
        assert 29 < diff.total_seconds() / 60 < 31

    def test_mixed_absolute_and_relative(self):
        dates = _parse_scout_dates("2026/01/15, 1時間前")
        assert len(dates) == 2

    def test_relative_weeks(self):
        dates = _parse_scout_dates("2週間前")
        assert len(dates) == 1
        diff = datetime.now() - dates[0]
        assert 13.9 < diff.days + diff.seconds / 86400 < 14.1
