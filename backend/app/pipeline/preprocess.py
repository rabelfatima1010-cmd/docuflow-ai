"""Turn an uploaded file into model-ready inputs.

- Images: straighten (deskew), boost contrast, cap resolution, re-encode as PNG.
- PDFs: sent natively to the model as a document block; if the PDF has a real
  text layer we also keep that text so a cheaper text-only pass can be used.
"""

import base64
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pymupdf

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
PDF_TYPE = "application/pdf"
SUPPORTED_EXTENSIONS = set(IMAGE_TYPES) | {".pdf"}
MAX_SIDE_PX = 2000
MIN_TEXT_CHARS = 200  # below this a PDF is treated as a scan


class UnsupportedFileError(ValueError):
    pass


@dataclass
class PreparedDocument:
    kind: str  # "image" | "pdf"
    media_type: str
    b64: str
    page_count: int = 1
    text: str | None = None  # embedded PDF text layer, if meaningful
    notes: list[str] = field(default_factory=list)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mime_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return PDF_TYPE
    if ext in IMAGE_TYPES:
        return IMAGE_TYPES[ext]
    raise UnsupportedFileError(f"Unsupported file type '{ext}'. Use PDF, PNG, JPG or WEBP.")


def _deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Estimate text skew from dark-pixel orientation and rotate it level."""
    inverted = cv2.bitwise_not(gray)
    thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 50:
        return gray, 0.0
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    # OpenCV >= 4.5 returns angles in [0, 90); map to a small correction around 0
    if angle > 45:
        angle -= 90
    angle = -angle
    if abs(angle) < 0.3 or abs(angle) > 15:  # ignore noise and implausible values
        return gray, 0.0
    h, w = gray.shape
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated, angle


def prepare_image(data: bytes) -> PreparedDocument:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise UnsupportedFileError("Could not decode image.")
    notes: list[str] = []

    h, w = img.shape[:2]
    scale = MAX_SIDE_PX / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        notes.append(f"resized x{scale:.2f}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray, angle = _deskew(gray)
    if angle:
        notes.append(f"deskewed {angle:.1f} deg")
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    ok, png = cv2.imencode(".png", gray)
    if not ok:
        raise UnsupportedFileError("Could not encode image.")
    return PreparedDocument(
        kind="image",
        media_type="image/png",
        b64=base64.standard_b64encode(png.tobytes()).decode(),
        notes=notes,
    )


def prepare_pdf(data: bytes) -> PreparedDocument:
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises various types
        raise UnsupportedFileError(f"Could not open PDF: {exc}") from exc
    with pdf:
        text = "\n\n".join(f"--- Page {i + 1} ---\n{page.get_text()}" for i, page in enumerate(pdf))
        page_count = pdf.page_count
    meaningful = len("".join(text.split())) >= MIN_TEXT_CHARS
    return PreparedDocument(
        kind="pdf",
        media_type=PDF_TYPE,
        b64=base64.standard_b64encode(data).decode(),
        page_count=page_count,
        text=text if meaningful else None,
        notes=[f"{page_count} page(s)", "text layer found" if meaningful else "scanned (no text layer)"],
    )


def prepare(path: str | Path) -> PreparedDocument:
    path = Path(path)
    data = path.read_bytes()
    if mime_for(path.name) == PDF_TYPE:
        return prepare_pdf(data)
    return prepare_image(data)
