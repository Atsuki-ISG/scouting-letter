"""Tests for the filter module."""

import pytest

from models.profile import CandidateProfile
from pipeline.filter import filter_candidate


@pytest.fixture
def ark_validation_config():
    return {"min_age": 20, "max_age": 59}


class TestFilterCandidate:
    """filter_candidate returns None (pass) or a reason string (exclude)."""

    def test_nurse_with_valid_qualification_passes(self, ark_validation_config):
        """Nurse with 看護師 qualification should pass all filters."""
        profile = CandidateProfile(
            member_id="001",
            qualifications="看護師",
            age="35歳",
            experience_type="病棟",
            experience_years="5年",
            employment_status="就業中",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    def test_non_nurse_qualification_is_filtered(self, ark_validation_config):
        """PT qualification should not pass nurse filter."""
        profile = CandidateProfile(
            member_id="002",
            qualifications="理学療法士",
            age="30歳",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "資格不一致" in result

    def test_already_scouted_is_filtered(self, ark_validation_config):
        """Candidate with scout_sent_date should be excluded."""
        profile = CandidateProfile(
            member_id="003",
            qualifications="看護師",
            age="40歳",
            scout_sent_date="2026-03-01",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "スカウト送信済み" in result

    def test_non_clinical_only_experience_is_filtered(self, ark_validation_config):
        """Candidate with only non-clinical experience should be excluded."""
        profile = CandidateProfile(
            member_id="004",
            qualifications="看護師",
            age="35歳",
            experience_type="保健師, 事務",
            employment_status="離職中",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "非臨床経験のみ" in result

    def test_empty_experience_and_employed_passes(self, ark_validation_config):
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
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    def test_age_below_minimum_is_filtered(self, ark_validation_config):
        """Candidate below minimum age should be excluded."""
        profile = CandidateProfile(
            member_id="006",
            qualifications="看護師",
            age="18歳",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "年齢下限" in result

    def test_age_above_maximum_is_filtered(self, ark_validation_config):
        """Candidate above maximum age should be excluded."""
        profile = CandidateProfile(
            member_id="007",
            qualifications="看護師",
            age="62歳",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is not None
        assert "年齢上限" in result

    def test_junkangoushi_passes_nurse_filter(self, ark_validation_config):
        """准看護師 should also pass the nurse filter."""
        profile = CandidateProfile(
            member_id="008",
            qualifications="准看護師",
            age="45歳",
            employment_status="就業中",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None

    def test_clinical_keyword_overrides_non_clinical(self, ark_validation_config):
        """Clinical keyword in experience should override non-clinical match."""
        profile = CandidateProfile(
            member_id="009",
            qualifications="看護師",
            age="40歳",
            experience_type="保健師, 病棟看護師",
            employment_status="離職中",
        )
        result = filter_candidate(
            profile,
            company_id="ark-visiting-nurse",
            job_category="nurse",
            validation_config=ark_validation_config,
        )
        assert result is None
