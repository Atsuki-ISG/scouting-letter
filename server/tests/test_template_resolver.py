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


# ---------------------------------------------------------------------------
# 年代別テンプレート（種別名末尾の年齢帯）
# ---------------------------------------------------------------------------

from pipeline.template_resolver import find_age_variant, parse_age_band


def _tpl(ttype: str, jc: str = "nurse") -> dict:
    return {"type": ttype, "job_category": jc, "body": ttype}


def _templates(*tpls: dict) -> dict:
    return {
        (f"{t['job_category']}:{t['type']}" if t["job_category"] else t["type"]): t
        for t in tpls
    }


class TestParseAgeBand:
    def test_open_lower(self):
        assert parse_age_band("〜39歳") == (None, 39)

    def test_open_upper(self):
        assert parse_age_band("40歳〜") == (40, None)

    def test_closed_range(self):
        assert parse_age_band("25-29歳") == (25, 29)

    def test_not_a_band(self):
        assert parse_age_band("L3") is None
        assert parse_age_band("〜") is None


class TestFindAgeVariant:
    LCC = _templates(
        _tpl("正社員_初回"),
        _tpl("正社員_初回_〜39歳"),
        _tpl("正社員_初回_40歳〜"),
        _tpl("正社員_再送"),
    )

    def test_boundary_39_goes_young(self):
        v = find_age_variant(self.LCC, "nurse", "正社員_初回", "39歳")
        assert v["type"] == "正社員_初回_〜39歳"

    def test_boundary_40_goes_older(self):
        v = find_age_variant(self.LCC, "nurse", "正社員_初回", "40歳")
        assert v["type"] == "正社員_初回_40歳〜"

    def test_over_60_goes_older(self):
        v = find_age_variant(self.LCC, "nurse", "正社員_初回", "63歳")
        assert v["type"] == "正社員_初回_40歳〜"

    def test_unknown_age_falls_back(self):
        assert find_age_variant(self.LCC, "nurse", "正社員_初回", None) is None
        assert find_age_variant(self.LCC, "nurse", "正社員_初回", "") is None

    def test_resend_without_bands_is_untouched(self):
        assert find_age_variant(self.LCC, "nurse", "正社員_再送", "45歳") is None

    def test_other_job_category_ignored(self):
        assert find_age_variant(self.LCC, "rehab_pt", "正社員_初回", "45歳") is None

    def test_gap_between_bands_falls_back(self):
        t = _templates(_tpl("正社員_初回_25-29歳"), _tpl("正社員_初回_40歳〜"))
        assert find_age_variant(t, "nurse", "正社員_初回", "33歳") is None

    def test_job_category_row_beats_generic_row(self):
        t = _templates(
            _tpl("正社員_初回_40歳〜", jc=""),
            _tpl("正社員_初回_40歳〜", jc="nurse"),
        )
        v = find_age_variant(t, "nurse", "正社員_初回", "50歳")
        assert v["job_category"] == "nurse"
