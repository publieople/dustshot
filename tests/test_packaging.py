"""Packaging assets: the desktop entry, AppStream metadata and icons ship with the project."""

from __future__ import annotations

import configparser
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"
DESKTOP = PACKAGING / "io.github.catchlight.desktop"
METAINFO = PACKAGING / "io.github.catchlight.metainfo.xml"
ICON_SIZES = ("256x256", "128x128", "64x64", "48x48")


def load_desktop() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # keep the case of Name[zh_CN] and friends
    parser.read(DESKTOP, encoding="utf-8")
    return parser


def test_desktop_entry_has_required_keys() -> None:
    parser = load_desktop()
    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application"
    assert entry["Name"] == "Catchlight"
    assert entry["Exec"].startswith("catchlight")
    assert entry["Icon"] == "io.github.catchlight"
    assert entry["Terminal"] == "false"
    assert entry["Categories"].endswith(";")


def test_desktop_entry_actions_exist() -> None:
    parser = load_desktop()
    entry = parser["Desktop Entry"]
    names = [name for name in entry["Actions"].split(";") if name]
    assert names == ["full", "edit", "record", "ocr", "history"]
    for name in names:
        section = parser[f"Desktop Action {name}"]
        assert section["Name"]
        assert section["Exec"].startswith("catchlight")


def test_desktop_entry_is_translated() -> None:
    entry = load_desktop()["Desktop Entry"]
    assert entry["Name[zh_CN]"] == "Catchlight 截图"
    assert entry["Comment[zh_CN]"]
    assert entry["Keywords[zh_CN]"].endswith(";")


def test_metainfo_matches_the_desktop_file() -> None:
    root = ET.parse(METAINFO).getroot()
    assert root.tag == "component"
    assert root.get("type") == "desktop-application"
    assert root.findtext("id") == "io.github.catchlight"
    assert root.findtext("metadata_license") == "CC0-1.0"
    assert root.findtext("project_license") == "GPL-3.0-or-later"
    assert root.findtext("launchable") == "io.github.catchlight.desktop"
    assert root.findtext("name") == "Catchlight"
    assert root.find("releases/release").get("version"), "AppStream needs at least one release"
    screenshots = root.findall("screenshots/screenshot")
    assert len(screenshots) >= 3
    for shot in screenshots:
        assert shot.findtext("image").startswith("https://")


@pytest.mark.parametrize("size", ICON_SIZES)
def test_icon_is_present(size: str) -> None:
    icon = PACKAGING / "icons" / "hicolor" / size / "apps" / "io.github.catchlight.png"
    assert icon.is_file()
    assert icon.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
