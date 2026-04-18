from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import UploadFile, File
from pathlib import Path
from pydantic import BaseModel, Field, validator
from datetime import datetime, timedelta
import uuid
from typing import Literal
from PIL import Image
from io import BytesIO

from db import (
    add_inventory_item,
    list_inventory,
    count_inventory,
    get_inventory_totals,
    update_inventory_details,
    update_inventory_name,
    update_inventory_quantity,
    update_inventory_image,
    update_inventory_image_hash,
    update_inventory_notion_page_id,
    update_inventory_notion_sync_flags,
    update_inventory_notion_sync_status,
    delete_inventory_by_source,
    delete_inventory_item,
    get_inventory_item,
    get_inventory_item_by_barcode,
    get_inventory_items_by_ids,
    get_plugin,
    get_inventory_filter_options,
    add_history_entry,
    list_history,
    get_history_entry,
    mark_history_undone,
    update_inventory_full,
    mark_history_redone,
    latest_pending_history,
    latest_redo_candidate,
)
from model import InventoryItem, Plugin
from services.barcode import generate_barcode
from services.notion_worker import (
    InventoryBackupSyncWorker,
    InventoryBackupSyncSnapshot,
    schedule_local_inventory_item_sync,
    update_notion_quantity_by_barcode,
)
from config import MEDIA_ROOT

router = APIRouter()
templates = Jinja2Templates(directory="templates")
PAGE_SIZE = 25
_inventory_backup_sync_worker = InventoryBackupSyncWorker()

def _parse_history_row(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "action": row["action"],
        "summary": row["summary"],
        "before_state": row["before_state"],
        "after_state": row["after_state"],
        "created_at": row["created_at"],
        "undone_at": row["undone_at"],
    }


def _restore_item(state: dict) -> int:
    """Recreate an inventory item from stored state."""
    return add_inventory_item(
        name=state.get("name", "Restored Item"),
        barcode=state.get("barcode"),
        quantity=state.get("quantity", 0),
        image_path=state.get("image_path"),
        image_hash=state.get("image_hash"),
        group_name=state.get("group_name"),
        collection_name=state.get("collection_name"),
        collection_category=state.get("collection_category"),
        occasion=state.get("occasion"),
        season=state.get("season"),
        holiday=state.get("holiday"),
        emotion=state.get("emotion"),
        color=state.get("color"),
        event_name=state.get("event_name"),
        event_date=state.get("event_date"),
        event_location=state.get("event_location"),
        event_notes=state.get("event_notes"),
        notion_page_id=state.get("notion_page_id"),
        source=state.get("source", "local"),
    )


def _delete_by_state(state: dict) -> None:
    """Delete an item best-effort using id fallback to barcode."""
    target_id = state.get("id")
    if target_id and get_inventory_item(target_id):
        delete_inventory_item(target_id)
        return
    barcode = state.get("barcode")
    if barcode:
        item = get_inventory_item_by_barcode(barcode)
        if item:
            delete_inventory_item(item["id"])


def _apply_state(state: dict) -> None:
    """Apply a full state to the database, updating if present else restoring."""
    target_id = state.get("id")
    if target_id and get_inventory_item(target_id):
        update_inventory_full(target_id, state)
    else:
        _restore_item(state)


def _json_load(raw):
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        import json

        return json.loads(raw)
    except Exception:
        return None
_LAST_HISTORY_ID: int | None = None


