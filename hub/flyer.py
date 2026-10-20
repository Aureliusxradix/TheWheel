"""Flyers shown on The Wheel: cleaned before they are kept, served only while a listing uses them.

His ruling 2026-10-20: a listing with no page online is allowed, labelled honestly, and the flyer itself is shown.
What a phone photo of a flyer carries besides the flyer is stripped here: EXIF (often GPS, the camera, the time),
ICC and text chunks, by drawing the pixels into a fresh image. The original upload is never kept. The words ON the
flyer pass the identity gate before it is kept (server.py, from the reader's visible_text); a reviewer sees it too.
"""
import hashlib
import io
import re
from pathlib import Path

from PIL import Image, ImageOps

MAX_SIDE = 1600
NAME = re.compile(r"^[0-9a-f]{16}\.webp$")


def clean(data: bytes) -> bytes:
    """Any PNG/JPEG/WEBP/GIF in, a WEBP with nothing but pixels out."""
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)  # keep the photo upright before its EXIF goes
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.getchannel("A"))
    flat.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    flat.save(out, "WEBP", quality=82, method=4)  # a new image: no exif, icc or text chunks are written
    return out.getvalue()


def keep(folder: Path, data: bytes) -> str:
    """Store a cleaned flyer under its own hash; returns its name."""
    name = hashlib.sha256(data).hexdigest()[:16] + ".webp"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return name
