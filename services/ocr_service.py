from __future__ import annotations

import functools
import io
import os
import shutil

from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None


@functools.lru_cache(maxsize=1)
def get_tesseract_path() -> str | None:
    """Finds the tesseract binary if available."""
    # Check custom env var
    env_path = os.getenv("TESSERACT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Check PATH
    which_path = shutil.which("tesseract")
    if which_path:
        return which_path

    # Check common Windows installation paths
    common_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    return None


def is_ocr_available() -> bool:
    """Returns True if pytesseract is installed and tesseract binary is found."""
    if pytesseract is None:
        return False
    return get_tesseract_path() is not None


def perform_ocr(image: Image.Image | bytes) -> str:
    """Runs OCR on an image and returns extracted text."""
    if pytesseract is None or not is_ocr_available():
        raise RuntimeError("Tesseract OCR is not installed or not in PATH.")

    tess_path = get_tesseract_path()
    if tess_path:
        pytesseract.pytesseract.tesseract_cmd = tess_path

    if isinstance(image, bytes):
        img_obj = Image.open(io.BytesIO(image))
    else:
        img_obj = image

    # Convert to RGB if needed
    if img_obj.mode not in ("RGB", "L"):
        img_obj = img_obj.convert("RGB")

    text = pytesseract.image_to_string(img_obj)
    return text.strip()
