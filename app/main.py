from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select, func

from app.config import settings
from app.database import engine, Base, AsyncSessionLocal
from app.models import Setting
from app.routers import leads, webhooks, dashboard, settings as settings_router, auth
from app.services import scheduler

app = FastAPI()
app.include_router(auth.router)
app.include_router(leads.router)
app.include_router(webhooks.router)
app.include_router(dashboard.router)
app.include_router(settings_router.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

DASHBOARD_PAGES = {"overview", "leads", "policy", "activity", "settings", "approvals"}


async def _validate_secrets_or_raise() -> None:
    """Surface secret-config mistakes at boot, not deep in a request.

    - AUTH_REQUIRED=true with an empty JWT_SECRET would 500 every login.
    - Stored secret rows with an empty ENCRYPTION_KEY would 500 every
      sender/credential read. (We only check rows that actually exist —
      a fresh install with no stored secrets is allowed to boot without a
      key, since encryption is lazy.)
    """
    if settings.AUTH_REQUIRED and not settings.JWT_SECRET:
        raise RuntimeError(
            "AUTH_REQUIRED=true but JWT_SECRET is empty. Set JWT_SECRET in .env "
            "to a long random string before booting."
        )

    if not settings.ENCRYPTION_KEY:
        async with AsyncSessionLocal() as db:
            stored_secrets = await db.scalar(
                select(func.count(Setting.key)).where(
                    Setting.is_secret.is_(True),
                    Setting.value != "",
                )
            )
        if stored_secrets:
            raise RuntimeError(
                f"ENCRYPTION_KEY is empty but {stored_secrets} encrypted setting(s) "
                "exist in the DB. Set ENCRYPTION_KEY in .env or those rows can't be "
                "decrypted."
            )


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _validate_secrets_or_raise()
    scheduler.start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.stop()


@app.get("/")
async def root():
    return {"status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/dashboard")
async def dashboard_index():
    return RedirectResponse(url="/dashboard/overview")


@app.get("/dashboard/{page}")
async def dashboard_page(page: str):
    if page not in DASHBOARD_PAGES:
        raise HTTPException(status_code=404)
    return FileResponse(FRONTEND_DIR / f"{page}.html")


@app.get("/login")
async def login_page():
    return FileResponse(FRONTEND_DIR / "login.html")
