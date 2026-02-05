from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import UploadFile, File
from pathlib import Path
from pydantic import BaseModel, Field, validator
from datetime import datetime
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
    delete_inventory_by_source,
    delete_inventory_item,
    get_inventory_item,
    get_inventory_item_by_barcode,
    get_plugin,
    get_inventory_filter_options,
)
from model import InventoryItem, Plugin
from services.barcode import generate_barcode
from services.notion_worker import (
    update_notion_quantity_by_barcode,
    upsert_notion_inventory_item,
    update_notion_inventory_image,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
PAGE_SIZE = 25

_LAST_DELETED: dict | None = None


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
    group_name: str | None = None,
    collection_name: str | None = None,
    collection_category: str | None = None,
    occasion: str | None = None,
    season: str | None = None,
    holiday: str | None = None,
    emotion: str | None = None,
    color: str | None = None,
    event_name: str | None = None,
):
    page = max(page, 1)
    filters = {
        "search": search,
        "group_name": group_name,
        "collection_name": collection_name,
        "collection_category": collection_category,
        "occasion": occasion,
        "season": season,
        "holiday": holiday,
        "emotion": emotion,
        "color": color,
        "event_name": event_name,
    }
    items = list_inventory(
        include_notion=include_notion,
        filters=filters,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
    )
    total = count_inventory(include_notion=include_notion, filters=filters)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
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
        },
    )


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

    return templates.TemplateResponse(
        "partials/inventory_duplicates.html",
        {
            "request": request,
            "exact_groups": exact_groups,
            "similar_pairs": similar_pairs,
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
):
    global _LAST_DELETED
    item_row = get_inventory_item(item_id)
    if item_row is not None:
        _LAST_DELETED = dict(item_row)
    delete_inventory_item(item_id)
    filters = {}
    total = count_inventory(include_notion=include_notion, filters=filters)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    items = list_inventory(
        include_notion=include_notion,
        filters=filters,
        limit=PAGE_SIZE,
        offset=0,
    )
    response = templates.TemplateResponse(
        "partials/inventory_table.html",
        {
            "request": request,
            "items": items,
            "page": 1,
            "total_pages": total_pages,
            "total_items": total,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )
    if _LAST_DELETED:
        response.headers["HX-Trigger"] = "inventory:undoAvailable"
    return response


# -----------------------------
# CREATE: inventory item
# -----------------------------
@router.post("/inventory", response_class=HTMLResponse)
async def create_inventory_item(
    request: Request,
    include_notion: bool = Form(False),
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

    _sync_local_item_to_notion(request, item_id)

    # Re-render table after insert
    filters = {}
    total = count_inventory(include_notion=include_notion, filters=filters)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    items = list_inventory(
        include_notion=include_notion,
        filters=filters,
        limit=PAGE_SIZE,
        offset=0,
    )
    return templates.TemplateResponse(
        "partials/inventory_table.html",
        {
            "request": request,
            "items": items,
            "page": 1,
            "total_pages": total_pages,
            "total_items": total,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )


# -----------------------------
# UPDATE: inventory name
# -----------------------------
@router.post("/inventory/{item_id}/name")
async def update_inventory_item_name(
    request: Request,
    item_id: int,
    name: str = Form(...),
):
    update_inventory_name(item_id, name)
    _sync_local_item_to_notion(request, item_id)
    item = InventoryItem.from_row(get_inventory_item(item_id))
    return templates.TemplateResponse(
        "partials/inventory_name.html",
        {
            "request": request,
            "item": item,
        },
    )


# -----------------------------
# UPDATE: inventory quantity
# -----------------------------
@router.post("/inventory/{item_id}/quantity")
async def update_inventory_item_quantity(
    request: Request,
    item_id: int,
    quantity: int = Form(...),
):
    update_inventory_quantity(item_id, quantity)
    _sync_local_item_to_notion(request, item_id)
    item = InventoryItem.from_row(get_inventory_item(item_id))
    return templates.TemplateResponse(
        "partials/inventory_quantity.html",
        {
            "request": request,
            "item": item,
        },
    )


# -----------------------------
# UPDATE: inventory image
# -----------------------------
@router.post("/inventory/{item_id}/image")
async def update_inventory_item_image(
    request: Request,
    item_id: int,
    file: UploadFile = File(...),
    include_notion: bool = Form(False),
):
    # Ensure image directory exists
    image_dir = Path("data/media/inventory")
    image_dir.mkdir(parents=True, exist_ok=True)

    # Generate safe filename
    ext = Path(file.filename).suffix.lower()
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = image_dir / filename

    # Write file to disk
    with file_path.open("wb") as f:
        file_bytes = await file.read()
        f.write(file_bytes)

    # Persist relative path in DB
    update_inventory_image(
        item_id,
        f"inventory/{filename}",
    )
    image_hash = _calculate_image_hash(file_bytes)
    if image_hash:
        update_inventory_image_hash(item_id, image_hash)

    _sync_inventory_image_to_notion(request, item_id, f"inventory/{filename}")

    filters = {}
    total = count_inventory(include_notion=include_notion, filters=filters)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    items = list_inventory(
        include_notion=include_notion,
        filters=filters,
        limit=PAGE_SIZE,
        offset=0,
    )
    return templates.TemplateResponse(
        "partials/inventory_table.html",
        {
            "request": request,
            "items": items,
            "page": 1,
            "total_pages": total_pages,
            "total_items": total,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )


@router.post("/inventory/{item_id}/details", response_class=HTMLResponse)
async def update_inventory_item_details(
    request: Request,
    item_id: int,
    include_notion: bool = Form(False),
    refresh_table: str | None = Form(None),
    refresh_row: str | None = Form(None),
    page: int = Form(1),
    search: str | None = Form(None),
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
    _sync_local_item_to_notion(request, item_id)
    item = InventoryItem.from_row(get_inventory_item(item_id))
    if refresh_row:
        response = templates.TemplateResponse(
            "partials/inventory_rows.html",
            {"request": request, "items": [item]},
        )
        response.headers["HX-Trigger"] = "inventory:filtersUpdated,inventory:refreshTable"
        return response
    if refresh_table:
        filters = {
            "search": search,
            "group_name": group_name,
            "collection_name": collection_name,
            "collection_category": collection_category,
            "occasion": occasion,
            "season": season,
            "holiday": holiday,
            "emotion": emotion,
            "color": color,
            "event_name": event_name,
        }
        total = count_inventory(include_notion=include_notion, filters=filters)
        total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        page = max(min(page, total_pages), 1)
        items = list_inventory(
            include_notion=include_notion,
            filters=filters,
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
        )
        response = templates.TemplateResponse(
            "partials/inventory_table.html",
            {
                "request": request,
                "items": items,
                "page": page,
                "total_pages": total_pages,
                "total_items": total,
                "page_size": PAGE_SIZE,
                "filters": filters,
            },
        )
        response.headers["HX-Trigger"] = "inventory:filtersUpdated"
        return response
    response = templates.TemplateResponse(
        "partials/inventory_details.html",
        {
            "request": request,
            "item": item,
        },
    )
    response.headers["HX-Trigger"] = "inventory:filtersUpdated,inventory:refreshTable"
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


@router.post("/inventory/undo", response_class=HTMLResponse)
async def undo_inventory_delete(
    request: Request,
    include_notion: bool = Form(False),
):
    global _LAST_DELETED
    if _LAST_DELETED:
        add_inventory_item(
            name=_LAST_DELETED["name"],
            barcode=_LAST_DELETED["barcode"],
            quantity=_LAST_DELETED["quantity"],
            image_path=_LAST_DELETED["image_path"],
            image_hash=_LAST_DELETED["image_hash"],
            group_name=_LAST_DELETED["group_name"],
            collection_name=_LAST_DELETED["collection_name"],
            collection_category=_LAST_DELETED["collection_category"],
            occasion=_LAST_DELETED["occasion"],
            season=_LAST_DELETED["season"],
            holiday=_LAST_DELETED["holiday"],
            emotion=_LAST_DELETED["emotion"],
            color=_LAST_DELETED["color"],
            event_name=_LAST_DELETED["event_name"],
            event_date=_LAST_DELETED["event_date"],
            event_location=_LAST_DELETED["event_location"],
            event_notes=_LAST_DELETED["event_notes"],
            notion_page_id=_LAST_DELETED["notion_page_id"],
            source=_LAST_DELETED["source"],
        )
        _LAST_DELETED = None

    filters = {}
    total = count_inventory(include_notion=include_notion, filters=filters)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    items = list_inventory(
        include_notion=include_notion,
        filters=filters,
        limit=PAGE_SIZE,
        offset=0,
    )
    return templates.TemplateResponse(
        "partials/inventory_table.html",
        {
            "request": request,
            "items": items,
            "page": 1,
            "total_pages": total_pages,
            "total_items": total,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )


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


def _sync_local_item_to_notion(request: Request, item_id: int) -> None:
    plugin_row = get_plugin("notion")
    plugin = Plugin.from_row(plugin_row)
    if not plugin or not plugin.enabled or not plugin.config:
        return
    item_row = get_inventory_item(item_id)
    if not item_row or item_row["source"] != "local":
        return
    upsert_notion_inventory_item(
        plugin.config["token"],
        plugin.config["database_id"],
        dict(item_row),
    )


def _sync_inventory_image_to_notion(
    request: Request,
    item_id: int,
    image_path: str,
) -> None:
    plugin_row = get_plugin("notion")
    plugin = Plugin.from_row(plugin_row)
    if not plugin or not plugin.enabled or not plugin.config:
        return
    base_url = str(request.base_url).rstrip("/")
    image_url = f"{base_url}/media/{image_path}"
    item_row = get_inventory_item(item_id)
    if not item_row or item_row["source"] != "local":
        return
    update_notion_inventory_image(
        plugin.config["token"],
        plugin.config["database_id"],
        image_url,
        barcode=item_row["barcode"],
    )
