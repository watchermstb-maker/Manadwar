"""Shared image-upload helpers (complaint photos, parcel photos, visitor photos).

Files live on disk under UPLOAD_DIR/<kind>/ with server-generated names; the
real type is detected from the first bytes, never from the client's filename
or Content-Type.
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

UPLOAD_ROOT = Path(os.getenv("UPLOAD_DIR") or (Path(__file__).resolve().parent.parent / "uploads"))
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def detect_image_type(head: bytes) -> Optional[str]:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def kind_dir(kind: str) -> Path:
    return UPLOAD_ROOT / kind


def save_image(kind: str, file: UploadFile) -> str:
    """Validate and store an uploaded image; returns the stored filename."""
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is larger than 5 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    ext = detect_image_type(data[:16])
    if ext is None:
        raise HTTPException(status_code=400, detail="Only JPG, PNG or WebP images are allowed.")
    folder = kind_dir(kind)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (folder / name).write_bytes(data)
    return name


def remove_image(kind: str, name: Optional[str]) -> None:
    if not name or Path(name).name != name:
        return
    try:
        (kind_dir(kind) / name).unlink()
    except OSError:
        pass


def image_path(kind: str, name: Optional[str]) -> Path:
    """Resolve a stored name to a file path or raise 404."""
    if not name or Path(name).name != name:
        raise HTTPException(status_code=404, detail="No photo.")
    path = kind_dir(kind) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No photo.")
    return path
