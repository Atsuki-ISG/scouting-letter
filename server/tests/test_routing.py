"""Unit tests for pipeline.routing — context extraction, DSL evaluation,
and rule matching. These tests do not hit the network; routing.route()
is tested via monkeypatching sheets_client.get_routing_rules.
"""
from __future__ import annotations

import pytest

from models.profile import CandidateProfile
from pipeline import routing


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_minimal_profile(self):
        p = CandidateProfile(member_id="m1")
        ctx = routing.build_context(p)
        # Completely empty profile → no experience info at all → None
        assert ctx["nursing_years"] is None
        assert ctx["total_years"] is None
        assert ctx["has_pr"] is False
        assert ctx["blank_years"] == 0
        assert ctx["age_group"] is None
        assert ctx["special_conditions"] == []
        assert ctx["management_keywords"] is False
        assert ctx["big_corp_keywords"] is False

    def test_non_nursing_experience_returns_zero(self):
        # Has non-nursing experience → nursing_years = 0 (not None)
        p = CandidateProfile(
            member_id="m1",
            experience_type="病棟看護師",
            experience_years="5年",
        )
        ctx = routing.build_context(p)
        assert ctx["nursing_years"] == 0
        assert ctx["total_years"] == 5

    def test_visiting_nurse_veteran(self):
        p = CandidateProfile(
            member_id="m1",
            experience_type="訪問看護",
            experience_years="8年",
            work_history_summary="訪問看護8年、終末期対応が中心",
            age="42歳",
            self_pr="終末期ケアに注力",
        )
        ctx = routing.build_context(p)
        assert ctx["nursing_years"] == 8
        assert ctx["total_years"] == 8
        assert ctx["has_pr"] is True
        assert ctx["age_group"] == "40s+"

    def test_age_groups(self):
        cases = [
            ("22歳", "20s-early"),
            ("28歳", "20s-late"),
            ("32歳", "30s-early"),
            ("36歳", "30s-late"),
            ("45歳", "40s+"),
            ("55", "40s+"),
        ]
        for age_str, expected in cases:
            p = CandidateProfile(member_id="m1", age=age_str)
            assert routing.build_context(p)["age_group"] == expected

    def test_management_keywords(self):
        p = CandidateProfile(
            member_id="m1",
            experience_type="病棟看護師",
            work_history_summary="主任として5年、師長代行を1年",
        )
        assert routing.build_context(p)["management_keywords"] is True

    def test_management_keywords_does_not_match_leadership(self):
        """『リーダーシップ』は PR ワードであり、役職ではない。誤検出しないこと。"""
        p = CandidateProfile(
            member_id="m1",
            experience_type="病棟看護師",
            self_pr="私はリーダーシップを発揮できる人材です。",
            work_history_summary="病棟経験10年、一般スタッフとして勤務。",
        )
        assert routing.build_context(p)["management_keywords"] is False

    def test_management_keywords_matches_leader_alone(self):
        """『リーダー』単体（シップなし）は役職として検出する"""
        p = CandidateProfile(
            member_id="m1",
            experience_type="病棟看護師",
            work_history_summary="チームリーダーとして3年、一般勤務5年。",
        )
        assert routing.build_context(p)["management_keywords"] is True

    def test_management_keywords_matches_more_titles(self):
        """新規追加した役職キーワードがヒットすること"""
        for title in ("課長", "部長", "院長", "支部長", "支店長", "マネージャー"):
            p = CandidateProfile(
                member_id="m1",
                work_history_summary=f"{title}として勤務",
            )
            assert routing.build_context(p)["management_keywords"] is True, title

    def test_has_rich_pr_requires_20_chars(self):
        """12字PR「笑顔には自信があります」は has_rich_pr=False"""
        p_thin = CandidateProfile(
            member_id="m1",
            self_pr="笑顔には自信があります。",
        )
        ctx_thin = routing.build_context(p_thin)
        assert ctx_thin["has_pr"] is True
        assert ctx_thin["has_rich_pr"] is False

        p_rich = CandidateProfile(
            member_id="m2",
            self_pr="病棟で10年勤務し、急変対応と新人指導の経験があります。",
        )
        ctx_rich = routing.build_context(p_rich)
        assert ctx_rich["has_pr"] is True
        assert ctx_rich["has_rich_pr"] is True

    def test_big_corp_keywords(self):
        p = CandidateProfile(
            member_id="m1",
            work_history_summary="虎の門病院で10年勤務",
        )
        assert routing.build_context(p)["big_corp_keywords"] is True

    def test_special_conditions_parsing(self):
        p = CandidateProfile(
            member_id="m1",
            special_conditions="高収入, ブランク可, 資格取得支援",
        )
        conds = routing.build_context(p)["special_conditions"]
        assert "高収入" in conds
        assert "ブランク可" in conds
        assert "資格取得支援" in conds

    def test_special_conditions_aliases(self):
        p = CandidateProfile(
            member_id="m1",
            special_conditions="年収アップ、教育充実",
        )
        conds = routing.build_context(p)["special_conditions"]
        # "年収アップ" aliases to "高収入"
        assert "高収入" in conds

    def test_numeric_income_pattern_alias(self):
        """年収500万円以上可能 / 年収600万円以上可能 が 高収入 にエイリアスされる"""
        p = CandidateProfile(
            member_id="m1",
            special_conditions="ボーナス・賞与あり, 年収500万円以上可能, 年収600万円以上可能",
        )
        conds = routing.build_context(p)["special_conditions"]
        assert "高収入" in conds
        # raw token も保持されていること
        assert "年収500万円以上可能" in conds

    def test_400man_not_treated_as_high_income(self):
        """年収400万円以上可能は中央値なので 高収入 扱いしない"""
        p = CandidateProfile(
            member_id="m1",
            special_conditions="年収400万円以上可能",
        )
        conds = routing.build_context(p)["special_conditions"]
        assert "高収入" not in conds

    def test_day_shift_only_aliases(self):
        p = CandidateProfile(
            member_id="m1",
            special_conditions="日勤のみ可, 車通勤可",
        )
        conds = routing.build_context(p)["special_conditions"]
        assert "日勤のみ" in conds
        assert "車通勤可" in conds

    def test_wlb_aliases(self):
        p = CandidateProfile(
            member_id="m1",
            special_conditions="年間休日120日以上, 完全週休2日",
        )
        conds = routing.build_context(p)["special_conditions"]
        assert "WLB" in conds
        assert "土日休み" in conds

    def test_blank_years_detection(self):
        p = CandidateProfile(
            member_id="m1",
            work_history_summary="訪問看護3年、その後ブランク2年",
        )
        assert routing.build_context(p)["blank_years"] == 2

    def test_blank_years_from_employment_status_離職中(self):
        """離職中で work_history がなくても blank=1 扱い"""
        p = CandidateProfile(
            member_id="m1",
            employment_status="離職中",
        )
        assert routing.build_context(p)["blank_years"] == 1

    def test_blank_years_from_latest_end_date(self):
        """離職中＋最新職歴終了月から期間を計算"""
        result = routing._estimate_blank_years(
            work_history="勤務期間: 2024年10月〜2025年7月\n職種: 看護師",
            employment_status="離職中",
            now_year=2026, now_month=7,  # 2025年7月終了から1年経過
        )
        # 12ヶ月 → 1年
        assert result == 1

    def test_blank_years_future_date_returns_0(self):
        """最新終了月が未来なら 0（データ不整合時）"""
        result = routing._estimate_blank_years(
            work_history="勤務期間: 2024年10月〜2026年7月",
            employment_status="離職中",
            now_year=2026, now_month=4,
        )
        assert result == 0

    def test_blank_years_employed_returns_0(self):
        """就業中なら 0"""
        p = CandidateProfile(
            member_id="m1",
            employment_status="就業中",
            work_history_summary="勤務期間: 2020年4月〜現在",
        )
        assert routing.build_context(p)["blank_years"] == 0

    def test_blank_years_ブランク_keyword_takes_priority(self):
        """explicit 『ブランクX年』 が employment_status より優先"""
        result = routing._estimate_blank_years(
            work_history="病棟看護5年、ブランク3年、復職後訪看2年",
            employment_status="就業中",
        )
        assert result == 3

    def test_placeholder_fields_treated_as_none(self):
        p = CandidateProfile(
            member_id="m1",
            experience_years="未入力",
            self_pr="なし",
            special_conditions="-",
        )
        ctx = routing.build_context(p)
        assert ctx["total_years"] is None
        assert ctx["has_pr"] is False
        assert ctx["special_conditions"] == []


