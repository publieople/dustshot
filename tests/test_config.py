"""Configuration persistence."""

from __future__ import annotations

import json
from pathlib import Path

from dustshot.config import CaptureSettings, SettingsStore, default_save_dir, pictures_dir


def test_defaults(store: SettingsStore) -> None:
    settings = store.load()
    assert settings.capture.image_format == "png"
    assert settings.capture.copy_after_capture is True
    assert settings.ocr.languages
    assert len(settings.annotation.palette) >= 8


def test_save_and_reload(store: SettingsStore) -> None:
    settings = store.load()
    settings.capture.image_format = "webp"
    settings.annotation.serial_start = 5
    path = store.save()
    assert path == store.path

    again = SettingsStore(store.path).load()
    assert again.capture.image_format == "webp"
    assert again.annotation.serial_start == 5


def test_unknown_keys_survive_a_reload(store: SettingsStore) -> None:
    """Forward compatibility: keys from newer versions are kept, not dropped."""
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"capture": {"image_format": "jpg", "future_option": 1}}), encoding="utf-8"
    )
    settings = store.load()
    assert settings.capture.image_format == "jpg"
    assert settings.capture.future_option == 1

    store.save()
    settings = SettingsStore(store.path).load()
    assert settings.capture.future_option == 1


def test_invalid_json_falls_back_to_defaults(store: SettingsStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{ not json", encoding="utf-8")
    settings = store.load()
    assert settings.capture.image_format == "png"


def test_reset_restores_defaults(store: SettingsStore) -> None:
    settings = store.load()
    settings.capture.image_format = "jpg"
    store.save()
    again = store.reset()
    assert again.capture.image_format == "png"
    assert Path(store.path).exists()


def test_pictures_dir_follows_the_xdg_user_dirs_file(tmp_path: Path, monkeypatch) -> None:
    """A localised picture folder keeps its name inside a Flatpak sandbox."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "user-dirs.dirs").write_text(
        'XDG_PICTURES_DIR="$HOME/图片"\nXDG_DOWNLOAD_DIR="$HOME/下载"\n', encoding="utf-8"
    )
    assert pictures_dir() == tmp_path / "图片"


def test_pictures_dir_accepts_the_braced_variable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "user-dirs.dirs").write_text(
        'XDG_PICTURES_DIR="${HOME}/Bilder"\n', encoding="utf-8"
    )
    assert pictures_dir() == tmp_path / "Bilder"


def test_pictures_dir_falls_back_to_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert pictures_dir() == tmp_path / "Pictures"


def test_default_save_dir_sits_under_the_pictures_dir() -> None:
    assert Path(CaptureSettings().save_dir) == default_save_dir()
    assert default_save_dir().name == "Screenshots"
