from __future__ import annotations

import json
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db import (
    get_plugin,
    upsert_plugin,
    update_plugin_enabled,
    update_plugin_config,
    delete_inventory_by_source,
)
from services.notion_worker import (
    NotionWorker,
    connect_to_notion,
    validate_notion_schema,
    fetch_database_rows,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_notion_worker = NotionWorker()
_notion_status = {"state": "idle", "message": None}


def _serialize_plugin_row(row) -> dict | None:
    if row is None:
        return None
    config = json.loads(row[3]) if row[3] else None
    return {
        "id": row[0],
        "name": row[1],
        "enabled": bool(row[2]),
        "config": config,
    }


def _start_notion_worker(plugin: dict | None) -> None:
    if not plugin or not plugin.get("config"):
        return

    def worker_task(stop_event):
        while not stop_event.is_set():
            _notion_status["state"] = "fetching"
            _notion_status["message"] = "Fetching database rows…"
            fetch_database_rows(plugin["config"]["database_id"])
            _notion_status["state"] = "idle"
            _notion_status["message"] = "Notion sync is up to date."
            stop_event.wait(10)

    _notion_worker.start(worker_task)


@router.get("/api/plugins/notion/status", response_class=HTMLResponse)
async def notion_status(request: Request):
    plugin = _serialize_plugin_row(get_plugin("notion"))
    return templates.TemplateResponse(
        "partials/notion_status.html",
        {
            "request": request,
            "plugin": plugin,
            "worker_running": _notion_worker.running,
            "status_message": _notion_status["message"],
        },
    )


@router.post("/api/plugins/notion/connect", response_class=HTMLResponse)
async def notion_connect(
    request: Request,
    token: str = Form(...),
    database: str = Form(...),
):
    error_message = None

    try:
        database_id, database_url = connect_to_notion(token, database)
        schema_ok, schema_error = validate_notion_schema(database_id)
        if not schema_ok:
            error_message = (
                schema_error
                or "Please align your Notion column headers with the inventory tracking table."
            )
        else:
            config = {
                "token": token,
                "database": database_url,
                "database_id": database_id,
            }
            upsert_plugin("notion", True, config)
            plugin = _serialize_plugin_row(get_plugin("notion"))
            _notion_status["state"] = "fetching"
            _notion_status["message"] = "Fetching database rows…"
            _start_notion_worker(plugin)
    except Exception:
        error_message = "Unable to connect. Please check your Notion credentials and try again."

    plugin = _serialize_plugin_row(get_plugin("notion"))

    return templates.TemplateResponse(
        "partials/notion_status.html",
        {
            "request": request,
            "plugin": plugin,
            "error_message": error_message,
            "worker_running": _notion_worker.running,
            "status_message": _notion_status["message"],
        },
    )


@router.post("/api/plugins/notion/toggle", response_class=HTMLResponse)
async def notion_toggle(request: Request, enabled: bool = Form(False)):
    update_plugin_enabled("notion", enabled)
    if enabled:
        plugin = _serialize_plugin_row(get_plugin("notion"))
        _start_notion_worker(plugin)
    else:
        _notion_worker.stop()
        _notion_status["state"] = "idle"
        _notion_status["message"] = "Notion sync paused."
    plugin = _serialize_plugin_row(get_plugin("notion"))
    return templates.TemplateResponse(
        "partials/notion_status.html",
        {
            "request": request,
            "plugin": plugin,
            "worker_running": _notion_worker.running,
            "status_message": _notion_status["message"],
        },
    )


@router.post("/api/plugins/notion/disconnect", response_class=HTMLResponse)
async def notion_disconnect(request: Request):
    _notion_worker.stop()
    update_plugin_config("notion", None)
    update_plugin_enabled("notion", False)
    delete_inventory_by_source("notion")
    _notion_status["state"] = "idle"
    _notion_status["message"] = "Notion disconnected."
    plugin = _serialize_plugin_row(get_plugin("notion"))
    return templates.TemplateResponse(
        "partials/notion_status.html",
        {
            "request": request,
            "plugin": plugin,
            "worker_running": _notion_worker.running,
            "status_message": _notion_status["message"],
        },
    )
