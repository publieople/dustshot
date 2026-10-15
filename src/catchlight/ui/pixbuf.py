"""Pillow to GdkPixbuf conversion helpers."""

from __future__ import annotations

from PIL import Image


def pixbuf_module():
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    return GdkPixbuf


def to_pixbuf(image: Image.Image):
    """Convert a Pillow image (RGB or RGBA) into a GdkPixbuf without copying twice."""

    GdkPixbuf = pixbuf_module()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    has_alpha = image.mode == "RGBA"
    payload = image.tobytes()
    stride = image.width * (4 if has_alpha else 3)
    return GdkPixbuf.Pixbuf.new_from_bytes(
        _bytes(payload),
        GdkPixbuf.Colorspace.RGB,
        has_alpha,
        8,
        image.width,
        image.height,
        stride,
    )


def _bytes(payload: bytes):
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    return GLib.Bytes.new(payload)
