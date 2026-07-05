import logging

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes_generate import router as generate_router
from api.routes_companies import router as companies_router
from api.routes_admin import router as admin_router
from config import LATEST_EXTENSION_VERSION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Scout Generation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    # chrome-extension://<id> と管理画面(https) の両方を許可。
    # cookie 認証は使っていないので credentials は False で OK（
    # credentials=True + allow_origins=["*"] は Starlette が ACAO を送らない壊れた組み合わせ）。
    allow_origin_regex=r"^(chrome-extension://.*|https?://.*)$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # 拡張が JS からバージョン判定ヘッダーを読めるように expose する（cross-origin では必須）。
    expose_headers=["X-Latest-Extension-Version", "X-Extension-Outdated"],
)


def _parse_version(v: str) -> tuple:
    """'1.2.0' → (1,2,0)。数値化できない要素は 0 扱い。"""
    parts = []
    for p in (v or "").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


@app.middleware("http")
async def extension_version_check(request: Request, call_next):
    """拡張の X-Extension-Version を監視し、旧版を検知する。

    Why: 拡張は手動zip配布で、誰が古いビルドを使い続けているか把握する手段が
    なかった。旧版は既知バグ（例: 生成結果の欠落）を手元で踏み続けるため、
    (1) 旧版リクエストをログに残して開発者が気づけるように、
    (2) レスポンスヘッダーで拡張に更新を促す。
    ヘッダー未送信（管理画面・curl 等）は判定対象外。
    """
    client_ver = request.headers.get("X-Extension-Version")
    response = await call_next(request)
    if client_ver:
        response.headers["X-Latest-Extension-Version"] = LATEST_EXTENSION_VERSION
        outdated = _parse_version(client_ver) < _parse_version(LATEST_EXTENSION_VERSION)
        response.headers["X-Extension-Outdated"] = "true" if outdated else "false"
        if outdated:
            logger.warning(
                "Outdated extension: version=%s latest=%s path=%s",
                client_ver, LATEST_EXTENSION_VERSION, request.url.path,
            )
    return response

app.include_router(generate_router, prefix="/api/v1")
app.include_router(companies_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")


@app.middleware("http")
async def admin_no_cache(request: Request, call_next):
    """Force browsers to revalidate /admin/* on every load.

    Why: admin HTML/JS are SPA-style single files served from Cloud Run. When
    we ship a label or bug fix, operators had to hard-reload to pick it up —
    confusing for non-engineers. Admin traffic is tiny so disabling caching
    has negligible cost.
    """
    response = await call_next(request)
    if request.url.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.mount("/admin", StaticFiles(directory="admin", html=True), name="admin")


@app.on_event("startup")
async def startup():
    from db.sheets_client import sheets_client
    logger.info("Loading config from Google Sheets...")
    sheets_client.reload()
    logger.info("Config loaded.")

    # バックグラウンドスケジューラは廃止（Cloud Runではリクエスト外で動けない）
    # Cloud Scheduler → POST /api/v1/admin/cron/daily-report に移行済み


@app.get("/health")
async def health_check():
    return {"status": "ok"}
