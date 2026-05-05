from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from app.database import engine, Base
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


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.stop()


@app.get("/")
async def root():
    return {"status": "running"}


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