def _build_filter_payload(
    search: str | None = None,
    search_case: str | None = None,
    image_status: str | None = None,
    group_name: str | None = None,
    collection_name: str | None = None,
    collection_category: str | None = None,
    occasion: str | None = None,
    season: str | None = None,
    holiday: str | None = None,
    emotion: str | None = None,
    color: str | None = None,
    event_name: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    tz_offset_minutes: int | str | None = None,
) -> dict[str, str | None]:
    def _normalize_datetime(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        normalized = normalized.replace("T", " ")
        if len(normalized) == 16:
            normalized = f"{normalized}:00"

        # Convert from user's local time to UTC using their offset (minutes to add to local to reach UTC)
        try:
            parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return normalized

        try:
            offset = int(tz_offset_minutes or 0)
        except Exception:
            offset = 0

        utc_value = parsed + timedelta(minutes=offset)
        return utc_value.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "search": search,
        "search_case": search_case or "insensitive",
        "image_status": (image_status or "").strip() or None,
        "group_name": group_name,
        "collection_name": collection_name,
        "collection_category": collection_category,
        "occasion": occasion,
        "season": season,
        "holiday": holiday,
        "emotion": emotion,
        "color": color,
        "event_name": event_name,
        "created_from": _normalize_datetime(created_from),
        "created_to": _normalize_datetime(created_to),
        "tz_offset_minutes": str(tz_offset_minutes) if tz_offset_minutes is not None else None,
    }


def _render_inventory_table(
    request: Request,
    include_notion: bool,
    filters: dict[str, str | None],
    page: int = 1,
):
    notion_plugin = Plugin.from_row(get_plugin("notion"))
    notion_plugin_active = bool(notion_plugin and notion_plugin.enabled and notion_plugin.config)
    bulk_sync_running = _inventory_backup_sync_worker.snapshot().state == "running"
    total = count_inventory(include_notion=include_notion, filters=filters)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = max(min(page, total_pages), 1)
    items = list_inventory(
        include_notion=include_notion,
        filters=filters,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
    )
    has_syncing_items = any(
        item["source"] == "local" and item["notion_sync_status"] == "syncing"
        for item in items
    )
    return templates.TemplateResponse(
        "partials/inventory_table.html",
        {
            "request": request,
            "items": items,
            "page": page,
            "total_pages": total_pages,
            "total_items": total,
            "page_size": PAGE_SIZE,
            "filters": filters,
            "notion_plugin_active": notion_plugin_active,
            "has_syncing_items": has_syncing_items,
            "bulk_sync_running": bulk_sync_running,
        },
    )


def _queue_local_item_notion_sync(item_id: int) -> None:
    plugin = Plugin.from_row(get_plugin("notion"))
    if not (plugin and plugin.enabled and plugin.config):
        return

    item = get_inventory_item(item_id)
    if item is None or item["source"] != "local":
        return

    schedule_local_inventory_item_sync(
        plugin.config["token"],
        plugin.config["database_id"],
        dict(item),
    )


class InventoryAdjustmentPayload(BaseModel):
    code: str = Field(..., min_length=1)
    direction: Literal["IN", "OUT"]
    quantity: int = Field(..., gt=0)
    timestamp: datetime
    redacted: bool

    @validator("direction", pre=True)
    def normalize_direction(cls, value: str) -> str:
        if isinstance(value, str):
            value = value.upper()
        return value


