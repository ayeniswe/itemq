from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class BarcodeFormat:
    key: str
    label: str


SUPPORTED_FORMATS: dict[str, BarcodeFormat] = {
    "code128": BarcodeFormat(key="code128", label="Code 128"),
    "qr": BarcodeFormat(key="qr", label="QR"),
}

DEFAULT_FORMAT = "code128"


def normalize_format(requested: str | None) -> str:
    if requested in SUPPORTED_FORMATS:
        return requested
    return DEFAULT_FORMAT


def render_barcode_svg(value: str, fmt: str) -> str:
    if fmt == "qr":
        return _render_qr(value)
    return _render_code128(value)


def _render_code128(value: str) -> str:
    bits = _bits_from_value(value)
    bar_width = 2
    height = 70
    quiet_zone = 8
    total_width = quiet_zone * 2 + len(bits) * bar_width

    x = quiet_zone
    rects = []
    for bit in bits:
        if bit:
            rects.append(
                f"<rect x='{x}' y='0' width='{bar_width}' height='{height}' "
                "fill='#111827' />"
            )
        x += bar_width

    rects_markup = "".join(rects)
    return (
        f"<svg viewBox='0 0 {total_width} {height}' "
        f"width='{total_width}' height='{height}' "
        "role='img' aria-label='Barcode'>"
        f"{rects_markup}</svg>"
    )


def _render_qr(value: str) -> str:
    size = 21
    module = 4
    padding = 4
    grid = _qr_matrix(value, size)
    total = (size + padding * 2) * module

    rects = []
    for row in range(size):
        for col in range(size):
            if grid[row][col]:
                x = (col + padding) * module
                y = (row + padding) * module
                rects.append(
                    f"<rect x='{x}' y='{y}' width='{module}' height='{module}' "
                    "fill='#111827' />"
                )

    rects_markup = "".join(rects)
    return (
        f"<svg viewBox='0 0 {total} {total}' "
        f"width='{total}' height='{total}' "
        "role='img' aria-label='QR code'>"
        f"{rects_markup}</svg>"
    )


def _bits_from_value(value: str) -> list[int]:
    if not value:
        return [1] * 16
    bits: list[int] = []
    for ch in value:
        encoded = f"{ord(ch):08b}"
        bits.extend(int(bit) for bit in encoded)
    return bits


def _qr_matrix(value: str, size: int) -> list[list[bool]]:
    digest = sha256(value.encode("utf-8")).digest()
    bits: list[int] = []
    for byte in digest:
        bits.extend((byte >> shift) & 1 for shift in range(7, -1, -1))

    grid = [[False for _ in range(size)] for _ in range(size)]
    finder_coords = [(0, 0), (0, size - 7), (size - 7, 0)]
    for start_row, start_col in finder_coords:
        for r in range(7):
            for c in range(7):
                is_border = r in {0, 6} or c in {0, 6}
                is_center = 2 <= r <= 4 and 2 <= c <= 4
                grid[start_row + r][start_col + c] = is_border or is_center

    bit_index = 0
    for row in range(size):
        for col in range(size):
            if grid[row][col]:
                continue
            grid[row][col] = bool(bits[bit_index % len(bits)])
            bit_index += 1
    return grid
