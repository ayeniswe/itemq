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
)
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


# -----------------------------
# CREATE: inventory item
# -----------------------------
@router.post("/inventory", response_class=HTMLResponse)
async def create_inventory_item(
    request: Request,
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
    items = list_inventory()
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
    item_id: int,
    name: str = Form(...),
):
    update_inventory_name(item_id, name)
    return ""


# -----------------------------
# UPDATE: inventory quantity
# -----------------------------
@router.post("/inventory/{item_id}/quantity")
async def update_inventory_item_quantity(
    item_id: int,
    quantity: int = Form(...),
):
    update_inventory_quantity(item_id, quantity)
    return ""


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
