"""The tray menu model and the icon bytes: everything that needs no D-Bus."""

from __future__ import annotations

import pytest
from PIL import Image

from dustshot import APP_ID, cli, tray


def test_menu_ids_are_unique() -> None:
    ids = [row.id for row in tray.entries()]
    assert len(ids) == len(set(ids))
    assert tray.MENU_ROOT not in ids


def test_rows_carry_a_label_or_are_separators() -> None:
    for row in tray.entries():
        if row.separator:
            assert row.label == ""
            assert row.command == ()
            assert tray.command_for(row.id) is None
        else:
            assert row.label
            if row.command:
                assert tray.command_for(row.id) == row.command
            else:
                assert tray.command_for(row.id) is None


def test_unknown_rows_have_no_command() -> None:
    assert tray.entry(999) is None
    assert tray.command_for(999) is None


def test_only_the_quit_row_quits() -> None:
    assert tray.is_quit(tray.QUIT_ID)
    for row in tray.entries():
        if row.id != tray.QUIT_ID:
            assert not tray.is_quit(row.id)


def test_every_command_parses() -> None:
    parser = cli.build_parser()
    commands = [row for row in tray.entries() if tray.command_for(row.id) is not None]
    assert commands
    for row in commands:
        args = parser.parse_args(list(row.command))
        assert args.command == row.command[0]
        assert row.command[0] in cli.COMMANDS


def test_icon_image_is_a_transparent_tile() -> None:
    image = tray.icon_image(48)
    assert image.mode == "RGBA"
    assert image.size == (48, 48)
    alpha = image.getchannel("A")
    assert alpha.getextrema() == (0, 255)
    assert image.getpixel((24, 24)) == tray.RED


def test_icon_uses_the_requested_size() -> None:
    assert tray.icon_image(16).size == (16, 16)


def test_icon_rejects_absurd_sizes() -> None:
    with pytest.raises(ValueError):
        tray.icon_image(4)


def test_pixmap_is_argb32_network_order() -> None:
    image = Image.new("RGBA", (2, 1))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 128))
    width, height, data = tray.pixmap(image)
    assert (width, height) == (2, 1)
    assert data == bytes([255, 255, 0, 0, 128, 0, 255, 0])


def test_icon_pixmap_has_four_bytes_per_pixel() -> None:
    width, height, data = tray.icon_pixmap(32)
    assert (width, height) == (32, 32)
    assert len(data) == 32 * 32 * 4


def test_item_bus_names_start_with_the_conventional_one() -> None:
    conventional, own = tray.item_bus_names(7)
    assert conventional == f"{tray.BUS_PREFIX}-7-1"
    assert own == f"{APP_ID}.StatusNotifierItem-7-1"


def test_item_bus_names_use_the_sandbox_id_when_there_is_one() -> None:
    assert tray.item_bus_names(7, "io.github.publieople.Dustshot")[1] == (
        "io.github.publieople.Dustshot.StatusNotifierItem-7-1"
    )
