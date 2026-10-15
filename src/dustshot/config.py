"""Persistent settings for Dustshot.

A small JSON store under XDG_CONFIG_HOME/dustshot/config.json with dataclass
defaults. Unknown keys found on disk are preserved so newer versions do not
destroy user configuration.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

APP_SLUG = "dustshot"


def _xdg(env: str, fallback: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw) if raw else fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP_SLUG


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP_SLUG


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", Path.home() / ".cache") / APP_SLUG


def config_path() -> Path:
    return config_dir() / "config.json"


DEFAULT_PALETTE = [
    "#ff3b30",
    "#ff9500",
    "#ffcc00",
    "#34c759",
    "#00c7be",
    "#007aff",
    "#5856d6",
    "#af52de",
    "#ffffff",
    "#000000",
]


@dataclass
class CaptureSettings:
    """Behaviour of the frame grab and the selection overlay."""

    save_dir: str = str(Path.home() / "Pictures" / "Screenshots")
    filename_pattern: str = "Shot_%Y-%m-%d_%H-%M-%S"
    image_format: str = "png"
    copy_after_capture: bool = True
    open_editor: bool = True
    dim: float = 0.35
    magnifier: bool = True
    show_size_label: bool = True
    remember_last_region: bool = True
    last_region: list[int] = field(default_factory=list)


@dataclass
class AnnotationSettings:
    """Default tool parameters."""

    color: str = "#ff3b30"
    palette: list[str] = field(default_factory=lambda: list(DEFAULT_PALETTE))
    pencil_width: int = 3
    marker_width: int = 3
    highlighter_width: int = 14
    shape_width: int = 2
    arrow_style: str = "solid"
    text_size: int = 16
    serial_size: int = 20
    serial_start: int = 1
    mosaic_block: int = 12
    blur_radius: int = 12
    fill_shapes: bool = False


@dataclass
class PinSettings:
    """Defaults for pinned windows."""

    opacity: float = 1.0
    border_radius: int = 0
    border_width: int = 0
    border_color: str = "#888888"
    keep_ratio: bool = True
    always_on_top: bool = True
    click_through: bool = False
    shadow: bool = True
    group: str = "default"


@dataclass
class OcrSettings:
    languages: str = "eng+chi_sim"
    auto_copy: bool = True
    show_overlay: bool = True
    tesseract_cmd: str = "tesseract"


@dataclass
class RecordingSettings:
    fps: int = 30
    codec: str = "h264"
    encoder: str = "auto"
    container: str = "mp4"
    gif_fps: int = 15
    gif_width: int = 800
    include_cursor: bool = True
    audio: bool = False


@dataclass
class Settings:
    """Root configuration object."""

    capture: CaptureSettings = field(default_factory=CaptureSettings)
    annotation: AnnotationSettings = field(default_factory=AnnotationSettings)
    pin: PinSettings = field(default_factory=PinSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    recording: RecordingSettings = field(default_factory=RecordingSettings)
    shortcuts: dict[str, str] = field(
        default_factory=lambda: {
            "region": "Print",
            "region_edit": "Shift+Print",
            "full": "Ctrl+Print",
            "pin_clipboard": "Ctrl+Shift+V",
            "restore_last": "Alt+Print",
            "toggle_all_pins": "Alt+H",
            "close_all_pins": "Alt+Shift+H",
        }
    )


def _merge_dataclass(obj: Any, data: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return obj
    known = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            setattr(obj, key, value)
            continue
        current = getattr(obj, key)
        if is_dataclass(current) and not isinstance(current, type):
            _merge_dataclass(current, value)
        else:
            setattr(obj, key, value)
    return obj


def _merge_extras(payload: dict[str, Any], obj: Any) -> None:
    """Write back attributes that are not declared fields.

    load() accepts unknown keys so a newer version can add options without
    breaking an older one; save() must not silently drop them again.
    """
    if not is_dataclass(obj):
        return
    known = {f.name for f in fields(obj)}
    for key, value in vars(obj).items():
        if key in known:
            child = getattr(obj, key)
            if is_dataclass(child) and isinstance(payload.get(key), dict):
                _merge_extras(payload[key], child)
            continue
        payload[key] = value


class SettingsStore:
    """Loads and stores Settings as JSON."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else config_path()
        self.settings = Settings()

    def load(self) -> Settings:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            _merge_dataclass(self.settings, data)
        return self.settings

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self.settings)
        _merge_extras(payload, self.settings)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return self.path

    def reset(self) -> Settings:
        self.settings = Settings()
        self.save()
        return self.settings


def ensure_dirs() -> None:
    for directory in (config_dir(), data_dir(), cache_dir()):
        directory.mkdir(parents=True, exist_ok=True)
