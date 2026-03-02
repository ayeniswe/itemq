from io import BytesIO

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from db import (
    get_inventory_items_with_labels_by_ids,
    get_plugin,
    list_inventory_with_labels_paginated,
    count_inventory_with_labels,
    get_inventory_filter_options,
    upsert_barcode_labels,
    list_inventory_label_state,
)
from model import Plugin
from services.barcode_rendering import (
    SUPPORTED_FORMATS,
    normalize_format,
    save_barcode_image,
)
from services.barcode_pdf import BarcodeSheetPDF
from config import MEDIA_ROOT
from routes.inventory import _build_filter_payload  # reuse datetime normalization

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _notion_enabled() -> bool:
    plugin = Plugin.from_row(get_plugin("notion"))
    return bool(plugin and plugin.enabled)


def _with_display_datetimes(filters: dict[str, str | None]) -> dict[str, str | None]:
    """Inject local-time display copies for created_from/created_to based on tz_offset_minutes."""
    enriched = dict(filters)
    raw_from = filters.get("created_from")
    raw_to = filters.get("created_to")
    try:
        offset = int(filters.get("tz_offset_minutes") or 0)
    except Exception:
        offset = 0

    def _to_local(value: str | None) -> str | None:
        if not value:
            return None
        try:
            from datetime import datetime, timedelta

            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            local_dt = dt - timedelta(minutes=offset)
            return local_dt.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return value.replace(" ", "T")

    enriched["created_from_display"] = _to_local(raw_from)
    enriched["created_to_display"] = _to_local(raw_to)
    return enriched


@router.get("/generate", response_class=HTMLResponse)
async def generate(
    request: Request,
    created_from: str | None = None,
    created_to: str | None = None,
    tz_offset_minutes: str | None = None,
):
    include_notion = _notion_enabled()
    filters = _build_filter_payload(
        search=None,
        search_case="insensitive",
        group_name=None,
        collection_name=None,
        collection_category=None,
        occasion=None,
        season=None,
        holiday=None,
        emotion=None,
        color=None,
        event_name=None,
        created_from=created_from,
        created_to=created_to,
        tz_offset_minutes=tz_offset_minutes,
    )
    filters = _with_display_datetimes(filters)
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
    item_ids: list[int] = []
    seen_ids: set[int] = set()
    for value in form.getlist("item_ids"):
        item_id = int(value)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        item_ids.append(item_id)
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
    page: int = 1,
):
    include_notion = _notion_enabled()
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
    filters = _with_display_datetimes(filters)
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


@router.get("/generate/selection_state")
async def generate_selection_state(
    request: Request,
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
    include_notion = _notion_enabled()
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
    rows = list_inventory_label_state(include_notion=include_notion, filters=filters)
    total = count_inventory_with_labels(include_notion=include_notion, filters=filters)
    items = [
        {
            "id": row["id"],
            "has_label": bool(row["label_path"]),
            "quantity": int(row["label_quantity"] or 0),
        }
        for row in rows
    ]
    return JSONResponse({"items": items, "total": total})


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
        existing_format = (item["label_format"] or "").lower()
        existing_path = item["label_path"]
        existing_file = MEDIA_ROOT / existing_path if existing_path else None

        if (
            existing_path
            and existing_format == normalized_format
            and existing_file
            and existing_file.exists()
        ):
            label_path = existing_path  # reuse existing label image that actually exists
        else:
            filename = save_barcode_image(item["barcode"], normalized_format, output_dir)
            label_path = f"barcodes/{filename}"

        entries.append(
            (
                item["id"],
                item["barcode"],
                normalized_format,
                label_path,
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
    return templates.TemplateResponse(
        "partials/barcode_generate_response.html",
        {
            "request": request,
            "barcodes": barcodes,
            "selected_format": _format_summary(barcodes),
            "selection_count": sum(quantities.values()),
            "items": inventory_items,
            "banner": None,
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
    missing = []
    for item in items:
        label_path = item["label_path"]
        if not label_path:
            missing.append(item)
            continue
        file_path = MEDIA_ROOT / label_path
        if not file_path.exists():
            missing.append(item)
    if missing:
        # Attempt to regenerate missing labels on the fly
        regenerated: list[tuple[int, str, str, str, int]] = []
        output_dir = MEDIA_ROOT / "barcodes"
        for item in missing:
            filename = save_barcode_image(item["barcode"], normalized_format, output_dir)
            label_path = f"barcodes/{filename}"
            regenerated.append(
                (
                    item["id"],
                    item["barcode"],
                    normalized_format,
                    label_path,
                    quantities.get(item["id"], 1),
                )
            )
        if regenerated:
            upsert_barcode_labels(regenerated)
            items = get_inventory_items_with_labels_by_ids(item_ids)
        else:
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
