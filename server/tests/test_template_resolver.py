"""resolve_template_type の初回/再送判定テスト。

send_type="auto" で初回と再送が混ざったリストでも候補者ごとに
スカウト送信日の有無から正しいテンプレート種別になることを検証する。
"""
from __future__ import annotations

from models.generation import GenerateOptions
from models.profile import CandidateProfile
from pipeline.template_resolver import resolve_template_type


def _profile(**kwargs) -> CandidateProfile:
    base = {"member_id": "00000001", "desired_employment_type": "正職員"}
    base.update(kwargs)
    return CandidateProfile(**base)


class TestAutoSendType:
    def test_sent_date_present_becomes_resend(self):
        p = _profile(scout_sent_date="2026/07/01")
        opts = GenerateOptions(send_type="auto")
        assert resolve_template_type(p, opts, "nurse") == "正社員_再送"

    def test_multiple_sent_dates_becomes_resend(self):
        p = _profile(scout_sent_date="2026/06/01, 2026/07/15")
        opts = GenerateOptions(send_type="auto")
        assert resolve_template_type(p, opts, "nurse") == "正社員_再送"

    def test_no_sent_date_becomes_initial(self):
        p = _profile(scout_sent_date="")
        opts = GenerateOptions(send_type="auto")
        assert resolve_template_type(p, opts, "nurse") == "正社員_初回"

    def test_none_sent_date_becomes_initial(self):
        p = _profile(scout_sent_date=None)
        opts = GenerateOptions(send_type="auto")
        assert resolve_template_type(p, opts, "nurse") == "正社員_初回"

    def test_placeholder_values_treated_as_initial(self):
        for placeholder in ("-", "－", "ー", "なし", "未送信", "  "):
            p = _profile(scout_sent_date=placeholder)
            opts = GenerateOptions(send_type="auto")
            assert resolve_template_type(p, opts, "nurse") == "正社員_初回", placeholder

    def test_mixed_batch_resolves_per_candidate(self):
        opts = GenerateOptions(send_type="auto")
        sent = _profile(member_id="1", scout_sent_date="2026/08/01")
        fresh = _profile(member_id="2", scout_sent_date="")
        assert resolve_template_type(sent, opts, "nurse") == "正社員_再送"
        assert resolve_template_type(fresh, opts, "nurse") == "正社員_初回"

    def test_favorite_wins_over_auto_resend(self):
        p = _profile(scout_sent_date="2026/07/01", is_favorite=True)
        opts = GenerateOptions(send_type="auto")
        assert resolve_template_type(p, opts, "nurse") == "正社員_お気に入り"

    def test_auto_ignores_legacy_is_resend_flag(self):
        # send_type 指定時は is_resend フラグより優先される
        p = _profile(scout_sent_date="")
        opts = GenerateOptions(send_type="auto", is_resend=True)
        assert resolve_template_type(p, opts, "nurse") == "正社員_初回"


class TestExplicitSendType:
    def test_forced_resend_overrides_missing_date(self):
        p = _profile(scout_sent_date="")
        opts = GenerateOptions(send_type="resend")
        assert resolve_template_type(p, opts, "nurse") == "正社員_再送"

    def test_forced_initial_overrides_sent_date(self):
        p = _profile(scout_sent_date="2026/07/01")
        opts = GenerateOptions(send_type="initial")
        assert resolve_template_type(p, opts, "nurse") == "正社員_初回"


class TestLegacyClients:
    def test_legacy_is_resend_true(self):
        # send_type を送らない旧拡張は従来どおり全員再送
        p = _profile(scout_sent_date="")
        opts = GenerateOptions(is_resend=True)
        assert resolve_template_type(p, opts, "nurse") == "正社員_再送"

    def test_legacy_default_is_initial(self):
        p = _profile(scout_sent_date="2026/07/01")
        opts = GenerateOptions()
        assert resolve_template_type(p, opts, "nurse") == "正社員_初回"

    def test_employment_resolution_unchanged(self):
        p = _profile(desired_employment_type="パート", scout_sent_date="2026/07/01")
        opts = GenerateOptions(send_type="auto")
        assert resolve_template_type(p, opts, "nurse") == "パート_再送"
