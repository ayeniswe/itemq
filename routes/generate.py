from io import BytesIO

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from db import (
    get_inventory_items_with_labels_by_ids,
    get_plugin,
    list_inventory_with_labels_paginated,
    count_inventory_with_labels,
    get_inventory_filter_options,
    upsert_barcode_labels,
)
from model import Plugin
from services.barcode_rendering import (
    SUPPORTED_FORMATS,
    normalize_format,
    save_barcode_image,
)
from services.barcode_pdf import BarcodeSheetPDF
from config import MEDIA_ROOT

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _notion_enabled() -> bool:
    plugin = Plugin.from_row(get_plugin("notion"))
    return bool(plugin and plugin.enabled)


@router.get("/generate", response_class=HTMLResponse)
async def generate(request: Request):
    include_notion = _notion_enabled()
    filters = {}
    items = list_inventory_with_labels_paginated(
        include_notion=include_notion,
        filters=filters,
        limit=25,
        offset=0,
    )
    total = count_inventory_with_labels(include_notion=include_notion, filters=filters)
    filter_options = get_inventory_filter_options(include_notion=include_notion)
    return templates.TemplateResponse(
        "generate.html",
        {
            "request": request,
            "items": items,
            "formats": list(SUPPORTED_FORMATS.values()),
            "selected_format": normalize_format(None),
            "notion_enabled": include_notion,
            "barcodes": [],
            "filters": filters,
            "filter_options": filter_options,
            "page": 1,
            "total_pages": max((total + 24) // 25, 1),
            "total_items": total,
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
        quantity = quantities.get(item["id"], item["label_quantity"] or 0)
        barcodes.append(
            {
                "id": item["id"],
                "name": item["name"],
                "barcode": item["barcode"],
                "source": item["source"],
                "format": label_format,
                "label_path": item["label_path"],
                "quantity": quantity,
                "image_path": item["image_path"],
                "group_name": item["group_name"],
                "collection_name": item["collection_name"],
                "collection_category": item["collection_category"],
                "occasion": item["occasion"],
                "season": item["season"],
                "holiday": item["holiday"],
                "emotion": item["emotion"],
                "color": item["color"],
                "event_name": item["event_name"],
            }
        )
    return barcodes


async def _parse_generation_form(request: Request) -> tuple[list[int], dict[int, int], str]:
    form = await request.form()
    item_ids = [int(value) for value in form.getlist("item_ids")]
    quantities = {}
    for item_id in item_ids:
        raw_value = form.get(f"quantity_{item_id}", "0")
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = 0
        quantities[item_id] = max(parsed, 0)
    normalized_format = normalize_format(form.get("format", "code128"))
    return item_ids, quantities, normalized_format


def _expand_barcodes_for_print(barcodes: list[dict]) -> list[dict]:
    expanded = []
    for barcode in sorted(barcodes, key=lambda entry: entry.get("barcode", "").casefold()):
        count = barcode.get("quantity", 1)
        if count <= 0:
            continue
        for _ in range(count):
            expanded.append({**barcode, "quantity": 1})
    return expanded


@router.get("/generate/inventory_list", response_class=HTMLResponse)
async def generate_inventory_list(
    request: Request,
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
    page: int = 1,
):
    include_notion = _notion_enabled()
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
    items = list_inventory_with_labels_paginated(
        include_notion=include_notion,
        filters=filters,
        limit=25,
        offset=(page - 1) * 25,
    )
    total = count_inventory_with_labels(include_notion=include_notion, filters=filters)
    filter_options = get_inventory_filter_options(include_notion=include_notion)
    return templates.TemplateResponse(
        "partials/barcode_inventory_list.html",
        {
            "request": request,
            "items": items,
            "filters": filters,
            "filter_options": filter_options,
            "page": page,
            "total_pages": max((total + 24) // 25, 1),
            "total_items": total,
        },
    )


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
    output_dir = MEDIA_ROOT / "barcodes"
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
    filters = {}
    inventory_items = list_inventory_with_labels_paginated(
        include_notion=include_notion,
        filters=filters,
        limit=25,
        offset=0,
    )
    total = count_inventory_with_labels(include_notion=include_notion, filters=filters)
    filter_options = get_inventory_filter_options(include_notion=include_notion)
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
            "filters": filters,
            "filter_options": filter_options,
            "page": 1,
            "total_pages": max((total + 24) // 25, 1),
            "total_items": total,
        },
    )


@router.post("/generate/print")
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
    label_paths = [MEDIA_ROOT / barcode["label_path"] for barcode in print_barcodes]

    try:
        pdf_bytes = BarcodeSheetPDF().build(label_paths)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        return templates.TemplateResponse(
            "partials/barcode_print_error.html",
            {
                "request": request,
                "message": str(exc),
            },
            status_code=400,
        )

    headers = {"Content-Disposition": "inline; filename=barcode-labels.pdf"}
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers=headers,
    )
