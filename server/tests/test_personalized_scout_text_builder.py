"""Unit tests for the block-based text builder used by the
personalized_scout pipeline. Pure functions → no fixtures needed.
"""
from __future__ import annotations

import pytest

from pipeline.personalized_scout.text_builder import (
    BLOCK_PLACEHOLDERS,
    L2_BLOCKS,
    build_scout_from_blocks,
    compute_personalization_stats,
    list_placeholders,
)


TEMPLATE_L3 = """{opening}

{bridge}

{facility_intro}

{job_framing}

{closing_cta}

## 募集要項
給与: 30万円
住所: 東京都練馬区
"""

TEMPLATE_L2 = """{opening}

## 会社紹介
当ステーションは訪問看護を専門としております。

{closing_cta}
"""


class TestListPlaceholders:
    def test_l3(self):
        assert list_placeholders(TEMPLATE_L3) == list(BLOCK_PLACEHOLDERS)

    def test_l2(self):
        assert list_placeholders(TEMPLATE_L2) == ["opening", "closing_cta"]

    def test_none(self):
        assert list_placeholders("旧式のテンプレ {personalized_text} だけ") == []

    def test_duplicate(self):
        # Duplicate placeholders collapse to one entry
        body = "{opening}{opening}{bridge}"
        assert list_placeholders(body) == ["opening", "bridge"]


class TestBuildScoutFromBlocks:
    def test_l3_all_filled(self):
        blocks = {
            "opening": "OP",
            "bridge": "BR",
            "facility_intro": "FI",
            "job_framing": "JF",
            "closing_cta": "CT",
        }
        out = build_scout_from_blocks(TEMPLATE_L3, blocks)
        assert "OP" in out
        assert "BR" in out
        assert "FI" in out
        assert "JF" in out
        assert "CT" in out
        # Fixed section preserved
        assert "## 募集要項" in out
        # No stray braces left
        assert "{opening}" not in out
        assert "{closing_cta}" not in out

    def test_l2_partial_blocks_leave_others_empty(self):
        blocks = {"opening": "OP_ONLY", "closing_cta": "CTA"}
        out = build_scout_from_blocks(TEMPLATE_L2, blocks)
        assert "OP_ONLY" in out
        assert "CTA" in out
        assert "{opening}" not in out
        assert "{closing_cta}" not in out

    def test_missing_block_renders_empty(self):
        # L3 template, but AI only returned 2 blocks
        blocks = {"opening": "OP", "closing_cta": "CT"}
        out = build_scout_from_blocks(TEMPLATE_L3, blocks)
        assert "OP" in out
        assert "CT" in out
        # Other placeholders are gone (empty string), not left as literal
        assert "{bridge}" not in out
        assert "{facility_intro}" not in out
        assert "{job_framing}" not in out

    def test_empty_template(self):
        assert build_scout_from_blocks("", {"opening": "X"}) == ""


class TestComputePersonalizationStats:
    def test_l3_full_ratio(self):
        blocks = {
            "opening": "あ" * 100,
            "bridge": "い" * 150,
            "facility_intro": "う" * 200,
            "job_framing": "え" * 150,
            "closing_cta": "お" * 100,
        }
        stats = compute_personalization_stats(TEMPLATE_L3, blocks, level="L3")
        assert stats["level"] == "L3"
        assert stats["personalized_chars"] == 700
        assert stats["fixed_chars"] > 0  # 募集要項 の長さ
        assert stats["total_chars"] == stats["personalized_chars"] + stats["fixed_chars"]
        assert 0 < stats["ratio"] < 1
        # per-block map has all 5 keys
        assert set(stats["per_block_chars"].keys()) == set(BLOCK_PLACEHOLDERS)
        assert stats["per_block_chars"]["opening"] == 100

    def test_l2_only_fills_two(self):
        blocks = {"opening": "A" * 100, "closing_cta": "B" * 80}
        stats = compute_personalization_stats(TEMPLATE_L2, blocks, level="L2")
        assert stats["personalized_chars"] == 180
        assert stats["per_block_chars"]["opening"] == 100
        assert stats["per_block_chars"]["bridge"] == 0
        assert stats["per_block_chars"]["facility_intro"] == 0

    def test_empty_blocks_ratio_matches_zero(self):
        blocks = {k: "" for k in BLOCK_PLACEHOLDERS}
        stats = compute_personalization_stats(TEMPLATE_L3, blocks, level="L3")
        assert stats["personalized_chars"] == 0
        assert stats["ratio"] == 0.0

    def test_ratio_matches_expected_l2_template(self):
        # TEMPLATE_L2 has ~52 fixed chars (## 会社紹介 + 説明文)
        blocks = {"opening": "X" * 100, "closing_cta": "Y" * 100}
        stats = compute_personalization_stats(TEMPLATE_L2, blocks, level="L2")
        # personalized=200, fixed should be well below that → ratio > 0.7
        assert stats["ratio"] > 0.5
        assert stats["per_block_chars"]["opening"] == 100

    def test_l2_blocks_contains_l3_subset(self):
        assert set(L2_BLOCKS) <= set(BLOCK_PLACEHOLDERS)
