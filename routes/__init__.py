from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from routes.inventory import router as inventory_router
from routes.plugins import router as plugins_router

from contextlib import asynccontextmanager
from pathlib import Path
import os

from db import init_db, get_plugin

@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB path can be passed from CLI via env var
    db_path = os.environ.get("ITEMQ_DB_PATH")

    if db_path:
        db_path = Path(db_path)
    else:
        # Fallback to project root
        db_path = Path.cwd() / "itemq.db"

    init_db(db_path)
    print(f"✅ DB initialized at startup: {db_path.resolve()}")

    yield

app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory="data/images"), name="media")

app.include_router(inventory_router)
app.include_router(plugins_router)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("base.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/generate", response_class=HTMLResponse)
async def generate(request: Request):
    return templates.TemplateResponse("generate.html", {"request": request})


@app.get("/inventory", response_class=HTMLResponse)
async def inventory(request: Request):
    return templates.TemplateResponse("inventory.html", {"request": request})


@app.get("/plugins", response_class=HTMLResponse)
async def plugins(request: Request):
    notion_plugin = get_plugin("notion")
    return templates.TemplateResponse(
        "plugins.html",
        {
            "request": request,
            "notion_plugin": notion_plugin,
        },
    )
