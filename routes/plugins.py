import re
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from notion_client import Client

from db import upsert_plugin

router = APIRouter()
templates = Jinja2Templates(directory="templates")

REQUIRED_NOTION_FIELDS = {
    "Name",
    "Barcode",
    "Quantity",
    "Source",
    "Image",
}


@router.post("/api/plugins/notion/connect", response_class=HTMLResponse)
async def connect_notion_plugin(
    request: Request,
    token: str = Form(...),
    database: str = Form(...),
):
    database_id = _extract_database_id(database)
    if not database_id:
        return _render_status(
            request,
            message=(
                "Invalid Notion database link. Columns must follow the same"
                " column format as the inventory tracking page."
            ),
            state="error",
        )

    try:
        notion = Client(auth=token)
        db = notion.databases.retrieve(database_id=database_id)
        _validate_database_schema(db)
        _fetch_all_database_rows(notion, database_id)
    except Exception:
        return _render_status(
            request,
            message=(
                "Notion connection failed. Columns must follow the same column"
                " format as the inventory tracking page."
            ),
            state="error",
        )

    upsert_plugin(
        name="notion",
        enabled=True,
        config={
            "token": token,
            "database": database,
        },
    )

    return _render_status(
        request,
        message="Pulling database rows…",
        state="pulling",
    )


def _render_status(request: Request, message: str, state: str) -> HTMLResponse:
    return templates.TemplateResponse(
        "partials/plugin_status.html",
        {
            "request": request,
            "message": message,
            "state": state,
        },
    )


def _extract_database_id(database_url: str) -> str | None:
    parsed = urlparse(database_url)
    candidate = parsed.path.split("/")[-1]
    match = re.search(r"[0-9a-fA-F]{32}", candidate.replace("-", ""))
    if match:
        return match.group(0)
    return None


def _validate_database_schema(database: dict) -> None:
    properties = set(database.get("properties", {}).keys())
    missing = REQUIRED_NOTION_FIELDS - properties
    if missing:
        raise ValueError("Missing required properties")


def _fetch_all_database_rows(notion: Client, database_id: str) -> None:
    cursor = None
    while True:
        response = notion.databases.query(
            database_id=database_id,
            start_cursor=cursor,
        )
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
