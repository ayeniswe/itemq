from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import uuid
import base64

import barcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont
import qrcode


@dataclass(frozen=True)
class BarcodeFormat:
    key: str
    label: str


SUPPORTED_FORMATS: dict[str, BarcodeFormat] = {
    "code128": BarcodeFormat(key="code128", label="Code 128"),
    "qr": BarcodeFormat(key="qr", label="QR"),
}

# Default to QR to improve scannability from mobile devices.
DEFAULT_FORMAT = "qr"


def normalize_format(requested: str | None) -> str:
    if requested in SUPPORTED_FORMATS:
        return requested
    return DEFAULT_FORMAT


def render_barcode_image_data(value: str, fmt: str) -> str:
    image = render_barcode_image(value, fmt)
    return _image_to_data_uri(image)


def render_barcode_image(value: str, fmt: str) -> Image.Image:
    if fmt == "qr":
        return _render_qr(value)
    return _render_code128(value)


def save_barcode_image(value: str, fmt: str, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = render_barcode_image(value, fmt)
    filename = f"{uuid.uuid4().hex}.png"
    file_path = output_dir / filename
    image.save(file_path, format="PNG")
    return filename


def _render_code128(value: str) -> Image.Image:
    barcode_class = barcode.get_barcode_class("code128")
    code = barcode_class(value, writer=ImageWriter())
    image = code.render(
        writer_options={
            "module_height": 15.0,
            "module_width": 0.35,
            "quiet_zone": 2.5,
            "write_text": False,
            "background": "white",
            "foreground": "black",
        }
    )
    return _add_value_label(image.convert("RGB"), value)


def _render_qr(value: str) -> Image.Image:
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return _add_value_label(image, value)


def _add_value_label(image: Image.Image, value: str) -> Image.Image:
    font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    text_bbox = draw.textbbox((0, 0), value, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    padding = 8
    width = max(image.width, text_width + padding * 2)
    height = image.height + text_height + padding * 2
    labeled = Image.new("RGB", (width, height), "white")
    x_offset = (width - image.width) // 2
    labeled.paste(image, (x_offset, 0))
    text_x = (width - text_width) // 2
    text_y = image.height + padding
    draw = ImageDraw.Draw(labeled)
    draw.text((text_x, text_y), value, fill="black", font=font)
    return labeled


def _image_to_data_uri(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"
