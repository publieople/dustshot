"""Clipboard helpers.

When GTK is available the display clipboard is used directly, which copies both
the pixels and the text representations in one transaction. Otherwise the
wl-clipboard command line tools are used so that the CLI still works in a plain
Wayland session.
"""

from __future__ import annotations

import io
import shutil
import subprocess

from PIL import Image


def _wl_tool(name: str) -> str | None:
    return shutil.which(name)


def _run_with_stdin(cmd: list[str], payload: bytes, timeout: float = 10.0) -> bool:
    try:
        result = subprocess.run(cmd, input=payload, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def copy_image(image: Image.Image) -> bool:
    """Copy an image to the clipboard; returns True on success."""

    data = png_bytes(image)
    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, GLib

        display = Gdk.Display.get_default()
        if display is not None:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            clipboard = display.get_clipboard()
            clipboard.set_content(Gdk.ContentProvider.new_for_value(texture))
            return True
    except Exception:
        pass
    tool = _wl_tool("wl-copy")
    if not tool:
        return False
    return _run_with_stdin([tool, "--type", "image/png"], data)


def copy_text(text: str) -> bool:
    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(text)
            return True
    except Exception:
        pass
    tool = _wl_tool("wl-copy")
    if not tool:
        return False
    return _run_with_stdin([tool], text.encode("utf-8"))


def paste_image() -> Image.Image | None:
    """Read an image from the clipboard, or None when there is none."""

    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display is not None:
            clipboard = display.get_clipboard()
            texture = clipboard.read_texture()
            if texture is not None:
                data = texture.save_to_png_bytes().get_data()
                return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        pass
    tool = _wl_tool("wl-paste")
    if not tool:
        return None
    try:
        result = subprocess.run(
            [tool, "--no-newline", "--type", "image/png"], capture_output=True, timeout=10.0, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        return Image.open(io.BytesIO(result.stdout)).convert("RGB")
    except Exception:
        return None


def paste_text() -> str | None:
    tool = _wl_tool("wl-paste")
    if not tool:
        return None
    try:
        result = subprocess.run([tool, "--no-newline"], capture_output=True, timeout=10.0, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace")
