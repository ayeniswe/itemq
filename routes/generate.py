from pathlib import Path

from fastapi import APIRouter, Request
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


def _build_barcode_preview(items, quantities: dict[int, int], fallback_format: str):
    barcodes = []
    for item in items:
        label_format = item["label_format"] or fallback_format
        quantity = quantities.get(item["id"], item["label_quantity"] or 1)
        barcodes.append(
            {
                "id": item["id"],
                "name": item["name"],
                "barcode": item["barcode"],
                "source": item["source"],
                "format": label_format,
                "label_path": item["label_path"],
                "quantity": quantity,
            }
        )
    return barcodes


async def _parse_generation_form(request: Request) -> tuple[list[int], dict[int, int], str]:
    form = await request.form()
    item_ids = [int(value) for value in form.getlist("item_ids")]
    quantities = {}
    for item_id in item_ids:
        raw_value = form.get(f"quantity_{item_id}", "1")
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = 1
        quantities[item_id] = max(parsed, 1)
    normalized_format = normalize_format(form.get("format", "code128"))
    return item_ids, quantities, normalized_format


def _expand_barcodes_for_print(barcodes: list[dict]) -> list[dict]:
    expanded = []
    for barcode in barcodes:
        count = barcode.get("quantity", 1)
        for _ in range(max(count, 1)):
            expanded.append({**barcode, "quantity": 1})
    return expanded


@router.post("/generate/preview", response_class=HTMLResponse)
async def generate_preview(
    request: Request,
):
    item_ids, quantities, normalized_format = await _parse_generation_form(request)
    items = get_inventory_items_with_labels_by_ids(item_ids)
    barcodes = _build_barcode_preview(items, quantities, normalized_format)
    return templates.TemplateResponse(
        "partials/barcode_preview.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": _format_summary(barcodes),
            "selection_count": sum(quantities.values()),
        },
    )


@router.post("/generate/create", response_class=HTMLResponse)
async def generate_create(
    request: Request,
):
    item_ids, quantities, normalized_format = await _parse_generation_form(request)
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
                quantities.get(item["id"], 1),
            )
        )
    if entries:
        upsert_barcode_labels(entries)
    refreshed_items = get_inventory_items_with_labels_by_ids(item_ids)
    barcodes = _build_barcode_preview(refreshed_items, quantities, normalized_format)
    include_notion = _notion_enabled()
    inventory_items = list_inventory_with_labels(include_notion=include_notion)
    banner = None
    if item_ids:
        banner = {
            "title": "Labels generated",
            "subtitle": (
                f"Saved {sum(quantities.values())} label"
                f"{'' if sum(quantities.values()) == 1 else 's'} as {normalized_format.upper()}."
            ),
        }

    return templates.TemplateResponse(
        "partials/barcode_generate_response.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": _format_summary(barcodes),
            "selection_count": sum(quantities.values()),
            "items": inventory_items,
            "banner": banner,
        },
    )


@router.post("/generate/print", response_class=HTMLResponse)
async def generate_print(
    request: Request,
):
    item_ids, quantities, normalized_format = await _parse_generation_form(request)
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
    barcodes = _build_barcode_preview(items, quantities, normalized_format)
    print_barcodes = _expand_barcodes_for_print(barcodes)
    return templates.TemplateResponse(
        "partials/barcode_preview.html",
        {
            "request": request,
            "barcodes": print_barcodes,
            "selected_format": _format_summary(barcodes),
            "selection_count": sum(quantities.values()),
        },
    )