# ---------------------------------------------------------------------------
# DSL evaluator
# ---------------------------------------------------------------------------


class TestEvaluateCondition:
    def test_simple_equality(self):
        ctx = {"attribute": "veteran"}
        assert routing.evaluate_condition('attribute == "veteran"', ctx)
        assert not routing.evaluate_condition('attribute == "junior"', ctx)

    def test_comparison_with_none_returns_false(self):
        ctx = {"nursing_years": None}
        # None-aware: comparison with None should not match, not raise
        assert not routing.evaluate_condition("nursing_years >= 3", ctx)

    def test_and_or_uppercase(self):
        ctx = {"has_pr": True, "nursing_years": 5}
        assert routing.evaluate_condition(
            "has_pr == true AND nursing_years >= 3", ctx
        )
        assert routing.evaluate_condition(
            "has_pr == false OR nursing_years >= 3", ctx
        )
        assert not routing.evaluate_condition(
            "has_pr == false AND nursing_years >= 3", ctx
        )

    def test_string_in_list(self):
        ctx = {"special_conditions": ["高収入", "教育体制"]}
        assert routing.evaluate_condition('"高収入" in special_conditions', ctx)
        assert not routing.evaluate_condition('"時短" in special_conditions', ctx)

    def test_value_in_tuple(self):
        ctx = {"age_group": "30s-early"}
        assert routing.evaluate_condition(
            'age_group in ("20s-early", "20s-late", "30s-early")', ctx
        )
        assert not routing.evaluate_condition(
            'age_group in ("40s+",)', ctx
        )

    def test_null_literal(self):
        ctx = {"nursing_years": None}
        assert routing.evaluate_condition("nursing_years == null", ctx)
        ctx = {"nursing_years": 3}
        assert not routing.evaluate_condition("nursing_years == null", ctx)

    def test_true_literal(self):
        ctx = {"has_pr": True}
        assert routing.evaluate_condition("has_pr == true", ctx)

    def test_complex_combined(self):
        ctx = {
            "nursing_years": None,
            "total_years": 5,
            "blank_years": 0,
            "has_pr": True,
        }
        # "訪問看護未経験 but 病院経験あり" pattern
        assert routing.evaluate_condition(
            "nursing_years == null AND total_years >= 1", ctx
        )
        # ブランクなし
        assert not routing.evaluate_condition("blank_years >= 1", ctx)

    def test_syntax_error_returns_false(self):
        assert not routing.evaluate_condition("nursing_years >=", {})
        assert not routing.evaluate_condition("(((", {})

    def test_empty_condition_returns_false(self):
        assert not routing.evaluate_condition("", {})
        assert not routing.evaluate_condition("   ", {})

    def test_unknown_variable_returns_none(self):
        # Unknown names resolve to None, so comparisons become False
        assert not routing.evaluate_condition("unknown_var >= 3", {})

    def test_function_call_not_allowed(self):
        # Functions would open arbitrary code execution; ensure they are
        # rejected (safe_eval raises ValueError → evaluator returns False).
        assert not routing.evaluate_condition("len([1,2,3]) >= 3", {})


