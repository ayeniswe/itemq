from __future__ import annotations

import json
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import notion_client

from db import (
    get_plugin,
    upsert_plugin,
    update_plugin_enabled,
    update_plugin_config,
    delete_inventory_by_source,
    add_inventory_item,
)
from model import Plugin
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
        errored = False
        try:
            for row in fetch_database_rows(plugin["config"]["token"], plugin["config"]["database_id"]):
                if stop_event.is_set():
                    break

                add_inventory_item(**row, source="notion")
        except Exception:
            errored = True
        finally:
            if stop_event.is_set():
                if _notion_status["state"] != "disconnected":
                    _notion_status["message"] = "Sync canceled."
                _notion_status["state"] = "idle"
            elif errored:
                if _notion_status["state"] != "disconnected":
                    _notion_status["message"] = (
                        "Sync failed. Internal Error"
                    )
                _notion_status["state"] = "idle"
            else:
                _notion_status["state"] = "idle"
                _notion_status["message"] = (
                    "All set! Your Notion inventory is up to date."
                )

    _notion_worker.start(worker_task)
    
@router.get("/plugins/notion/status", response_class=HTMLResponse)
async def notion_status(request: Request):
    plugin = Plugin.from_row(get_plugin("notion"))
    
    if _notion_status["state"] in {"idle", "disconnected"}:
        _notion_worker.stop()

    return templates.TemplateResponse(
        "partials/notion_status.html",
        {
            "request": request,
            "plugin": plugin,
            "worker_running": _notion_worker.running,
            "status_message": _notion_status["message"],
        },
    )


@router.post("/plugins/notion/connect", response_class=HTMLResponse)
async def notion_connect(
    request: Request,
    token: str = Form(...),
    database_url: str = Form(...),
):
    error_message = None

    try:
        database_id, db_name = connect_to_notion(token, database_url)
        schema_ok, schema_error = validate_notion_schema(database_id)
        if not schema_ok:
            error_message = (
                schema_error
                or "Please align your Notion column headers with the inventory tracking table."
            )
        else:
            config = {
                "token": token,
                "database_name": db_name,
                "database_url": database_url,
                "database_id": database_id,
            }
            upsert_plugin("notion", True, config)
            plugin = _serialize_plugin_row(get_plugin("notion"))
            _notion_status["state"] = "fetching"
            _notion_status["message"] = "Syncing Notion inventory…"
            _start_notion_worker(plugin)
    except notion_client.APIResponseError as e:
        error = str(e)
        if "API token" in error:
            error_message = error.replace("API", "Notion")
        elif "valid uuid" in error:
            error_message = "Database link is invalid"
        else:
            error_message = "Unknown error"
    except Exception:
        error_message = "Unknown error"

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


@router.post("/plugins/notion/sync", response_class=HTMLResponse)
async def notion_sync(request: Request):
    plugin = _serialize_plugin_row(get_plugin("notion"))
    if not plugin or not plugin.get("config"):
        _notion_status["state"] = "idle"
        _notion_status["message"] = "Connect Notion to start syncing."
    elif _notion_worker.running:
        _notion_status["state"] = "fetching"
        _notion_status["message"] = "Sync already in progress…"
    else:
        _notion_status["state"] = "fetching"
        _notion_status["message"] = "Syncing Notion inventory…"
        _start_notion_worker(plugin)
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


@router.post("/plugins/notion/disconnect", response_class=HTMLResponse)
async def notion_disconnect(request: Request):
    _notion_worker.stop()
    update_plugin_config("notion", None)
    update_plugin_enabled("notion", False)
    delete_inventory_by_source("notion")
    _notion_status["state"] = "disconnected"
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
