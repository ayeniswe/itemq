from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db import upsert_plugin

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.post("/api/plugins/notion/connect", response_class=HTMLResponse)
async def connect_notion_plugin(
    request: Request,
    token: str = Form(...),
    database: str = Form(...),
):
    upsert_plugin(
        name="notion",
        enabled=True,
        config={
            "token": token,
            "database": database,
        },
    )

    return templates.TemplateResponse(
        "partials/plugin_status.html",
        {
            "request": request,
            "message": "Pulling database rows…",
            "state": "pulling",
        },
    )
