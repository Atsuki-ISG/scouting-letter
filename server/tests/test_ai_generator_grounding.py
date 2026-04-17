"""Tests for Google Search grounding plumbing in ai_generator.

These tests cover the citation extractor and GenerationResult shape.
End-to-end behavior (tools propagated to Gemini, citations round-tripped
from a real response) is exercised through the pipeline integration tests.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline import ai_generator
from pipeline.ai_generator import (
    GenerationResult,
    _extract_citations,
)


def _mk_response(chunks=None, attributions=None):
    """Build a minimal fake Gemini response with grounding metadata."""
    meta = SimpleNamespace()
    meta.grounding_chunks = chunks or []
    meta.grounding_attributions = attributions or []
    candidate = SimpleNamespace(grounding_metadata=meta)
    return SimpleNamespace(candidates=[candidate])


class TestExtractCitations:
    def test_returns_empty_when_no_candidates(self):
        response = SimpleNamespace(candidates=[])
        assert _extract_citations(response) == []

    def test_returns_empty_when_no_grounding_metadata(self):
        candidate = SimpleNamespace(grounding_metadata=None)
        response = SimpleNamespace(candidates=[candidate])
        assert _extract_citations(response) == []

    def test_reads_grounding_chunks_web_uri_title(self):
        chunks = [
            SimpleNamespace(web=SimpleNamespace(uri="https://a.com", title="A")),
            SimpleNamespace(web=SimpleNamespace(uri="https://b.com", title="B")),
        ]
        result = _extract_citations(_mk_response(chunks=chunks))
        assert result == [
            {"uri": "https://a.com", "title": "A"},
            {"uri": "https://b.com", "title": "B"},
        ]

    def test_deduplicates_uris(self):
        chunks = [
            SimpleNamespace(web=SimpleNamespace(uri="https://a.com", title="A1")),
            SimpleNamespace(web=SimpleNamespace(uri="https://a.com", title="A2")),
        ]
        result = _extract_citations(_mk_response(chunks=chunks))
        assert result == [{"uri": "https://a.com", "title": "A1"}]

    def test_falls_back_to_grounding_attributions(self):
        attrs = [
            SimpleNamespace(web=SimpleNamespace(uri="https://c.com", title="C")),
        ]
        result = _extract_citations(_mk_response(attributions=attrs))
        assert result == [{"uri": "https://c.com", "title": "C"}]

    def test_merges_chunks_and_attributions_without_duplicates(self):
        chunks = [
            SimpleNamespace(web=SimpleNamespace(uri="https://shared.com", title="Chunk")),
        ]
        attrs = [
            SimpleNamespace(web=SimpleNamespace(uri="https://shared.com", title="Attr")),
            SimpleNamespace(web=SimpleNamespace(uri="https://only-attr.com", title="OA")),
        ]
        result = _extract_citations(_mk_response(chunks=chunks, attributions=attrs))
        # chunks run first, so chunk title wins on duplicates
        uris = [c["uri"] for c in result]
        assert uris == ["https://shared.com", "https://only-attr.com"]

    def test_skips_chunks_missing_web(self):
        chunks = [
            SimpleNamespace(web=None),
            SimpleNamespace(web=SimpleNamespace(uri="https://ok.com", title="OK")),
        ]
        result = _extract_citations(_mk_response(chunks=chunks))
        assert result == [{"uri": "https://ok.com", "title": "OK"}]

    def test_skips_empty_uri(self):
        chunks = [
            SimpleNamespace(web=SimpleNamespace(uri="", title="empty")),
        ]
        result = _extract_citations(_mk_response(chunks=chunks))
        assert result == []

    def test_is_crash_safe_on_malformed_response(self):
        # No candidates attribute at all — must not crash.
        assert _extract_citations(SimpleNamespace()) == []


class TestGenerationResultCitations:
    def test_default_citations_is_empty_list(self):
        r = GenerationResult(text="hi")
        assert r.citations == []

    def test_citations_preserved_when_provided(self):
        r = GenerationResult(text="hi", citations=[{"uri": "x", "title": "X"}])
        assert r.citations == [{"uri": "x", "title": "X"}]


class TestMockModeWithGoogleSearch:
    """MOCK_AI path must still return a GenerationResult with citations=[]."""

    @pytest.mark.asyncio
    async def test_mock_returns_empty_citations(self, monkeypatch):
        monkeypatch.setattr(ai_generator, "MOCK_AI", True)
        result = await ai_generator.generate_personalized_text(
            "system", "user", use_google_search=True,
        )
        assert result.citations == []
        assert result.text.startswith("【モック生成】")