# -----------------------------
# READ: inventory table (HTMX)
# -----------------------------
@router.get("/inventory/table", response_class=HTMLResponse)
async def inventory_table(
    request: Request,
    include_notion: bool = False,
    page: int = 1,
    search: str | None = None,
    search_case: str | None = "insensitive",
    image_status: str | None = None,
    group_name: str | None = None,
    collection_name: str | None = None,
    collection_category: str | None = None,
    occasion: str | None = None,
    season: str | None = None,
    holiday: str | None = None,
    emotion: str | None = None,
    color: str | None = None,
    event_name: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    tz_offset_minutes: str | None = None,
):
    page = max(page, 1)
    filters = _build_filter_payload(
        search=search,
        search_case=search_case,
        image_status=image_status,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    return _render_inventory_table(request, include_notion, filters, page)


@router.get("/inventory/summary", response_class=HTMLResponse)
async def inventory_summary(
    request: Request,
    include_notion: bool = False,
):
    totals = get_inventory_totals(include_notion=include_notion)
    return templates.TemplateResponse(
        "partials/inventory_summary.html",
        {
            "request": request,
            "totals": totals,
        },
    )


@router.get("/inventory/filter_options")
async def inventory_filter_options(include_notion: bool = False):
    return get_inventory_filter_options(include_notion=include_notion)


@router.get("/inventory/duplicates", response_class=HTMLResponse)
async def inventory_duplicates(
    request: Request,
    include_notion: bool = False,
):
    items = list_inventory(
        include_notion=include_notion,
        filters={},
        limit=500,
        offset=0,
    )
    items_with_hash = [item for item in items if item["image_hash"]]
    items_with_name = [item for item in items if (item["name"] or "").strip()]

    exact_duplicates = {}
    for item in items_with_hash:
        exact_duplicates.setdefault(item["image_hash"], []).append(item)

    exact_groups = [
        group for group in exact_duplicates.values() if len(group) > 1
    ]

    similar_pairs = []
    for index, item in enumerate(items_with_hash):
        for other in items_with_hash[index + 1:]:
            distance = _hamming_distance(item["image_hash"], other["image_hash"])
            if 0 < distance <= 6:
                similar_pairs.append(
                    {
                        "left": item,
                        "right": other,
                        "distance": distance,
                    }
                )

    # Same-name groups (case-insensitive)
    name_duplicates: dict[str, list] = {}
    for item in items_with_name:
        key = (item["name"] or "").strip().lower()
        name_duplicates.setdefault(key, []).append(item)

    same_name_groups = [
        group for group in name_duplicates.values() if len(group) > 1
    ]

    return templates.TemplateResponse(
        "partials/inventory_duplicates.html",
        {
            "request": request,
            "exact_groups": exact_groups,
            "similar_pairs": similar_pairs,
            "same_name_groups": same_name_groups,
        },
    )


@router.delete("/inventory/notion")
async def delete_notion_inventory():
    delete_inventory_by_source("notion")
    return {"status": "ok"}


@router.delete("/inventory/{item_id}", response_class=HTMLResponse)
async def delete_inventory_item_row(
    request: Request,
    item_id: int,
    include_notion: bool = Form(False),
    search: str | None = Form(None),
    search_case: str | None = Form("insensitive"),
    image_status: str | None = Form(None),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    created_from: str | None = Form(None),
    created_to: str | None = Form(None),
    tz_offset_minutes: str | None = Form(None),
):
    item_row = get_inventory_item(item_id)
    if item_row is not None:
        add_history_entry(
            action="delete_single",
            summary=f"Deleted item '{item_row['name']}' (barcode {item_row['barcode']})",
            before_state=dict(item_row),
            after_state=None,
        )
        delete_inventory_item(item_id)
    filters = _build_filter_payload(
        search=search,
        search_case=search_case,
        image_status=image_status,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    response = _render_inventory_table(request, include_notion, filters, page=1)
    response.headers["HX-Trigger"] = "inventory:refreshHistory"
    return response


@router.post("/inventory/bulk_delete", response_class=HTMLResponse)
async def bulk_delete_inventory_items(
    request: Request,
    selected_ids: list[int] = Form(...),
    include_notion: bool = Form(False),
    page: int = Form(1),
    search: str | None = Form(None),
    search_case: str | None = Form("insensitive"),
    image_status: str | None = Form(None),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    created_from: str | None = Form(None),
    created_to: str | None = Form(None),
    tz_offset_minutes: str | None = Form(None),
):
    items = [dict(row) for row in get_inventory_items_by_ids(selected_ids)]
    for row in items:
        delete_inventory_item(row["id"])
    add_history_entry(
        action="delete_multi",
        summary=f"Deleted {len(items)} items",
        before_state=items,
        after_state=None,
    )
    filters = _build_filter_payload(
        search=search,
        search_case=search_case,
        image_status=image_status,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    response = _render_inventory_table(request, include_notion, filters, page=page)
    response.headers["HX-Trigger"] = "inventory:refreshHistory"
    return response


# -----------------------------
# CREATE: inventory item
# -----------------------------
@router.post("/inventory", response_class=HTMLResponse)
async def create_inventory_item(
    request: Request,
    include_notion: bool = Form(False),
    page: int = Form(1),
    filter_search: str | None = Form(None),
    filter_search_case: str | None = Form("insensitive"),
    filter_image_status: str | None = Form(None),
    filter_group_name: str | None = Form(None),
    filter_collection_name: str | None = Form(None),
    filter_collection_category: str | None = Form(None),
    filter_occasion: str | None = Form(None),
    filter_season: str | None = Form(None),
    filter_holiday: str | None = Form(None),
    filter_emotion: str | None = Form(None),
    filter_color: str | None = Form(None),
    filter_event_name: str | None = Form(None),
    filter_created_from: str | None = Form(None),
    filter_created_to: str | None = Form(None),
    filter_tz_offset_minutes: str | None = Form(None),
    name: str = Form(...),
    quantity: int = Form(0),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    event_date: str | None = Form(None),
    event_location: str | None = Form(None),
    event_notes: str | None = Form(None),
):
    barcode = generate_barcode()

    item_id = add_inventory_item(
        name=name,
        barcode=barcode,
        quantity=quantity,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        event_date=event_date,
        event_location=event_location,
        event_notes=event_notes,
    )

    add_history_entry(
        action="create",
        summary=f"Created item '{name}' (barcode {barcode})",
        before_state=None,
        after_state=dict(get_inventory_item(item_id)),
    )

    filters = _build_filter_payload(
        search=filter_search,
        search_case=filter_search_case,
        image_status=filter_image_status,
        group_name=filter_group_name,
        collection_name=filter_collection_name,
        collection_category=filter_collection_category,
        occasion=filter_occasion,
        season=filter_season,
        holiday=filter_holiday,
        emotion=filter_emotion,
        color=filter_color,
        event_name=filter_event_name,
        created_from=filter_created_from,
        created_to=filter_created_to,
        tz_offset_minutes=filter_tz_offset_minutes,
    )
    response = _render_inventory_table(request, include_notion, filters, page=page)
    response.headers["HX-Trigger"] = "inventory:refreshHistory"
    return response


# -----------------------------
# UPDATE: inventory name
# -----------------------------
@router.post("/inventory/{item_id}/name")
async def update_inventory_item_name(
    request: Request,
    item_id: int,
    name: str = Form(...),
):
    before = get_inventory_item(item_id)
    update_inventory_name(item_id, name)
    update_inventory_notion_sync_flags(
        item_id,
        notion_row_synced=False,
        notion_cover_synced=bool(before and before["notion_cover_synced"]),
    )
    update_inventory_notion_sync_status(item_id, "syncing")
    item = InventoryItem.from_row(get_inventory_item(item_id))
    _queue_local_item_notion_sync(item_id)
    add_history_entry(
        action="update_name",
        summary=f"Renamed item '{before['name']}' → '{name}'",
        before_state=dict(before) if before else None,
        after_state=dict(get_inventory_item(item_id)) if item else None,
    )
    response = templates.TemplateResponse(
        "partials/inventory_name.html",
        {
            "request": request,
            "item": item,
        },
    )
    # Refresh duplicate insights when a name change could create/remove same-name duplicates
    response.headers["HX-Trigger"] = "inventory:refreshDuplicates,inventory:refreshHistory"
    return response


# -----------------------------
# UPDATE: inventory quantity
# -----------------------------
@router.post("/inventory/{item_id}/quantity")
async def update_inventory_item_quantity(
    request: Request,
    item_id: int,
    quantity: int = Form(...),
):
    before = get_inventory_item(item_id)
    update_inventory_quantity(item_id, quantity)
    item = InventoryItem.from_row(get_inventory_item(item_id))
    add_history_entry(
        action="update_quantity",
        summary=f"Quantity for '{before['name'] if before else item.name}' set to {quantity}",
        before_state=dict(before) if before else None,
        after_state=dict(get_inventory_item(item_id)) if item else None,
    )
    response = templates.TemplateResponse(
        "partials/inventory_quantity.html",
        {
            "request": request,
            "item": item,
        },
    )
    response.headers["HX-Trigger"] = "inventory:refreshHistory"
    return response


# -----------------------------
# UPDATE: inventory image
# -----------------------------
@router.post("/inventory/{item_id}/image")
async def update_inventory_item_image(
    request: Request,
    item_id: int,
    file: UploadFile = File(...),
    include_notion: bool = Form(False),
    page: int = Form(1),
    search: str | None = Form(None),
    search_case: str | None = Form("insensitive"),
    image_status: str | None = Form(None),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    created_from: str | None = Form(None),
    created_to: str | None = Form(None),
    tz_offset_minutes: str | None = Form(None),
):
    image_dir = MEDIA_ROOT / "inventory"

    # Generate safe filename
    ext = Path(file.filename).suffix.lower()
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = image_dir / filename

    # Write file to disk
    with file_path.open("wb") as f:
        file_bytes = await file.read()
        f.write(file_bytes)

    # Persist relative path in DB
    before = get_inventory_item(item_id)
    update_inventory_image(
        item_id,
        f"inventory/{filename}",
    )
    update_inventory_notion_sync_flags(
        item_id,
        notion_row_synced=bool(before and before["notion_row_synced"]),
        notion_cover_synced=False,
    )
    update_inventory_notion_sync_status(item_id, "syncing")
    image_hash = _calculate_image_hash(file_bytes)
    if image_hash:
        update_inventory_image_hash(item_id, image_hash)
    _queue_local_item_notion_sync(item_id)

    add_history_entry(
        action="update_image",
        summary=f"Updated image for '{before['name'] if before else 'item'}'",
        before_state=dict(before) if before else None,
        after_state=dict(get_inventory_item(item_id)),
    )

    filters = _build_filter_payload(
        search=search,
        search_case=search_case,
        image_status=image_status,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    response = _render_inventory_table(request, include_notion, filters, page=page)
    response.headers["HX-Trigger"] = "inventory:refreshHistory"
    return response


@router.post("/inventory/{item_id}/details", response_class=HTMLResponse)
async def update_inventory_item_details(
    request: Request,
    item_id: int,
    include_notion: bool = Form(False),
    refresh_table: str | None = Form(None),
    refresh_row: str | None = Form(None),
    page: int = Form(1),
    search: str | None = Form(None),
    search_case: str | None = Form("insensitive"),
    image_status: str | None = Form(None),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    created_from: str | None = Form(None),
    created_to: str | None = Form(None),
    tz_offset_minutes: str | None = Form(None),
    event_date: str | None = Form(None),
    event_location: str | None = Form(None),
    event_notes: str | None = Form(None),
):
    before = get_inventory_item(item_id)
    update_inventory_details(
        item_id,
        group_name,
        collection_name,
        collection_category,
        occasion,
        season,
        holiday,
        emotion,
        color,
        event_name,
        event_date,
        event_location,
        event_notes,
    )
    item = InventoryItem.from_row(get_inventory_item(item_id))
    add_history_entry(
        action="update_details",
        summary=f"Updated details for '{before['name'] if before else item.name}'",
        before_state=dict(before) if before else None,
        after_state=dict(get_inventory_item(item_id)) if item else None,
    )
    if refresh_row:
        response = templates.TemplateResponse(
            "partials/inventory_rows.html",
            {"request": request, "items": [item]},
        )
        response.headers["HX-Trigger"] = "inventory:filtersUpdated,inventory:refreshTable,inventory:refreshHistory"
        return response
    if refresh_table:
        filters = _build_filter_payload(
            search=search,
            search_case=search_case,
            group_name=group_name,
            collection_name=collection_name,
            collection_category=collection_category,
            occasion=occasion,
            season=season,
            holiday=holiday,
            emotion=emotion,
            color=color,
            event_name=event_name,
            created_from=created_from,
            created_to=created_to,
            tz_offset_minutes=tz_offset_minutes,
        )
        response = _render_inventory_table(request, include_notion, filters, page=page)
        response.headers["HX-Trigger"] = "inventory:filtersUpdated,inventory:refreshHistory"
        return response
    response = templates.TemplateResponse(
        "partials/inventory_details.html",
        {
            "request": request,
            "item": item,
        },
    )
    response.headers["HX-Trigger"] = "inventory:filtersUpdated,inventory:refreshTable,inventory:refreshHistory"
    return response


@router.get("/inventory/{item_id}/details", response_class=HTMLResponse)
async def view_inventory_item_details(
    request: Request,
    item_id: int,
    view: str | None = None,
):
    item = InventoryItem.from_row(get_inventory_item(item_id))
    template = (
        "partials/inventory_details_modal.html"
        if view == "modal"
        else "partials/inventory_details.html"
    )
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "item": item,
        },
    )


@router.post("/inventory/undo_action", response_class=HTMLResponse)
async def undo_history_action(
    request: Request,
    history_id: int | None = Form(None),
    view: str | None = Form(None),
    include_notion: bool = Form(False),
    page: int = Form(1),
    search: str | None = Form(None),
    search_case: str | None = Form("insensitive"),
    image_status: str | None = Form(None),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    created_from: str | None = Form(None),
    created_to: str | None = Form(None),
    tz_offset_minutes: str | None = Form(None),
):
    # stack: latest pending action
    if history_id is not None:
        entry = get_history_entry(history_id)
    else:
        entry = latest_pending_history()
    if entry is None:
        raise HTTPException(status_code=404, detail="No history to undo.")
    if entry["undone_at"]:
        raise HTTPException(status_code=400, detail="Action already undone.")

    action = entry["action"]
    before_state = _json_load(entry["before_state"])
    after_state = _json_load(entry["after_state"])

    # Handle creation undo
    if action == "create" and after_state:
        target_id = after_state.get("id")
        if target_id:
            delete_inventory_item(target_id)
    # Handle deletes (single or multi): restore previous items
    elif action in {"delete_single", "delete_multi"} and before_state:
        items = before_state if isinstance(before_state, list) else [before_state]
        for item_state in items:
            _restore_item(item_state)
    # Handle generic updates (name, quantity, details, image)
    elif action.startswith("update_") and before_state:
        target_id = before_state.get("id")
        if target_id and get_inventory_item(target_id):
            update_inventory_full(target_id, before_state)
        else:
            _restore_item(before_state)
    else:
        raise HTTPException(status_code=400, detail="Unsupported action for undo.")

    mark_history_undone(entry["id"])

    if view == "history":
        history_rows = list_history(limit=200)
        return templates.TemplateResponse(
            "partials/history_list.html",
            {"request": request, "history": history_rows},
        )

    filters = _build_filter_payload(
        search=search,
        search_case=search_case,
        image_status=image_status,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    response = _render_inventory_table(request, include_notion, filters, page=page)
    response.headers["HX-Trigger"] = "inventory:refreshHistory,inventory:refreshTable"
    return response


@router.post("/inventory/redo_action", response_class=HTMLResponse)
async def redo_history_action(
    request: Request,
    history_id: int | None = Form(None),
    view: str | None = Form(None),
    include_notion: bool = Form(False),
    page: int = Form(1),
    search: str | None = Form(None),
    search_case: str | None = Form("insensitive"),
    image_status: str | None = Form(None),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    created_from: str | None = Form(None),
    created_to: str | None = Form(None),
    tz_offset_minutes: str | None = Form(None),
):
    # stack: latest undone entry
    if history_id is not None:
        entry = get_history_entry(history_id)
    else:
        entry = latest_redo_candidate()
    if entry is None or not entry["undone_at"]:
        raise HTTPException(status_code=404, detail="No action to redo.")

    action = entry["action"]
    before_state = _json_load(entry["before_state"])
    after_state = _json_load(entry["after_state"])

    # Reapply original action forward
    if action == "create":
        if after_state:
            _apply_state(after_state)
    elif action in {"delete_single", "delete_multi"}:
        items = before_state if isinstance(before_state, list) else [before_state]
        for item_state in items:
            _delete_by_state(item_state)
    elif action.startswith("update_"):
        if after_state:
            _apply_state(after_state)
    else:
        raise HTTPException(status_code=400, detail="Unsupported action for redo.")

    mark_history_redone(entry["id"])

    if view == "history":
        history_rows = list_history(limit=200)
        return templates.TemplateResponse(
            "partials/history_list.html",
            {"request": request, "history": history_rows},
        )

    filters = _build_filter_payload(
        search=search,
        search_case=search_case,
        image_status=image_status,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    response = _render_inventory_table(request, include_notion, filters, page=page)
    response.headers["HX-Trigger"] = "inventory:refreshHistory,inventory:refreshTable"
    return response


@router.get("/inventory/{item_id}/name/edit", response_class=HTMLResponse)
async def edit_inventory_name_cell(
    request: Request,
    item_id: int,
):
    item = InventoryItem.from_row(get_inventory_item(item_id))
    return templates.TemplateResponse(
        "partials/inventory_name_edit.html",
        {"request": request, "item": item},
    )


@router.get("/inventory/history", response_class=HTMLResponse)
async def inventory_history(request: Request, limit: int = 20):
    history_rows = list_history(limit=limit)
    return templates.TemplateResponse(
        "partials/inventory_history.html",
        {
            "request": request,
            "history": history_rows,
        },
    )


@router.get("/inventory/{item_id}/quantity/edit", response_class=HTMLResponse)
async def edit_inventory_quantity_cell(
    request: Request,
    item_id: int,
):
    item = InventoryItem.from_row(get_inventory_item(item_id))
    return templates.TemplateResponse(
        "partials/inventory_quantity_edit.html",
        {"request": request, "item": item},
    )


@router.get("/inventory/{item_id}/details/edit", response_class=HTMLResponse)
async def edit_inventory_details_cell(
    request: Request,
    item_id: int,
):
    item = InventoryItem.from_row(get_inventory_item(item_id))
    return templates.TemplateResponse(
        "partials/inventory_details_edit.html",
        {"request": request, "item": item},
    )


@router.post("/inventory/adjust")
async def adjust_inventory_by_barcode(payload: InventoryAdjustmentPayload):
    item_row = get_inventory_item_by_barcode(payload.code)
    if item_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No inventory item found for barcode '{payload.code}'.",
        )

    item = InventoryItem.from_row(item_row)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"No inventory item found for barcode '{payload.code}'.",
        )

    delta = payload.quantity if payload.direction == "IN" else -payload.quantity
    new_quantity = item.quantity + delta
    if item.source == "notion":
        plugin_row = get_plugin("notion")
        if plugin_row is None:
            raise HTTPException(
                status_code=400,
                detail="Notion is not connected for this inventory item.",
            )
        plugin_config = Plugin.from_row(plugin_row)
        if plugin_config is None or not plugin_config.config:
            raise HTTPException(
                status_code=400,
                detail="Notion is not connected for this inventory item.",
            )

        updated_rows = update_notion_quantity_by_barcode(
            plugin_config.config["token"],
            plugin_config.config["database_id"],
            item.barcode,
            new_quantity,
        )
        if updated_rows == 0:
            raise HTTPException(
                status_code=404,
                detail="No matching Notion row found for this barcode.",
            )

    update_inventory_quantity(item.id, new_quantity)

    return {
        "status": "ok",
        "item_id": item.id,
        "barcode": item.barcode,
        "previous_quantity": item.quantity,
        "new_quantity": new_quantity,
        "direction": payload.direction,
        "timestamp": payload.timestamp.isoformat(),
        "redacted": payload.redacted,
    }


def _render_inventory_sync_status(
    request: Request,
    snapshot: InventoryBackupSyncSnapshot | None = None,
) -> HTMLResponse:
    snapshot = snapshot or _inventory_backup_sync_worker.snapshot()
    tone = "idle"
    if snapshot.state == "running":
        tone = "running"
    elif snapshot.state == "canceling":
        tone = "warning"
    elif snapshot.state == "canceled":
        tone = "warning"
    elif snapshot.state == "failed":
        tone = "failed"
    elif snapshot.failed_rows or snapshot.failed_images:
        tone = "warning"
    elif snapshot.state == "completed":
        tone = "success"

    return templates.TemplateResponse(
        "partials/inventory_notion_sync_status.html",
        {
            "request": request,
            "sync_status": snapshot,
            "sync_tone": tone,
        },
    )


@router.get("/inventory/sync_to_notion/status", response_class=HTMLResponse)
async def inventory_sync_to_notion_status(request: Request):
    return _render_inventory_sync_status(request)


@router.post("/inventory/sync_to_notion", response_class=HTMLResponse)
async def sync_inventory_to_notion(request: Request):
    plugin = Plugin.from_row(get_plugin("notion"))
    if not (plugin and plugin.enabled and plugin.config):
        return _render_inventory_sync_status(
            request,
            InventoryBackupSyncSnapshot(
                state="failed",
                message="Connect Notion before syncing.",
                detail="The backup sync needs an active Notion connection.",
            ),
        )

    total_local_items = count_inventory(include_notion=False)
    all_local_rows = list_inventory(
        include_notion=False,
        filters={},
        limit=max(total_local_items, 1),
        offset=0,
    )
    local_rows = [
        dict(row)
        for row in all_local_rows
        if not (row["notion_row_synced"] and row["notion_cover_synced"])
    ]
    _inventory_backup_sync_worker.start(
        plugin.config["token"],
        plugin.config["database_id"],
        local_rows,
    )
    response = _render_inventory_sync_status(request)
    response.headers["HX-Trigger"] = "inventory:refreshTable"
    return response


@router.post("/inventory/sync_to_notion/cancel", response_class=HTMLResponse)
async def cancel_inventory_sync_to_notion(request: Request):
    _inventory_backup_sync_worker.stop()
    response = _render_inventory_sync_status(request)
    response.headers["HX-Trigger"] = "inventory:refreshTable"
    return response


@router.post("/inventory/sync_to_notion/dismiss", response_class=HTMLResponse)
async def dismiss_inventory_sync_to_notion(request: Request):
    _inventory_backup_sync_worker.dismiss()
    return _render_inventory_sync_status(request)


@router.post("/inventory/{item_id}/sync_to_notion", response_class=HTMLResponse)
async def sync_inventory_row_to_notion(
    request: Request,
    item_id: int,
    include_notion: bool = Form(False),
    page: int = Form(1),
    search: str | None = Form(None),
    search_case: str | None = Form("insensitive"),
    image_status: str | None = Form(None),
    group_name: str | None = Form(None),
    collection_name: str | None = Form(None),
    collection_category: str | None = Form(None),
    occasion: str | None = Form(None),
    season: str | None = Form(None),
    holiday: str | None = Form(None),
    emotion: str | None = Form(None),
    color: str | None = Form(None),
    event_name: str | None = Form(None),
    created_from: str | None = Form(None),
    created_to: str | None = Form(None),
    tz_offset_minutes: str | None = Form(None),
):
    item = get_inventory_item(item_id)
    if item and item["source"] == "local":
        update_inventory_notion_sync_flags(
            item_id,
            notion_row_synced=False,
            notion_cover_synced=False,
        )
        update_inventory_notion_sync_status(item_id, "syncing")
        _queue_local_item_notion_sync(item_id)

    filters = _build_filter_payload(
        search=search,
        search_case=search_case,
        image_status=image_status,
        group_name=group_name,
        collection_name=collection_name,
        collection_category=collection_category,
        occasion=occasion,
        season=season,
        holiday=holiday,
        emotion=emotion,
        color=color,
        event_name=event_name,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    response = _render_inventory_table(request, include_notion, filters, page=page)
    response.headers["HX-Trigger"] = "inventory:refreshHistory"
    return response


def _calculate_image_hash(file_bytes: bytes) -> str | None:
    try:
        image = Image.open(BytesIO(file_bytes)).convert("L").resize((8, 8))
        pixels = list(image.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if pixel >= avg else "0" for pixel in pixels)
        return f"{int(bits, 2):016x}"
    except Exception:
        return None


def _hamming_distance(left: str, right: str) -> int:
    try:
        left_bits = bin(int(left, 16))[2:].zfill(64)
        right_bits = bin(int(right, 16))[2:].zfill(64)
    except ValueError:
        return 64
    return sum(l != r for l, r in zip(left_bits, right_bits))
