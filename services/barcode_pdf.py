from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from math import ceil
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class BarcodeSheetPDF:
    page_size_in: tuple[float, float] = (8.5, 11)
    dpi: int = 300
    outer_margin_in: float = 0.5
    padding_in: float = 0.04
    inner_margin_in: float = 0.1

    def _compute_grid(self, canvas_px: tuple[int, int]) -> tuple[int, int, float]:
        canvas_w_px, canvas_h_px = canvas_px

        qr_w_in = canvas_w_px / self.dpi
        qr_h_in = canvas_h_px / self.dpi

        cell_size_in = max(qr_w_in, qr_h_in) + (self.inner_margin_in * 2)

        page_w_in, page_h_in = self.page_size_in
        usable_w = page_w_in - (self.outer_margin_in * 2)
        usable_h = page_h_in - (self.outer_margin_in * 2)

        cols = int((usable_w + self.padding_in) // (cell_size_in + self.padding_in))
        rows = int((usable_h + self.padding_in) // (cell_size_in + self.padding_in))

        if cols <= 0 or rows <= 0:
            raise RuntimeError("Computed grid does not fit on page")

        return cols, rows, cell_size_in

    def build(self, image_paths: list[Path], canvas_px: tuple[int, int] | None = None) -> bytes:
        if not image_paths:
            raise RuntimeError("No barcode images provided")

        for path in image_paths:
            if not path.exists():
                raise FileNotFoundError(f"Missing barcode image: {path}")

        if canvas_px is None:
            with Image.open(image_paths[0]) as sample:
                canvas_px = sample.size

        cols, rows, cell_size_in = self._compute_grid(canvas_px)

        page_w_px = int(round(self.page_size_in[0] * self.dpi))
        page_h_px = int(round(self.page_size_in[1] * self.dpi))

        cell_size_px = int(round(cell_size_in * self.dpi))
        padding_px = int(round(self.padding_in * self.dpi))
        inner_margin_px = int(round(self.inner_margin_in * self.dpi))

        usable_size_px = cell_size_px - (inner_margin_px * 2)
        if usable_size_px <= 0:
            raise ValueError("inner_margin_in too large for cell size")

        grid_width = cols * cell_size_px + (cols - 1) * padding_px
        grid_height = rows * cell_size_px + (rows - 1) * padding_px

        start_x = int(round((page_w_px - grid_width) / 2))
        start_y = int(round((page_h_px - grid_height) / 2))

        per_page = cols * rows
        total_pages = ceil(len(image_paths) / per_page)
        pages: list[Image.Image] = []

        for page in range(total_pages):
            page_img = Image.new("RGB", (page_w_px, page_h_px), "white")
            page_items = image_paths[page * per_page : (page + 1) * per_page]

            for idx, img_path in enumerate(page_items):
                col = idx % cols
                row = idx // cols

                x = start_x + col * (cell_size_px + padding_px)
                y = start_y + row * (cell_size_px + padding_px)

                with Image.open(img_path) as barcode_img:
                    barcode_img = barcode_img.convert("RGB")
                    native_w, native_h = barcode_img.size

                    scale = min(usable_size_px / native_w, usable_size_px / native_h)
                    img_w = int(round(native_w * scale))
                    img_h = int(round(native_h * scale))

                    if img_w != native_w or img_h != native_h:
                        barcode_img = barcode_img.resize((img_w, img_h), Image.LANCZOS)

                    draw_x = x + (cell_size_px - img_w) // 2
                    draw_y = y + (cell_size_px - img_h) // 2

                    page_img.paste(barcode_img, (draw_x, draw_y))

            pages.append(page_img)

        buffer = BytesIO()
        pages[0].save(
            buffer,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=self.dpi,
        )
        return buffer.getvalue()