# ---------------------------------------------------------------------------
# route() — rule matching
# ---------------------------------------------------------------------------


class TestRoute:
    @staticmethod
    def _stub_rules(monkeypatch, rules):
        monkeypatch.setattr(
            routing.sheets_client, "get_routing_rules", lambda: rules
        )

    def test_default_when_no_rules(self, monkeypatch):
        self._stub_rules(monkeypatch, [])
        result = routing.route(CandidateProfile(member_id="m1"))
        assert result["skeleton"] == "alpha"
        assert result["tone"] == "casual"
        assert result["attribute"] == "general"
        assert result["matched_rule"] == "default_fallback"

    def test_first_match_wins(self, monkeypatch):
        self._stub_rules(monkeypatch, [
            {
                "priority": 1, "name": "no_info",
                "condition": "nursing_years == null AND total_years == null",
                "skeleton": "alpha", "tone": "casual", "attribute": "general",
            },
            {
                "priority": 2, "name": "blank",
                "condition": "blank_years >= 1",
                "skeleton": "delta", "tone": "letter", "attribute": "blank_career",
            },
        ])
        p = CandidateProfile(member_id="m1")  # no nursing/total experience
        result = routing.route(p)
        assert result["matched_rule"] == "no_info"
        assert result["skeleton"] == "alpha"

    def test_veteran_routing(self, monkeypatch):
        self._stub_rules(monkeypatch, [
            {
                "priority": 5, "name": "high_income",
                "condition": '"高収入" in special_conditions',
                "skeleton": "alpha", "tone": "compact", "attribute": "nursing_veteran",
            },
            {
                "priority": 7, "name": "visiting_nurse_veteran",
                "condition": "nursing_years >= 3",
                "skeleton": "alpha", "tone": "casual", "attribute": "nursing_veteran",
            },
        ])
        # ベテラン with 高収入 → priority 5 wins
        p1 = CandidateProfile(
            member_id="m1",
            experience_type="訪問看護",
            experience_years="8年",
            special_conditions="高収入",
        )
        r1 = routing.route(p1)
        assert r1["matched_rule"] == "high_income"
        assert r1["tone"] == "compact"

        # ベテラン without 高収入 → priority 7 wins
        p2 = CandidateProfile(
            member_id="m2",
            experience_type="訪問看護",
            experience_years="5年",
        )
        r2 = routing.route(p2)
        assert r2["matched_rule"] == "visiting_nurse_veteran"
        assert r2["tone"] == "casual"

    def test_default_fallback_when_no_rule_matches(self, monkeypatch):
        self._stub_rules(monkeypatch, [
            {
                "priority": 1, "name": "never_matches",
                "condition": "nursing_years >= 100",
                "skeleton": "delta", "tone": "letter", "attribute": "blank_career",
            },
        ])
        p = CandidateProfile(member_id="m1", experience_years="3年")
        result = routing.route(p)
        assert result["matched_rule"] == "default_fallback"
        assert result["skeleton"] == "alpha"

    def test_failing_condition_does_not_abort_rule_scan(self, monkeypatch):
        # If one rule's condition is malformed, subsequent rules should
        # still be evaluated.
        self._stub_rules(monkeypatch, [
            {
                "priority": 1, "name": "broken",
                "condition": "(((",
                "skeleton": "delta", "tone": "letter", "attribute": "blank_career",
            },
            {
                "priority": 2, "name": "always_matches",
                "condition": "true",
                "skeleton": "alpha", "tone": "casual", "attribute": "general",
            },
        ])
        result = routing.route(CandidateProfile(member_id="m1"))
        assert result["matched_rule"] == "always_matches"

    def test_sheets_load_error_returns_default(self, monkeypatch):
        def boom():
            raise RuntimeError("sheets down")
        monkeypatch.setattr(
            routing.sheets_client, "get_routing_rules", boom
        )
        result = routing.route(CandidateProfile(member_id="m1"))
        assert result == {**routing.DEFAULT_ROUTING}


