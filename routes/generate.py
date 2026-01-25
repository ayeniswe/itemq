from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db import (
    get_inventory_items_with_labels_by_ids,
    get_plugin,
    list_inventory_with_labels,
    upsert_barcode_labels,
)
from model import Plugin
from services.barcode_rendering import (
    SUPPORTED_FORMATS,
    normalize_format,
    save_barcode_image,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _notion_enabled() -> bool:
    plugin = Plugin.from_row(get_plugin("notion"))
    return bool(plugin and plugin.enabled)


@router.get("/generate", response_class=HTMLResponse)
async def generate(request: Request):
    include_notion = _notion_enabled()
    items = list_inventory_with_labels(include_notion=include_notion)
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


def _format_summary(barcodes: list[dict]) -> str:
    formats = {barcode["format"] for barcode in barcodes if barcode.get("format")}
    if not formats:
        return normalize_format(None).upper()
    if len(formats) == 1:
        return next(iter(formats)).upper()
    return "MULTIPLE"


def _build_barcode_preview(items, fallback_format: str):
    barcodes = []
    for item in items:
        label_format = item["label_format"] or fallback_format
        barcodes.append(
            {
                "id": item["id"],
                "name": item["name"],
                "barcode": item["barcode"],
                "source": item["source"],
                "format": label_format,
                "label_path": item["label_path"],
            }
        )
    return barcodes


@router.post("/generate/preview", response_class=HTMLResponse)
async def generate_preview(
    request: Request,
    item_ids: list[int] = Form([]),
    format: str = Form("code128"),
):
    normalized_format = normalize_format(format)
    items = get_inventory_items_with_labels_by_ids(item_ids)
    barcodes = _build_barcode_preview(items, normalized_format)
    return templates.TemplateResponse(
        "partials/barcode_preview.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": _format_summary(barcodes),
            "selection_count": len(item_ids),
        },
    )


@router.post("/generate/create", response_class=HTMLResponse)
async def generate_create(
    request: Request,
    item_ids: list[int] = Form([]),
    format: str = Form("code128"),
):
    normalized_format = normalize_format(format)
    items = get_inventory_items_with_labels_by_ids(item_ids)
    output_dir = Path("data/media/barcodes")
    entries = []
    for item in items:
        filename = save_barcode_image(item["barcode"], normalized_format, output_dir)
        entries.append(
            (
                item["id"],
                item["barcode"],
                normalized_format,
                f"barcodes/{filename}",
            )
        )
    if entries:
        upsert_barcode_labels(entries)
    refreshed_items = get_inventory_items_with_labels_by_ids(item_ids)
    barcodes = _build_barcode_preview(refreshed_items, normalized_format)
    include_notion = _notion_enabled()
    inventory_items = list_inventory_with_labels(include_notion=include_notion)
    banner = None
    if item_ids:
        banner = {
            "title": "Labels generated",
            "subtitle": (
                f"Saved {len(item_ids)} label"
                f"{'' if len(item_ids) == 1 else 's'} as {normalized_format.upper()}."
            ),
        }

    return templates.TemplateResponse(
        "partials/barcode_generate_response.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": _format_summary(barcodes),
            "selection_count": len(item_ids),
            "items": inventory_items,
            "banner": banner,
        },
    )


@router.post("/generate/print", response_class=HTMLResponse)
async def generate_print(
    request: Request,
    item_ids: list[int] = Form([]),
    format: str = Form("code128"),
):
    normalized_format = normalize_format(format)
    items = get_inventory_items_with_labels_by_ids(item_ids)
    missing = [item for item in items if not item["label_path"]]
    if missing:
        return templates.TemplateResponse(
            "partials/barcode_print_error.html",
            {
                "request": request,
                "message": "Generate labels for the selected items, then try printing again.",
            },
            status_code=400,
        )
    barcodes = _build_barcode_preview(items, normalized_format)
    return templates.TemplateResponse(
        "partials/barcode_preview.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": _format_summary(barcodes),
            "selection_count": len(item_ids),
        },
    )
