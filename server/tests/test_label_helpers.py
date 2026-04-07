"""Tests for category label helpers."""
from __future__ import annotations

import pytest

from db.sheets_client import label_for_category, label_for_categories


def test_label_for_category_known_ids():
    assert label_for_category("nurse") == "看護師"
    assert label_for_category("rehab_pt") == "理学療法士"
    assert label_for_category("rehab_st") == "言語聴覚士"
    assert label_for_category("rehab_ot") == "作業療法士"
    assert label_for_category("medical_office") == "医療事務"
    assert label_for_category("dietitian") == "管理栄養士"
    assert label_for_category("counselor") == "相談支援専門員"


def test_label_for_category_sales():
    """sales カテゴリは大和ハウスライフサポートで使用。"""
    assert label_for_category("sales") == "入居相談員"


def test_label_for_category_unknown_returns_input():
    assert label_for_category("unknown_category") == "unknown_category"
    assert label_for_category("") == ""


def test_label_for_categories_list():
    assert label_for_categories(["nurse", "rehab_pt"]) == ["看護師", "理学療法士"]


def test_label_for_categories_empty_list():
    assert label_for_categories([]) == []


def test_label_for_categories_mixed_known_unknown():
    assert label_for_categories(["nurse", "xxx"]) == ["看護師", "xxx"]
