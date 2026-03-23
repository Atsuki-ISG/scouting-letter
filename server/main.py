import logging

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import CORS_ORIGINS
from api.routes_generate import router as generate_router
from api.routes_companies import router as companies_router
from api.routes_admin import router as admin_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Scout Generation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate_router, prefix="/api/v1")
app.include_router(companies_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")

app.mount("/admin", StaticFiles(directory="admin", html=True), name="admin")


@app.on_event("startup")
async def startup():
    from db.sheets_client import sheets_client
    logger.info("Loading config from Google Sheets...")
    sheets_client.reload()
    logger.info("Config loaded.")

    from monitoring.scheduler import start_scheduler
    await start_scheduler()


@app.get("/health")
async def health_check():
    return {"status": "ok"}
