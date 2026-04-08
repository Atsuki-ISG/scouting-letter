"""Google Drive API client for exporting Markdown to Google Docs.

Independent from `sheets_client` / `sheets_writer` because it requires a
different OAuth scope (`drive.file`). Reusing those services directly
would silently fail — the google-auth credentials are scope-locked once
the token is minted.

Usage:
    from db.docs_exporter import docs_exporter
    result = docs_exporter.create_doc_from_markdown(
        title="ARK訪問看護_スカウトレポート_2026-03-09_2026-04-08",
        markdown_text="# ...",
        parent_folder_id="1AbCdEf...",
    )
    # result -> {"id": "...", "webViewLink": "https://docs.google.com/document/d/.../edit"}
"""
from __future__ import annotations

import io

import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

try:
    import markdown as md_lib
except ImportError:  # pragma: no cover — handled at runtime with helpful error
    md_lib = None


_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _markdown_to_html(markdown_text: str) -> str:
    """Convert Markdown to a self-contained HTML string.

    Uses the `markdown` package with the `tables` extension so that
    our KPI / cross-tab tables survive conversion to Google Docs.
    """
    if md_lib is None:
        raise RuntimeError(
            "markdown パッケージがインストールされていません。requirements.txt に markdown を追加してください。"
        )
    body_html = md_lib.markdown(
        markdown_text,
        extensions=["tables", "fenced_code"],
    )
    # Drive import needs a full HTML document. Basic table styling so the
    # imported Doc isn't visually flat.
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<style>"
        "body{font-family:'Helvetica Neue',Arial,sans-serif;}"
        "table{border-collapse:collapse;margin:8px 0;}"
        "th,td{border:1px solid #999;padding:4px 10px;}"
        "th{background:#f0f0f0;}"
        "</style></head><body>"
        f"{body_html}"
        "</body></html>"
    )


class DocsExporter:
    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service is None:
            credentials, _ = google.auth.default(scopes=_DRIVE_SCOPES)
            self._service = build("drive", "v3", credentials=credentials)
        return self._service

    def create_doc_from_markdown(
        self,
        title: str,
        markdown_text: str,
        parent_folder_id: str,
    ) -> dict:
        """Create a new Google Doc from Markdown inside the given Drive folder.

        Returns the file resource with `id` and `webViewLink` populated.
        Raises on API errors; the route handler translates to HTTP 500.
        """
        if not parent_folder_id:
            raise ValueError("parent_folder_id is required")

        html_body = _markdown_to_html(markdown_text)
        service = self._get_service()

        metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [parent_folder_id],
        }
        media = MediaIoBaseUpload(
            io.BytesIO(html_body.encode("utf-8")),
            mimetype="text/html",
            resumable=False,
        )
        file = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id,webViewLink,name",
                supportsAllDrives=True,
            )
            .execute()
        )
        return file


docs_exporter = DocsExporter()
