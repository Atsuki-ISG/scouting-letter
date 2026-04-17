"""Tests for the scout diagnosis system (Stage 1).

TDD tests for:
- POST /admin/diagnose_template (diagnosis endpoint)
- POST /admin/save_diagnosis_knowledge (knowledge accumulation)
- Diagnosis history sheet writing
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

from main import app
from auth.api_key import verify_api_key
from pipeline.ai_generator import GenerationResult


def _fake_operator():
    return {"operator_id": "t", "name": "tester", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


# Template sheet data: header + 1 data row (row_index=2 in 1-based)
_TEMPLATE_ROWS = [
    ["company", "job_category", "type", "body", "version"],  # header
    ["ark-visiting-nurse", "看護師", "正社員_default", "テンプレート本文\\n{personalized_text}\\n会社紹介", "3"],  # row_index=2
]

# Send data with no rows (just header, no 全文 column for backwards compat)
_SEND_DATA_EMPTY = [
    ["日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
     "生成パス", "パターン", "年齢層", "資格", "経験区分", "希望雇用形態",
     "就業状況", "地域", "曜日", "時間帯", "全文", "返信", "返信日", "返信カテゴリ"],
]


def _sheets_writer_get_all_rows(sheet_name):
    """Route get_all_rows to appropriate mock data based on sheet name."""
    if sheet_name == "テンプレート":
        return _TEMPLATE_ROWS
    # send data sheets
    return _SEND_DATA_EMPTY


@pytest.fixture
def mock_sheets_writer():
    with patch("api.routes_admin.sheets_writer") as sw:
        sw.ensure_sheet_exists = MagicMock()
        sw.append_rows = MagicMock()
        sw.get_all_rows = MagicMock(side_effect=_sheets_writer_get_all_rows)
        yield sw


@pytest.fixture
def mock_sheets_client():
    with patch("api.routes_admin.sheets_client") as sc:
        sc.get_company_profile = MagicMock(return_value="テスト会社プロフィール")
        sc.reload = MagicMock()
        yield sc


VALID_DIAGNOSIS_JSON = json.dumps({
    "gate_scores": {"gate1_open": "B", "gate2_read": "A", "gate3_reply": "C"},
    "weak_principles": [
        {"principle": "返報性", "issue": "具体的評価なし", "severity": "high"}
    ],
    "ai_smell": [
        {"fingerprint": "接続詞偏り", "evidence": "「さらに」「また」連続", "fix_hint": "接続詞を削る"}
    ],
    "structure_issues": [
        {"issue": "会社紹介が冒頭", "detail": "最初2文が会社情報", "severity": "high"}
    ],
    "personalization_issues": [],
    "integration_issues": [],
    "strengths": ["CTAが低ハードル"],
    "priority_actions": [
        {"action": "冒頭を候補者評価に変更", "impact": "high", "target": "template"},
        {"action": "プロンプトに経験年数指示追加", "impact": "medium", "target": "prompt"},
    ],
    "improvement_targets": {"template": True, "prompt": True, "recipes": False},
}, ensure_ascii=False)


def _mock_diagnosis_ai():
    """Return a patch that makes generate_structured return the valid diagnosis dict.

    The endpoint now uses generate_structured (JSON-schema enforced) so we
    mock that instead of the legacy generate_personalized_text path.
    """
    import json as _json
    parsed = _json.loads(VALID_DIAGNOSIS_JSON)

    async def fake_generate(*, system_prompt, user_prompt, response_schema, **kwargs):
        meta = GenerationResult(
            text=VALID_DIAGNOSIS_JSON,
            prompt_tokens=3000,
            output_tokens=500,
            total_tokens=3500,
            model_name="gemini-2.5-pro",
        )
        return parsed, meta

    return patch(
        "pipeline.ai_generator.generate_structured",
        side_effect=fake_generate,
    )


def _mock_diagnosis_ai_invalid_json():
    """Return a patch where generate_structured raises (simulating parse failure).

    generate_structured raises ValueError when Gemini returns something that
    isn't valid JSON for the schema — that's the new failure path.
    """
    async def fake_generate(*, system_prompt, user_prompt, response_schema, **kwargs):
        raise ValueError("AI JSON schema validation failed")

    return patch(
        "pipeline.ai_generator.generate_structured",
        side_effect=fake_generate,
    )


# ============================================================
# diagnose_template endpoint tests
# ============================================================

class TestDiagnoseTemplate:
    """Tests for POST /api/v1/admin/diagnose_template."""

    def test_basic_diagnosis(self, client, mock_sheets_writer, mock_sheets_client):
        """Should return structured diagnosis with gate scores."""
        with _mock_diagnosis_ai():
            resp = client.post("/api/v1/admin/diagnose_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "job_category": "看護師",
                "row_index": 2,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "diagnosis" in data
        diag = data["diagnosis"]
        assert diag["gate_scores"]["gate1_open"] in ("A", "B", "C")
        assert diag["gate_scores"]["gate2_read"] in ("A", "B", "C")
        assert diag["gate_scores"]["gate3_reply"] in ("A", "B", "C")
        assert isinstance(diag["weak_principles"], list)
        assert isinstance(diag["ai_smell"], list)
        assert isinstance(diag["priority_actions"], list)
        assert isinstance(diag["improvement_targets"], dict)

    def test_diagnosis_returns_context(self, client, mock_sheets_writer, mock_sheets_client):
        """Should include context info (company, template_type, stats)."""
        with _mock_diagnosis_ai():
            resp = client.post("/api/v1/admin/diagnose_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
            })
        data = resp.json()
        assert "context" in data
        ctx = data["context"]
        assert ctx["company"] == "ark-visiting-nurse"
        assert ctx["template_type"] == "正社員_default"

    def test_diagnosis_returns_id(self, client, mock_sheets_writer, mock_sheets_client):
        """Should return a diagnosis_id for tracking."""
        with _mock_diagnosis_ai():
            resp = client.post("/api/v1/admin/diagnose_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
            })
        data = resp.json()
        assert "diagnosis_id" in data
        assert data["diagnosis_id"].startswith("diag_")

    def test_diagnosis_writes_history(self, client, mock_sheets_writer, mock_sheets_client):
        """Should write diagnosis result to history sheet."""
        with _mock_diagnosis_ai():
            client.post("/api/v1/admin/diagnose_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
            })
        # Check that ensure_sheet_exists was called with 診断履歴
        calls = [c for c in mock_sheets_writer.ensure_sheet_exists.call_args_list
                 if c[0][0] == "診断履歴"]
        assert len(calls) >= 1, "ensure_sheet_exists('診断履歴', ...) was not called"
        # Check headers passed
        headers = calls[0][0][1]
        assert "id" in headers
        assert "gate1_score" in headers

        # Check append_rows was called for history
        append_calls = mock_sheets_writer.append_rows.call_args_list
        history_calls = [c for c in append_calls if c[0][0] == "診断履歴"]
        assert len(history_calls) >= 1, "append_rows('診断履歴', ...) was not called"
        history_row = history_calls[0][0][1][0]
        assert history_row[0].startswith("diag_")  # id
        assert history_row[2] == "ark-visiting-nurse"  # company

    def test_diagnosis_invalid_json_returns_error(self, client, mock_sheets_writer, mock_sheets_client):
        """generate_structured raising should translate to an error response."""
        with _mock_diagnosis_ai_invalid_json():
            resp = client.post("/api/v1/admin/diagnose_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        # Error surfaces under "AI呼び出しエラー" now (structured output layer).
        assert "AI" in data.get("detail", "") or "エラー" in data.get("detail", "")

    def test_diagnosis_missing_company(self, client, mock_sheets_writer, mock_sheets_client):
        """Should return error when company is missing."""
        with _mock_diagnosis_ai():
            resp = client.post("/api/v1/admin/diagnose_template", json={
                "template_type": "正社員_default",
                "row_index": 2,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_diagnosis_with_full_text_samples(self, client, mock_sheets_writer, mock_sheets_client):
        """Should use full_text samples from send data when available."""
        send_rows_with_data = [
            _SEND_DATA_EMPTY[0],  # header
            ["2026-04-14 10:00:00", "M001", "看護師", "正社員_default", "3",
             "standard", "", "30代", "看護師", "5-10年", "正職員",
             "在職中", "東京都", "月曜", "10-12時",
             "完成形スカウト文サンプル1", "", "", ""],
        ]

        def _get_all_rows_with_samples(sheet_name):
            if sheet_name == "テンプレート":
                return _TEMPLATE_ROWS
            return send_rows_with_data

        mock_sheets_writer.get_all_rows.side_effect = _get_all_rows_with_samples

        with _mock_diagnosis_ai() as mock_ai:
            resp = client.post("/api/v1/admin/diagnose_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
            })
            assert resp.json()["status"] == "ok"
            assert resp.json()["context"]["sample_count"] == 1
            # Verify the user prompt includes sample text
            if mock_ai.call_count > 0:
                call_args = mock_ai.call_args
                user_prompt = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("user_prompt", "")
                assert "完成形スカウト文サンプル" in user_prompt

    def test_diagnosis_without_full_text_column(self, client, mock_sheets_writer, mock_sheets_client):
        """Should work gracefully when send data has no 全文 column (old data)."""
        old_send_headers = [
            "日時", "会員番号", "職種カテゴリ", "テンプレート種別", "テンプレートVer",
            "生成パス", "パターン", "年齢層", "資格", "経験区分", "希望雇用形態",
            "就業状況", "地域", "曜日", "時間帯", "返信", "返信日", "返信カテゴリ",
        ]

        def _get_all_rows_old_format(sheet_name):
            if sheet_name == "テンプレート":
                return _TEMPLATE_ROWS
            return [old_send_headers]

        mock_sheets_writer.get_all_rows.side_effect = _get_all_rows_old_format

        with _mock_diagnosis_ai():
            resp = client.post("/api/v1/admin/diagnose_template", json={
                "company": "ark-visiting-nurse",
                "template_type": "正社員_default",
                "row_index": 2,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["context"]["sample_count"] == 0


# ============================================================
# save_diagnosis_knowledge endpoint tests
# ============================================================

class TestSaveDiagnosisKnowledge:
    """Tests for POST /api/v1/admin/save_diagnosis_knowledge."""

    def test_save_knowledge_basic(self, client, mock_sheets_writer):
        """Should write a rule to knowledge pool with status=pending."""
        resp = client.post("/api/v1/admin/save_diagnosis_knowledge", json={
            "company": "ark-visiting-nurse",
            "category": "expression",
            "rule": "「さらに」「また」の3連続を避ける",
            "source": "診断 2026-04-14",
            "diagnosis_id": "diag_abc123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "id" in data

        # Verify sheet write
        mock_sheets_writer.append_rows.assert_called_once()
        rows = mock_sheets_writer.append_rows.call_args[0][1]
        row = rows[0]
        # Find status field - should be "pending"
        assert "pending" in row

    def test_save_knowledge_validates_category(self, client, mock_sheets_writer):
        """Should reject invalid categories."""
        resp = client.post("/api/v1/admin/save_diagnosis_knowledge", json={
            "company": "ark-visiting-nurse",
            "category": "invalid_category",
            "rule": "テストルール",
            "source": "テスト",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_save_knowledge_requires_rule(self, client, mock_sheets_writer):
        """Should reject empty rule."""
        resp = client.post("/api/v1/admin/save_diagnosis_knowledge", json={
            "company": "ark-visiting-nurse",
            "category": "tone",
            "rule": "",
            "source": "テスト",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_save_knowledge_global_rule(self, client, mock_sheets_writer):
        """Should allow empty company for global rules."""
        resp = client.post("/api/v1/admin/save_diagnosis_knowledge", json={
            "company": "",
            "category": "expression",
            "rule": "全社共通ルール",
            "source": "診断",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
