"""Font discovery through fontconfig with a safe fallback.

Annotation text has to render CJK and Latin glyphs without bundling a font, so
the system font is resolved at runtime with fc-match. If fontconfig is missing
the Pillow built-in bitmap font is used instead of failing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache

from PIL import ImageFont

REGULAR_FAMILIES = ("Noto Sans CJK SC", "Noto Sans", "DejaVu Sans")
BOLD_FAMILIES = ("Noto Sans CJK SC:bold", "Noto Sans:bold", "DejaVu Sans:bold")
MONO_FAMILIES = ("Noto Sans Mono CJK SC", "DejaVu Sans Mono")


def _fc_match(spec: str) -> str | None:
    if not shutil.which("fc-match"):
        return None
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}:%{index}", spec],
            capture_output=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - host dependent
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.decode("utf-8", "replace").strip()
    if not text:
        return None
    path, _sep, index = text.rpartition(":")
    if not path or not os.path.isfile(path):
        return None
    return f"{path}|{index or 0}"


def resolve(spec_or_families) -> tuple[str, int] | None:
    specs = (spec_or_families,) if isinstance(spec_or_families, str) else tuple(spec_or_families)
    for spec in specs:
        found = _fc_match(spec)
        if found:
            path, _sep, index = found.partition("|")
            try:
                return (path, int(index))
            except ValueError:
                return (path, 0)
    return None


@lru_cache(maxsize=32)
def load_font(size: int, bold: bool = False, mono: bool = False):
    """Return a Pillow font object for the requested size (pixel height)."""

    size = max(6, int(size))
    families = MONO_FAMILIES if mono else (BOLD_FAMILIES if bold else REGULAR_FAMILIES)
    resolved = resolve(families)
    if resolved:
        path, index = resolved
        try:
            return ImageFont.truetype(path, size=size, index=index)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def text_size(font, text: str) -> tuple[int, int]:
    """Measure multi-line text with the given font."""

    lines = text.split("\n") or [""]
    width = 0
    height = 0
    for line in lines:
        box = font.getbbox(line or " ")
        width = max(width, box[2] - box[0])
        height += int(font.size * 1.3) if hasattr(font, "size") else box[3] - box[1]
    return (max(width, 1), max(height, 1))
