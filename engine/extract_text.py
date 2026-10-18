"""Text extraction: PDF text layer, OCR, VLM fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image


@dataclass
class ExtractedText:
    """Extracted text with page info."""

    text: str
    pages: list[dict]  # Each page: {page_num, text, bbox_data}
    method: str  # "pdf_text", "ocr", "vlm"


async def extract_text(
    image_data: Any | None,
    file_path: Path | None,
    text_input: str | None,
) -> ExtractedText:
    """Extract text from file or text input."""
    if text_input:
        return ExtractedText(
            text=text_input,
            pages=[{"page_num": 1, "text": text_input, "bbox_data": []}],
            method="text_input",
        )

    if not file_path or not file_path.exists():
        raise ValueError("No valid input provided")

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return await _extract_pdf(file_path)
    elif suffix in [".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"]:
        return await _extract_image(file_path, image_data)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


async def _extract_pdf(file_path: Path) -> ExtractedText:
    """Extract text from PDF - try text layer first, then OCR."""
    loop = asyncio.get_event_loop()

    # Try text layer first
    text_result = await loop.run_in_executor(None, _extract_pdf_text, file_path)

    if text_result["has_text"]:
        return ExtractedText(
            text=text_result["text"],
            pages=text_result["pages"],
            method="pdf_text",
        )

    # Fallback to OCR on rendered pages
    ocr_result = await loop.run_in_executor(None, _ocr_pdf, file_path)
    return ExtractedText(
        text=ocr_result["text"],
        pages=ocr_result["pages"],
        method="ocr",
    )


def _require_tesseract() -> None:
    """Fail with a clear message instead of a crash when OCR is unavailable."""
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:
        raise ValueError(
            "OCR unavailable: tesseract binary not found. "
            "Install it (e.g. brew install tesseract) or provide a PDF with a text layer."
        ) from e


def _extract_pdf_text(file_path: Path) -> dict:
    """Extract text from PDF text layer."""
    doc = fitz.open(file_path)
    pages = []
    full_text = []

    for page_num, page in enumerate(doc, 1):
        text = page.get_text()
        blocks = page.get_text("dict")["blocks"]

        page_bboxes = []
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        bbox = span["bbox"]  # x0, y0, x1, y1 in points
                        page_bboxes.append(
                            {
                                "text": span["text"],
                                "bbox": _normalize_bbox(bbox, page.rect.width, page.rect.height),
                            }
                        )

        pages.append(
            {
                "page_num": page_num,
                "text": text,
                "bbox_data": page_bboxes,
            }
        )
        full_text.append(text)

    doc.close()

    combined = "\n\n".join(full_text).strip()
    return {
        "has_text": len(combined) > 50,  # Arbitrary threshold
        "text": combined,
        "pages": pages,
    }


def _ocr_pdf(file_path: Path) -> dict:
    """OCR PDF by rendering pages to images."""
    _require_tesseract()
    doc = fitz.open(file_path)
    pages = []
    full_text = []

    for page_num, page in enumerate(doc, 1):
        # Render page to image
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # OCR
        text = pytesseract.image_to_string(img)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        page_bboxes = []
        for i in range(len(data["text"])):
            if data["text"][i].strip():
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                page_bboxes.append(
                    {
                        "text": data["text"][i],
                        "bbox": _normalize_bbox((x, y, x + w, y + h), pix.width, pix.height),
                    }
                )

        pages.append(
            {
                "page_num": page_num,
                "text": text,
                "bbox_data": page_bboxes,
            }
        )
        full_text.append(text)

    doc.close()

    return {
        "text": "\n\n".join(full_text).strip(),
        "pages": pages,
    }


async def _extract_image(file_path: Path, image_data: Any | None) -> ExtractedText:
    """Extract text from image using OCR."""
    _require_tesseract()
    loop = asyncio.get_event_loop()

    if image_data is not None:
        # Use preprocessed image
        img = Image.fromarray(cv2.cvtColor(image_data.processed, cv2.COLOR_BGR2RGB))
    else:
        img = Image.open(file_path)

    text = await loop.run_in_executor(None, pytesseract.image_to_string, img)
    data = await loop.run_in_executor(None, pytesseract.image_to_data, img, pytesseract.Output.DICT)

    page_bboxes = []
    for i in range(len(data["text"])):
        if data["text"][i].strip():
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            page_bboxes.append(
                {
                    "text": data["text"][i],
                    "bbox": _normalize_bbox((x, y, x + w, y + h), img.width, img.height),
                }
            )

    return ExtractedText(
        text=text.strip(),
        pages=[
            {
                "page_num": 1,
                "text": text.strip(),
                "bbox_data": page_bboxes,
            }
        ],
        method="ocr",
    )


def _normalize_bbox(bbox: tuple, img_width: int, img_height: int) -> dict:
    """Normalize bbox to 0-1 range."""
    x0, y0, x1, y1 = bbox
    return {
        "x": max(0.0, min(1.0, x0 / img_width)),
        "y": max(0.0, min(1.0, y0 / img_height)),
        "width": max(0.0, min(1.0, (x1 - x0) / img_width)),
        "height": max(0.0, min(1.0, (y1 - y0) / img_height)),
    }


# Import cv2 at module level for type hint
import cv2
