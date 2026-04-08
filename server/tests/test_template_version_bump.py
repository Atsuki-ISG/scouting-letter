"""Regression tests for template body version-bump logic.

Covers both code paths:
- `PUT /admin/templates/{row_index}` (update_row)
- `POST /admin/batch_update_templates`

Hypotheses the tests pin down:
1. version increments exactly +1 per body change
2. header cells with surrounding whitespace still resolve correctly
3. empty/missing version values bump to "2"
4. no-op when body unchanged (including \\n literal vs real newline variants)
5. consecutive applies produce consecutive versions (no sticky "2")
6. change history sheet gets exactly one row per bump with the old body
7. company guard: batch_update rejects row_index that targets a different company
8. strict column mode raises when a required column is missing
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auth.api_key import verify_api_key
from main import app
from db.sheets_writer import SheetsWriter


def _fake_operator():
    return {"operator_id": "test", "name": "tester", "role": "admin"}


@pytest.fixture
def client():
    app.dependency_overrides[verify_api_key] = _fake_operator
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key, None)


# ---------------------------------------------------------------------------
# In-memory fake sheets writer. Each test constructs one per scenario.
# ---------------------------------------------------------------------------

class FakeSheets:
    """Drop-in fake for `sheets_writer` that stores rows in memory.

    Only implements the methods routes_admin touches for template updates.
    """

    def __init__(self, initial: dict[str, list[list[str]]] | None = None):
        self.data: dict[str, list[list[str]]] = {
            name: [list(row) for row in rows]
            for name, rows in (initial or {}).items()
        }
        self.audit: list[tuple[str, str, int, dict]] = []

    # --- read ---
    def get_all_rows(self, sheet_name: str) -> list[list[str]]:
        return [list(row) for row in self.data.get(sheet_name, [])]

    # --- write ---
    def append_row(self, sheet_name: str, values: list[str]) -> None:
        self.data.setdefault(sheet_name, []).append(list(values))

    def ensure_sheet_exists(self, sheet_name: str, headers: list[str] | None = None) -> None:
        if sheet_name not in self.data:
            self.data[sheet_name] = [list(headers)] if headers else []

    def update_cells_by_name(
        self,
        sheet_name: str,
        row_index: int,
        cells: dict[str, str],
        *,
        actor: str = "",
        strict_columns: list[str] | None = None,
    ) -> dict:
        rows = self.data.get(sheet_name, [])
        if not rows or row_index < 2 or row_index > len(rows):
            raise ValueError(f"row {row_index} out of range in {sheet_name}")
        # Mirror the real writer: strip headers before matching
        headers = [h.strip() for h in rows[0]]
        row = rows[row_index - 1]
        while len(row) < len(headers):
            row.append("")

        updated: list[str] = []
        skipped: list[str] = []
        for col_name, value in cells.items():
            if col_name in headers:
                row[headers.index(col_name)] = value
                updated.append(col_name)
            else:
                skipped.append(col_name)

        if strict_columns:
            missing = [c for c in strict_columns if c in skipped]
            if missing:
                raise ValueError(
                    f"required column(s) missing in '{sheet_name}': {missing}"
                )

        self.audit.append(("update", sheet_name, row_index, dict(cells)))
        return {"updated": updated, "skipped": skipped}

    def delete_row(self, sheet_name: str, row_index: int, *, actor: str = "") -> None:
        rows = self.data.get(sheet_name, [])
        if 2 <= row_index <= len(rows):
            rows.pop(row_index - 1)


TEMPLATE_HEADERS = ["company", "job_category", "type", "body", "version"]


def _install(monkeypatch, fake: FakeSheets) -> None:
    """Patch sheets_writer + sheets_client.reload to use the fake."""
    monkeypatch.setattr("api.routes_admin.sheets_writer", fake)
    monkeypatch.setattr("api.routes_admin.sheets_client.reload", lambda: None)


# ---------------------------------------------------------------------------
# PUT /admin/templates/{row_index}  via update_row
# ---------------------------------------------------------------------------

class TestSingleUpdateVersionBump:
    def test_clean_bump(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "古い本文", "3"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.put(
            "/api/v1/admin/templates/2",
            json={"body": "新しい本文", "_change_reason": "改善"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["version"] == "4"
        assert fake.data["テンプレート"][1] == ["ark", "nurse", "パート_初回", "新しい本文", "4"]
        # history logged
        history = fake.data.get("テンプレート変更履歴", [])
        assert len(history) == 2  # header + 1 record
        assert history[1][4] == "3"  # old_version
        assert history[1][5] == "4"  # new_version
        assert history[1][7] == "古い本文"  # old_body

    def test_header_with_trailing_whitespace(self, client, monkeypatch):
        """Sheet header cells sometimes carry stray whitespace. version bump
        must still land on the correct column."""
        fake = FakeSheets({
            "テンプレート": [
                ["company", "job_category", "type", "body ", " version"],
                ["ark", "nurse", "パート_初回", "古い本文", "5"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.put(
            "/api/v1/admin/templates/2",
            json={"body": "新本文", "_change_reason": "改善"},
        )
        assert res.status_code == 200
        row = fake.data["テンプレート"][1]
        assert row[3] == "新本文"
        assert row[4] == "6"

    def test_empty_version_becomes_two(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "本文", ""],
            ],
        })
        _install(monkeypatch, fake)

        res = client.put("/api/v1/admin/templates/2", json={"body": "別本文"})
        assert res.status_code == 200
        assert fake.data["テンプレート"][1][4] == "2"

    def test_noop_on_identical_body(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "同じ本文", "7"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.put("/api/v1/admin/templates/2", json={"body": "同じ本文"})
        assert res.status_code == 200
        # version must not move
        assert fake.data["テンプレート"][1][4] == "7"
        # no history row
        assert "テンプレート変更履歴" not in fake.data or \
            len(fake.data.get("テンプレート変更履歴", [])) <= 1

    def test_noop_across_newline_encoding(self, client, monkeypatch):
        """Body stored with real newlines; caller sends the \\n-literal variant
        of the same content. Should treat as no-op."""
        stored = "行1\n行2\n行3"
        sent_literal = r"行1\n行2\n行3"
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", stored, "4"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.put("/api/v1/admin/templates/2", json={"body": sent_literal})
        assert res.status_code == 200
        assert fake.data["テンプレート"][1][4] == "4"

    def test_consecutive_updates_increment(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "v0", "1"],
            ],
        })
        _install(monkeypatch, fake)

        client.put("/api/v1/admin/templates/2", json={"body": "v1"})
        client.put("/api/v1/admin/templates/2", json={"body": "v2"})
        client.put("/api/v1/admin/templates/2", json={"body": "v3"})

        row = fake.data["テンプレート"][1]
        assert row[3] == "v3"
        assert row[4] == "4"  # 1 -> 2 -> 3 -> 4
        # 3 history rows
        history = fake.data.get("テンプレート変更履歴", [])
        assert len(history) == 4  # header + 3


# ---------------------------------------------------------------------------
# POST /admin/batch_update_templates
# ---------------------------------------------------------------------------

class TestBatchUpdateVersionBump:
    def test_clean_bump_via_batch(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "旧", "2"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/batch_update_templates",
            json={"updates": [{"row_index": 2, "body": "新", "reason": "一括展開"}]},
        )
        assert res.status_code == 200
        assert res.json()["updated"] == 1
        row = fake.data["テンプレート"][1]
        assert row[3] == "新"
        assert row[4] == "3"

    def test_batch_with_whitespace_header(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                ["company ", " job_category", "type ", "body", " version "],
                ["ark", "nurse", "パート_初回", "旧", "8"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/batch_update_templates",
            json={"updates": [{"row_index": 2, "body": "新"}]},
        )
        assert res.status_code == 200
        row = fake.data["テンプレート"][1]
        # Must increment from 8 to 9, NOT stick at 2
        assert row[4] == "9"

    def test_batch_noop_on_identical_body(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "同じ", "5"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/batch_update_templates",
            json={"updates": [{"row_index": 2, "body": "同じ"}]},
        )
        assert res.status_code == 200
        assert res.json()["updated"] == 0
        assert fake.data["テンプレート"][1][4] == "5"

    def test_batch_multiple_rows(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "A", "1"],
                ["ark", "nurse", "正社員_初回", "B", "1"],
                ["lcc", "nurse", "パート_初回", "C", "1"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/batch_update_templates",
            json={
                "updates": [
                    {"row_index": 2, "company": "ark", "body": "A2"},
                    {"row_index": 3, "company": "ark", "body": "B"},  # no-op
                    {"row_index": 4, "company": "lcc", "body": "C2"},
                ]
            },
        )
        assert res.status_code == 200
        assert res.json()["updated"] == 2
        assert fake.data["テンプレート"][1][4] == "2"
        assert fake.data["テンプレート"][2][4] == "1"  # no-op preserved
        assert fake.data["テンプレート"][3][4] == "2"

    def test_batch_rejects_wrong_company_row_index(self, client, monkeypatch):
        """Guard: row_index belongs to ark, upd says lcc → skip."""
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "ark本文", "1"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/batch_update_templates",
            json={
                "updates": [
                    {"row_index": 2, "company": "lcc", "body": "壊れた"},
                ]
            },
        )
        assert res.status_code == 200
        assert res.json()["updated"] == 0
        # row untouched
        assert fake.data["テンプレート"][1][3] == "ark本文"
        assert fake.data["テンプレート"][1][4] == "1"

    def test_batch_creates_new_row_when_row_index_missing(self, client, monkeypatch):
        fake = FakeSheets({
            "テンプレート": [
                TEMPLATE_HEADERS,
                ["ark", "nurse", "パート_初回", "既存", "1"],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/batch_update_templates",
            json={
                "updates": [
                    {
                        "company": "ark",
                        "job_category": "rehab_pt",
                        "template_type": "パート_初回",
                        "body": "新規",
                    }
                ]
            },
        )
        assert res.status_code == 200
        assert res.json()["updated"] == 1
        assert len(fake.data["テンプレート"]) == 3
        assert fake.data["テンプレート"][2] == ["ark", "rehab_pt", "パート_初回", "新規", "1"]


# ---------------------------------------------------------------------------
# Strict column mode (version / body must exist)
# ---------------------------------------------------------------------------

class TestStrictColumnEnforcement:
    def test_missing_version_column_reported(self, client, monkeypatch):
        """If the sheet has no 'version' column, batch_update should NOT silently
        bump body without recording a version — it should surface an error so
        the data drift gets fixed. The endpoint should still return 200 with a
        clear warning in the payload."""
        fake = FakeSheets({
            "テンプレート": [
                ["company", "job_category", "type", "body"],  # no version
                ["ark", "nurse", "パート_初回", "旧", ""],
            ],
        })
        _install(monkeypatch, fake)

        res = client.post(
            "/api/v1/admin/batch_update_templates",
            json={"updates": [{"row_index": 2, "body": "新"}]},
        )
        # Current behaviour decision: surface HTTP 500 so the director sees it.
        assert res.status_code == 500
        # Body must not have been touched
        assert fake.data["テンプレート"][1][3] == "旧"
