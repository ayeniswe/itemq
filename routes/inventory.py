from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import UploadFile, File
from pathlib import Path
import uuid

from db import (
    add_inventory_item,
    list_inventory,
    update_inventory_name,
    update_inventory_quantity,
    update_inventory_image,
    delete_inventory_by_source,
    delete_inventory_item,
    get_inventory_item,
)
from model import InventoryItem
from services.barcode import generate_barcode

router = APIRouter()
templates = Jinja2Templates(directory="templates")


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
    image_dir = Path("data/media/inventory")
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
