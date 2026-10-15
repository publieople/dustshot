"""Saving, naming and clipboard plumbing for finished captures."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from .clipboard import copy_image
from .config import CaptureSettings, Settings

FORMAT_SUFFIX = {"png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp"}
LOSSY = {"jpg", "jpeg", "webp"}


def resolve_save_dir(settings: CaptureSettings) -> Path:
    directory = Path(settings.save_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def build_name(settings: CaptureSettings, when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime(settings.filename_pattern)
    suffix = FORMAT_SUFFIX.get(settings.image_format.lower(), ".png")
    return f"{stamp}{suffix}"


def unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def save_image(
    image: Image.Image,
    settings: Settings | CaptureSettings,
    path: str | Path | None = None,
    when: datetime | None = None,
) -> Path:
    """Save a finished image and return the path that was written."""

    capture = settings.capture if isinstance(settings, Settings) else settings
    if path is None:
        directory = resolve_save_dir(capture)
        target = unique_path(directory, build_name(capture, when))
    else:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)

    fmt = capture.image_format.lower()
    suffix = FORMAT_SUFFIX.get(fmt, ".png")
    if target.suffix.lower() != suffix:
        target = target.with_suffix(suffix)

    if fmt in LOSSY:
        image.convert("RGB").save(target, quality=92, optimize=True)
    else:
        image.save(target, optimize=False)
    return target


def copy_to_clipboard(image: Image.Image) -> bool:
    return copy_image(image)


def default_save_path(settings: Settings, when: datetime | None = None) -> Path:
    capture = settings.capture
    return resolve_save_dir(capture) / build_name(capture, when)


def human_timestamp(value: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value if value is not None else time.time()))
