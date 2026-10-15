"""Saving, naming and settings-aware output paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image

from dustshot.config import CaptureSettings, Settings
from dustshot.output import build_name, default_save_path, human_timestamp, save_image, unique_path


def make_settings(tmp_path: Path, fmt: str = "png") -> Settings:
    settings = Settings()
    settings.capture = CaptureSettings(save_dir=str(tmp_path), image_format=fmt)
    return settings


def test_build_name_uses_pattern_and_format(tmp_path: Path) -> None:
    capture = CaptureSettings(filename_pattern="Shot_%Y-%m-%d_%H-%M-%S", image_format="png")
    when = datetime(2026, 10, 15, 15, 30, 45)
    assert build_name(capture, when) == "Shot_2026-10-15_15-30-45.png"
    capture.image_format = "jpg"
    assert build_name(capture, when) == "Shot_2026-10-15_15-30-45.jpg"


def test_unique_path_adds_index(tmp_path: Path) -> None:
    (tmp_path / "shot.png").write_bytes(b"x")
    assert unique_path(tmp_path, "shot.png") == tmp_path / "shot_2.png"
    (tmp_path / "shot_2.png").write_bytes(b"x")
    assert unique_path(tmp_path, "shot.png") == tmp_path / "shot_3.png"


def test_save_image_writes_requested_format(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "jpg")
    image = Image.new("RGB", (20, 20), (255, 0, 0))
    target = save_image(image, settings, when=datetime(2026, 1, 2, 3, 4, 5))
    assert target.suffix == ".jpg"
    assert target.exists()
    assert Image.open(target).size == (20, 20)


def test_save_image_rewrites_suffix(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "jpg")
    image = Image.new("RGB", (10, 10), (0, 255, 0))
    target = save_image(image, settings, path=tmp_path / "manual.png")
    assert target.name == "manual.jpg"


def test_default_save_path_is_inside_save_dir(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    path = default_save_path(settings, datetime(2026, 5, 5, 5, 5, 5))
    assert path.parent == tmp_path
    assert path.name.startswith("Shot_2026-05-05_05-05-05")


def test_human_timestamp_formats_value() -> None:
    assert human_timestamp(0).startswith("1970-01-01")
