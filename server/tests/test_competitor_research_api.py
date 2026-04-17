"""Tests for the competitor research API endpoint.

Verifies the endpoint wiring (not the pipeline internals — those live in
`test_competitor_research_pipeline.py`). The pipeline is mocked so these
tests don't need API keys or network access.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from auth.api_key import verify_api_key
from pipeline.competitor_research import ResearchResult


def _fake_operator():
    return {"operator_id": "t", "name": "t", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


@pytest.fixture
def mock_sheets_client():
    with patch("api.routes_admin.sheets_client") as sc:
        sc.get_company_profile.return_value = "- **所在地**: 北海道札幌市"
        sc.get_company_display_name.return_value = "ARK訪問看護"
        sc.get_company_config.return_value = {
            "job_categories": [{"id": "nurse", "display_name": "看護師"}],
        }
        sc.get_competitor_research.return_value = None  # no cache by default
        sc.reload = MagicMock()
        yield sc


@pytest.fixture
def mock_sheets_writer():
    with patch("api.routes_admin.sheets_writer") as sw:
        sw.upsert_competitor_research = MagicMock(return_value={"action": "insert", "row_index": 2})
        yield sw


def _result() -> ResearchResult:
    return ResearchResult(
        conditions_table="| 施設 | 給与 |\n| --- | --- |\n| A訪看 | 月給30万 |",
        culture_narrative="研修が手厚いのが特徴。",
        hidden_strengths="1. 発見: 認知症ケアの経験を活かせる環境\n2. 発見: 大病院内サテライト",
        hooks=(
            "- 東京都指定の訪問看護教育ステーションで行政お墨付きの教育体制\n"
            "- 大病院内サテライトで医師と密に連携できる安心感を訴求\n"
            "- インセンティブ依存ではない高い基本給"
        ),
        sources=[{"uri": "https://a.example", "title": "A"}],
        competitors_list=[{"name": "A訪看", "url": "https://a.example", "notes": "教育充実"}],
        model_used="pass1-2:gemini-3-flash-preview / pass3:gemini-3.1-pro-preview",
    )


def _patch_pipeline(result: ResearchResult):
    """Patch run_research so the endpoint doesn't hit Gemini."""
    async def fake(**kwargs):
        return result
    return patch("api.routes_admin.run_research", side_effect=fake)


# ---------------------------------------------------------------------------

class TestEndpointHappyPath:
    def test_returns_ok_with_analysis_and_hooks(self, client, mock_sheets_client, mock_sheets_writer):
        with _patch_pipeline(_result()):
            response = client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["company"] == "ARK訪問看護"
        assert data["company_id"] == "ark-visiting-nurse"
        assert "隠れた強み" in data["analysis"]
        assert "求人条件比較" in data["analysis"]
        assert "雰囲気・文化" in data["analysis"]
        assert isinstance(data["extracted_hooks"], list)
        assert len(data["extracted_hooks"]) == 3
        assert any("教育ステーション" in h for h in data["extracted_hooks"])
        # New structured fields
        assert data["conditions_table"].startswith("| 施設")
        assert data["culture_narrative"].startswith("研修")
        assert data["sources"] == [{"uri": "https://a.example", "title": "A"}]
        assert data["from_cache"] is False
        assert data["saved_to_sheet"] is True

    def test_writes_to_sheet_on_success(self, client, mock_sheets_client, mock_sheets_writer):
        with _patch_pipeline(_result()):
            client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse"},
            )
        mock_sheets_writer.upsert_competitor_research.assert_called_once()
        kwargs = mock_sheets_writer.upsert_competitor_research.call_args.kwargs
        assert kwargs["company"] == "ark-visiting-nurse"
        assert kwargs["job_category"] == ""
        # to_sheet_dict-shaped payload
        assert "conditions_table" in kwargs["data"]
        assert "hooks" in kwargs["data"]

    def test_accepts_job_category(self, client, mock_sheets_client, mock_sheets_writer):
        with _patch_pipeline(_result()):
            response = client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse", "job_category": "nurse"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["job_category"] == "看護師"
        kwargs = mock_sheets_writer.upsert_competitor_research.call_args.kwargs
        assert kwargs["job_category"] == "nurse"


class TestEndpointErrors:
    def test_empty_company_returns_error(self, client, mock_sheets_client):
        response = client.post(
            "/api/v1/admin/research_competitors",
            json={"company": ""},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "error"

    def test_pipeline_exception_returns_error_not_500(self, client, mock_sheets_client, mock_sheets_writer):
        async def boom(**kwargs):
            raise RuntimeError("gemini died")
        with patch("api.routes_admin.run_research", side_effect=boom):
            response = client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "gemini died" in data["detail"]

    def test_sheet_write_failure_does_not_break_response(self, client, mock_sheets_client, mock_sheets_writer):
        mock_sheets_writer.upsert_competitor_research.side_effect = RuntimeError("sheets down")
        with _patch_pipeline(_result()):
            response = client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse"},
            )
        data = response.json()
        assert data["status"] == "ok"
        assert data["saved_to_sheet"] is False
        assert "sheets down" in data["save_error"]
        # Analysis is still returned
        assert "隠れた強み" in data["analysis"]


class TestCaching:
    def test_cache_hit_skips_pipeline(self, client, mock_sheets_client, mock_sheets_writer):
        """When the sheet already has research for this (company, category),
        reuse it instead of running the expensive pipeline again."""
        mock_sheets_client.get_competitor_research.return_value = {
            "company": "ark-visiting-nurse",
            "job_category": "",
            "conditions_table": "cached table",
            "culture_narrative": "cached culture",
            "hidden_strengths": "cached strengths",
            "hooks": "- cached hook 1\n- cached hook 2",
            "sources": [{"uri": "https://cached.example", "title": "Cached"}],
            "competitors_list": [{"name": "Cached"}],
            "model_used": "cached-model",
            "updated_at": "2026-04-10 10:00:00",
            "updated_by": "tester",
        }
        with patch("api.routes_admin.run_research") as run_mock:
            response = client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse"},
            )
        data = response.json()
        assert data["from_cache"] is True
        assert data["updated_at"] == "2026-04-10 10:00:00"
        assert data["extracted_hooks"] == ["cached hook 1", "cached hook 2"]
        # Pipeline must not be called on cache hit
        run_mock.assert_not_called()
        # And nothing should be written
        mock_sheets_writer.upsert_competitor_research.assert_not_called()

    def test_force_refresh_bypasses_cache(self, client, mock_sheets_client, mock_sheets_writer):
        mock_sheets_client.get_competitor_research.return_value = {
            "conditions_table": "OLD",
            "culture_narrative": "",
            "hidden_strengths": "",
            "hooks": "",
            "sources": [],
            "competitors_list": [],
            "updated_at": "2025-01-01",
        }
        with _patch_pipeline(_result()):
            response = client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse", "force_refresh": True},
            )
        data = response.json()
        assert data["from_cache"] is False
        assert data["conditions_table"].startswith("| 施設")  # fresh data
        mock_sheets_writer.upsert_competitor_research.assert_called_once()

    def test_save_to_sheet_false_skips_write(self, client, mock_sheets_client, mock_sheets_writer):
        with _patch_pipeline(_result()):
            response = client.post(
                "/api/v1/admin/research_competitors",
                json={"company": "ark-visiting-nurse", "save_to_sheet": False},
            )
        assert response.json()["status"] == "ok"
        mock_sheets_writer.upsert_competitor_research.assert_not_called()
