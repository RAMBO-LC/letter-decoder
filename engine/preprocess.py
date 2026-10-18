"""Image preprocessing using OpenCV."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class ImageData:
    """Preprocessed image data."""

    original: np.ndarray
    processed: np.ndarray
    width: int
    height: int


async def preprocess_image(file_path: Path | None) -> ImageData | None:
    """Preprocess image: deskew, denoise, crop."""
    if not file_path or not file_path.exists():
        return None

    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _preprocess_sync, file_path)


def _preprocess_sync(file_path: Path) -> ImageData:
    """Synchronous preprocessing."""
    # Read image
    img = cv2.imread(str(file_path))
    if img is None:
        raise ValueError(f"Could not read image: {file_path}")

    original = img.copy()
    h, w = img.shape[:2]

    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Denoise
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    # Deskew
    deskewed = _deskew(denoised)

    # Auto-crop to content
    cropped = _auto_crop(deskewed)

    return ImageData(
        original=original,
        processed=cropped,
        width=cropped.shape[1],
        height=cropped.shape[0],
    )


def _deskew(image: np.ndarray) -> np.ndarray:
    """Deskew image using minAreaRect on text contours."""
    # Threshold
    _, thresh = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Find contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return image

    # Get largest contour (assumed to be text block)
    largest = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(largest)
    angle = rect[-1]

    # Correct angle
    if angle < -45:
        angle = 90 + angle

    # Only rotate if skew is significant
    if abs(angle) > 0.5:
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
        return rotated

    return image


def _auto_crop(image: np.ndarray) -> np.ndarray:
    """Auto-crop to content bounding box."""
    # Threshold
    _, thresh = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Find non-zero points
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return image

    x, y, w, h = cv2.boundingRect(coords)

    # Add small padding
    pad = 10
    x = max(0, x - pad)
    y = max(0, y - pad)
    w = min(image.shape[1] - x, w + 2 * pad)
    h = min(image.shape[0] - y, h + 2 * pad)

    return image[y : y + h, x : x + w]
