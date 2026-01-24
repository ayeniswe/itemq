from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db import (
    add_barcode_generations,
    get_inventory_items_by_ids,
    get_plugin,
    list_inventory,
)
from model import Plugin
from services.barcode_rendering import (
    SUPPORTED_FORMATS,
    normalize_format,
    render_barcode_svg,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _notion_enabled() -> bool:
    plugin = Plugin.from_row(get_plugin("notion"))
    return bool(plugin and plugin.enabled)


@router.get("/generate", response_class=HTMLResponse)
async def generate(request: Request):
    include_notion = _notion_enabled()
    items = list_inventory(include_notion=include_notion)
    return templates.TemplateResponse(
        "generate.html",
        {
            "request": request,
            "items": items,
            "formats": list(SUPPORTED_FORMATS.values()),
            "selected_format": normalize_format(None),
            "notion_enabled": include_notion,
            "barcodes": [],
        },
    )


@router.post("/generate/preview", response_class=HTMLResponse)
async def generate_preview(
    request: Request,
    item_ids: list[int] = Form([]),
    format: str = Form("code128"),
):
    normalized_format = normalize_format(format)
    items = get_inventory_items_by_ids(item_ids)
    barcodes = [
        {
            "id": item["id"],
            "name": item["name"],
            "barcode": item["barcode"],
            "source": item["source"],
            "format": normalized_format,
            "svg": render_barcode_svg(item["barcode"], normalized_format),
        }
        for item in items
    ]
    return templates.TemplateResponse(
        "partials/barcode_preview.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": normalized_format,
            "selection_count": len(item_ids),
        },
    )


@router.post("/generate/confirm", response_class=HTMLResponse)
async def generate_confirm(
    request: Request,
    item_ids: list[int] = Form([]),
    format: str = Form("code128"),
):
    normalized_format = normalize_format(format)
    items = get_inventory_items_by_ids(item_ids)
    barcodes = [
        {
            "id": item["id"],
            "name": item["name"],
            "barcode": item["barcode"],
            "source": item["source"],
            "format": normalized_format,
            "svg": render_barcode_svg(item["barcode"], normalized_format),
        }
        for item in items
    ]
    entries = [
        (item["id"], item["barcode"], normalized_format, "generated")
        for item in items
    ]
    if entries:
        add_barcode_generations(entries)

    return templates.TemplateResponse(
        "partials/barcode_confirm.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": normalized_format,
            "selection_count": len(item_ids),
        },
    )
