"""Tests for the thinking_budget override in _build_generation_config.

The per-call override lets the multi-pass competitor research pipeline
use a small budget for cheap passes (listup, extraction) and a large
budget only for the expensive synthesis pass.

thinking トークンは max_output_tokens を消費するため、thinking 対応
モデルでは本文枠が保証されるよう思考予算が上乗せされることも検証する。
"""
from __future__ import annotations

import pytest

from pipeline import ai_generator


@pytest.fixture(autouse=True)
def _set_env_default(monkeypatch):
    # Ensure tests are deterministic regardless of the runtime env.
    monkeypatch.setattr(ai_generator, "GEMINI_THINKING_BUDGET", 8192)


class TestBuildGenerationConfigThinkingBudget:
    def test_env_default_applied_when_not_overridden(self):
        cfg = ai_generator._build_generation_config(
            0.3, 2048, "gemini-3.1-pro-preview", for_vertex=True,
        )
        assert cfg["thinking_config"] == {"thinking_budget": 8192}
        # 思考予算の分だけ本文枠が上乗せされる
        assert cfg["max_output_tokens"] == 2048 + 8192

    def test_override_to_zero_disables_thinking(self):
        cfg = ai_generator._build_generation_config(
            0.3, 2048, "gemini-3.1-pro-preview", for_vertex=True,
            thinking_budget=0,
        )
        assert "thinking_config" not in cfg
        assert cfg["max_output_tokens"] == 2048

    def test_override_sets_custom_budget(self):
        cfg = ai_generator._build_generation_config(
            0.3, 2048, "gemini-3.1-pro-preview", for_vertex=True,
            thinking_budget=1024,
        )
        assert cfg["thinking_config"] == {"thinking_budget": 1024}
        assert cfg["max_output_tokens"] == 2048 + 1024

    def test_thinking_skipped_for_unsupported_model(self):
        cfg = ai_generator._build_generation_config(
            0.3, 2048, "gemini-1.5-pro", for_vertex=True,
            thinking_budget=4096,
        )
        assert "thinking_config" not in cfg
        assert cfg["max_output_tokens"] == 2048

    def test_thinking_skipped_for_genai_sdk_path(self):
        # google-generativeai SDK rejects thinking_config in GenerationConfig.
        # ただし thinking 自体は既定で走るため、本文枠の上乗せは行う。
        cfg = ai_generator._build_generation_config(
            0.3, 2048, "gemini-3.1-pro-preview", for_vertex=False,
            thinking_budget=4096,
        )
        assert "thinking_config" not in cfg
        assert cfg["max_output_tokens"] == 2048 + 4096

    def test_none_falls_through_to_env_default(self):
        cfg = ai_generator._build_generation_config(
            0.3, 2048, "gemini-3-flash-preview", for_vertex=True,
            thinking_budget=None,
        )
        assert cfg["thinking_config"] == {"thinking_budget": 8192}
        assert cfg["max_output_tokens"] == 2048 + 8192
