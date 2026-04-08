"""Tests for POST /admin/expand_template.

Covers:
- same-company expansion (existing behavior + new response shape)
- cross-company expansion (target.company differs from source.company)
- missing source template → 404
- empty targets → 400
- Gemini failure for one target does not break the whole batch
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app


def _fake_operator():
    return {"operator_id": "t", "name": "t", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


TEMPLATE_HEADERS = ["company", "job_category", "type", "body", "version"]


def _mk_rows():
    return [
        TEMPLATE_HEADERS,
        ["ark", "nurse", "パート_初回", "ark看護師パート初回本文", "3"],
        ["ark", "rehab_pt", "パート_初回", "ark PTパート初回本文", "2"],
        ["lcc", "nurse", "パート_初回", "lcc看護師パート初回本文", "1"],
    ]


class TestExpandTemplate:
    @pytest.fixture
    def mock_ai(self):
        async def fake(system, user, *, max_output_tokens=2048, temperature=0.3):
            class R:
                text = "生成された適応版本文"
                model_name = "test-model"
            return R()
        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=fake) as m:
            yield m

    def test_same_company_expansion(self, client, mock_ai):
        with patch("api.routes_admin.sheets_writer") as mw, \
             patch("api.routes_admin.sheets_client.get_company_profile", return_value="ARK profile"):
            mw.get_all_rows.return_value = _mk_rows()
            res = client.post("/api/v1/admin/expand_template", json={
                "company": "ark",
                "source_job_category": "nurse",
                "source_template_type": "パート_初回",
                "targets": [
                    {"job_category": "rehab_pt", "template_type": "パート_初回"},
                ],
            })
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert len(body["results"]) == 1
        r = body["results"][0]
        assert r["company"] == "ark"
        assert r["job_category"] == "rehab_pt"
        assert r["template_type"] == "パート_初回"
        assert r["original"] == "ark PTパート初回本文"
        assert r["proposed"] == "生成された適応版本文"
        assert r["row_index"] == 3

    def test_cross_company_expansion_uses_target_profile(self, client, mock_ai):
        with patch("api.routes_admin.sheets_writer") as mw, \
             patch("api.routes_admin.sheets_client.get_company_profile") as prof:
            mw.get_all_rows.return_value = _mk_rows()
            prof.side_effect = lambda cid: {
                "ark": "ARK profile",
                "lcc": "LCC profile",
            }.get(cid, "")
            res = client.post("/api/v1/admin/expand_template", json={
                "company": "ark",
                "source_job_category": "nurse",
                "source_template_type": "パート_初回",
                "targets": [
                    {"company": "lcc", "job_category": "nurse", "template_type": "パート_初回"},
                ],
            })
        assert res.status_code == 200
        r = res.json()["results"][0]
        assert r["company"] == "lcc"
        assert r["row_index"] == 4
        assert r["original"] == "lcc看護師パート初回本文"
        # Profile lookup should have been called for BOTH source and target
        # (source is fetched only if accessed; we accept that the LCC call
        # happens as a minimum)
        called_companies = [c.args[0] for c in prof.call_args_list]
        assert "lcc" in called_companies

    def test_cross_company_new_target_has_no_row_index(self, client, mock_ai):
        """Expanding to a (company, jc, type) combo that doesn't exist yet
        should still return a result with row_index=None so the frontend
        can send it as a new row to batch_update_templates."""
        with patch("api.routes_admin.sheets_writer") as mw, \
             patch("api.routes_admin.sheets_client.get_company_profile", return_value=""):
            mw.get_all_rows.return_value = _mk_rows()
            res = client.post("/api/v1/admin/expand_template", json={
                "company": "ark",
                "source_job_category": "nurse",
                "source_template_type": "パート_初回",
                "targets": [
                    {"company": "lcc", "job_category": "rehab_pt", "template_type": "パート_初回"},
                ],
            })
        r = res.json()["results"][0]
        assert r["company"] == "lcc"
        assert r["row_index"] is None
        assert r["original"] == ""

    def test_missing_source_returns_404(self, client, mock_ai):
        with patch("api.routes_admin.sheets_writer") as mw, \
             patch("api.routes_admin.sheets_client.get_company_profile", return_value=""):
            mw.get_all_rows.return_value = _mk_rows()
            res = client.post("/api/v1/admin/expand_template", json={
                "company": "ark",
                "source_job_category": "nurse",
                "source_template_type": "正社員_再送",  # doesn't exist
                "targets": [{"job_category": "nurse", "template_type": "パート_初回"}],
            })
        assert res.status_code == 404

    def test_empty_targets_returns_400(self, client, mock_ai):
        with patch("api.routes_admin.sheets_writer") as mw:
            mw.get_all_rows.return_value = _mk_rows()
            res = client.post("/api/v1/admin/expand_template", json={
                "company": "ark",
                "source_job_category": "nurse",
                "source_template_type": "パート_初回",
                "targets": [],
            })
        assert res.status_code == 400

    def test_gemini_error_on_one_target_does_not_fail_batch(self, client):
        """One failing target should surface as result.error and let the
        rest succeed."""
        calls = {"n": 0}

        async def partial_fake(system, user, *, max_output_tokens=2048, temperature=0.3):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("rate limit")

            class R:
                text = "ok"
                model_name = "test-model"
            return R()

        with patch("pipeline.ai_generator.generate_personalized_text", side_effect=partial_fake), \
             patch("api.routes_admin.sheets_writer") as mw, \
             patch("api.routes_admin.sheets_client.get_company_profile", return_value=""):
            mw.get_all_rows.return_value = _mk_rows()
            res = client.post("/api/v1/admin/expand_template", json={
                "company": "ark",
                "source_job_category": "nurse",
                "source_template_type": "パート_初回",
                "targets": [
                    {"job_category": "rehab_pt", "template_type": "パート_初回"},
                    {"company": "lcc", "job_category": "nurse", "template_type": "パート_初回"},
                ],
            })
        assert res.status_code == 200
        results = res.json()["results"]
        assert len(results) == 2
        assert results[0].get("error") == "rate limit"
        assert results[0]["proposed"] == ""
        assert results[1]["proposed"] == "ok"
