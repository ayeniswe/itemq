from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import UploadFile, File
from pathlib import Path
from pydantic import BaseModel, Field, validator
from datetime import datetime
import uuid
from typing import Literal

from db import (
    add_inventory_item,
    list_inventory,
    update_inventory_name,
    update_inventory_quantity,
    update_inventory_image,
    delete_inventory_by_source,
    delete_inventory_item,
    get_inventory_item,
    get_inventory_item_by_barcode,
)
from model import InventoryItem
from services.barcode import generate_barcode

router = APIRouter()
templates = Jinja2Templates(directory="templates")


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
):
    items = list_inventory(include_notion=include_notion)
    return templates.TemplateResponse(
        "partials/inventory_rows.html",
        {
            "request": request,
            "items": items,
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
    delete_inventory_item(item_id)
    items = list_inventory(include_notion=include_notion)
    return templates.TemplateResponse(
        "partials/inventory_rows.html",
        {
            "request": request,
            "items": items,
        },
    )


# -----------------------------
# CREATE: inventory item
# -----------------------------
@router.post("/inventory", response_class=HTMLResponse)
async def create_inventory_item(
    request: Request,
    include_notion: bool = Form(False),
    name: str = Form(...),
    quantity: int = Form(1),
):
    barcode = generate_barcode()

    add_inventory_item(
        name=name,
        barcode=barcode,
        quantity=quantity,
    )

    # Re-render table after insert
    items = list_inventory(include_notion)
    return templates.TemplateResponse(
        "partials/inventory_rows.html",
        {
            "request": request,
            "items": items,
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
    image_dir = Path("data/images/inventory")
    image_dir.mkdir(parents=True, exist_ok=True)

    # Generate safe filename
    ext = Path(file.filename).suffix.lower()
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = image_dir / filename

    # Write file to disk
    with file_path.open("wb") as f:
        f.write(await file.read())

    # Persist relative path in DB
    update_inventory_image(
        item_id,
        f"inventory/{filename}",
    )

    items = list_inventory(include_notion=include_notion)
    return templates.TemplateResponse(
        "partials/inventory_rows.html",
        {
            "request": request,
            "items": items,
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