# ---------------------------------------------------------------------------
# resolve_header() — header pool matching
# ---------------------------------------------------------------------------


class TestResolveHeader:
    @staticmethod
    def _stub_pool(monkeypatch, pool):
        monkeypatch.setattr(
            routing.sheets_client,
            "get_header_pool",
            lambda company_id: pool,
        )

    def test_returns_none_when_pool_empty(self, monkeypatch):
        self._stub_pool(monkeypatch, [])
        result = routing.resolve_header(
            CandidateProfile(member_id="m1"), "ichigo-visiting-nurse"
        )
        assert result is None

    def test_returns_none_on_sheets_error(self, monkeypatch):
        def boom(_):
            raise RuntimeError("sheets down")
        monkeypatch.setattr(routing.sheets_client, "get_header_pool", boom)
        result = routing.resolve_header(
            CandidateProfile(member_id="m1"), "ichigo-visiting-nurse"
        )
        assert result is None

    def test_matches_by_trigger_condition(self, monkeypatch):
        self._stub_pool(monkeypatch, [
            {
                "pool_id": "P01", "trigger_condition": "高収入／年収アップ",
                "skeleton": "both", "tone": "",
                "header_text": "🌸【年収500-600万可】月給35-45万",
                "priority": 1,
            },
            {
                "pool_id": "P02", "trigger_condition": "default",
                "skeleton": "both", "tone": "",
                "header_text": "🌸【新規オープン】富士見台サテライト",
                "priority": 2,
            },
        ])
        # Candidate with 高収入 in special_conditions
        p = CandidateProfile(member_id="m1", special_conditions="高収入")
        result = routing.resolve_header(p, "ichigo")
        assert result == "🌸【年収500-600万可】月給35-45万"

    def test_fallback_to_default_when_no_match(self, monkeypatch):
        self._stub_pool(monkeypatch, [
            {
                "pool_id": "P01", "trigger_condition": "高収入",
                "skeleton": "both", "tone": "",
                "header_text": "high income header",
                "priority": 1,
            },
            {
                "pool_id": "P02", "trigger_condition": "default",
                "skeleton": "both", "tone": "",
                "header_text": "default header",
                "priority": 10,
            },
        ])
        # Candidate without matching こだわり
        p = CandidateProfile(member_id="m1", special_conditions="残業少")
        result = routing.resolve_header(p, "ichigo")
        assert result == "default header"

    def test_returns_none_when_no_match_and_no_default(self, monkeypatch):
        self._stub_pool(monkeypatch, [
            {
                "pool_id": "P01", "trigger_condition": "高収入",
                "skeleton": "both", "tone": "",
                "header_text": "high income",
                "priority": 1,
            },
        ])
        p = CandidateProfile(member_id="m1", special_conditions="残業少")
        result = routing.resolve_header(p, "ichigo")
        assert result is None

    def test_skeleton_filter_excludes_mismatched(self, monkeypatch):
        self._stub_pool(monkeypatch, [
            {
                "pool_id": "P01", "trigger_condition": "高収入",
                "skeleton": "delta", "tone": "",
                "header_text": "delta-only header",
                "priority": 1,
            },
            {
                "pool_id": "P02", "trigger_condition": "default",
                "skeleton": "both", "tone": "",
                "header_text": "default",
                "priority": 10,
            },
        ])
        p = CandidateProfile(member_id="m1", special_conditions="高収入")
        # Request alpha skeleton — delta-only pool should NOT match
        result = routing.resolve_header(p, "ichigo", skeleton="alpha")
        assert result == "default"  # falls back to default

    def test_tone_filter_excludes_mismatched(self, monkeypatch):
        self._stub_pool(monkeypatch, [
            {
                "pool_id": "P01", "trigger_condition": "高収入",
                "skeleton": "both", "tone": "compact,business",
                "header_text": "compact header",
                "priority": 1,
            },
            {
                "pool_id": "P02", "trigger_condition": "高収入",
                "skeleton": "both", "tone": "casual,letter",
                "header_text": "casual header",
                "priority": 2,
            },
        ])
        p = CandidateProfile(member_id="m1", special_conditions="高収入")
        # casual tone → P01 is excluded, P02 matches
        result = routing.resolve_header(p, "ichigo", tone="casual")
        assert result == "casual header"

    def test_priority_order(self, monkeypatch):
        self._stub_pool(monkeypatch, [
            {
                "pool_id": "P02", "trigger_condition": "高収入",
                "skeleton": "both", "tone": "",
                "header_text": "secondary",
                "priority": 5,
            },
            {
                "pool_id": "P01", "trigger_condition": "高収入",
                "skeleton": "both", "tone": "",
                "header_text": "primary",
                "priority": 1,
            },
        ])
        p = CandidateProfile(member_id="m1", special_conditions="高収入")
        result = routing.resolve_header(p, "ichigo")
        # Lowest priority wins
        assert result == "primary"

    def test_multi_token_trigger_condition(self, monkeypatch):
        self._stub_pool(monkeypatch, [
            {
                "pool_id": "P03", "trigger_condition": "ブランク可／未経験可／教育体制",
                "skeleton": "both", "tone": "",
                "header_text": "for inexperienced",
                "priority": 1,
            },
        ])
        # Candidate has only one of the trigger tokens
        p = CandidateProfile(member_id="m1", special_conditions="未経験可")
        result = routing.resolve_header(p, "ichigo")
        assert result == "for inexperienced"
