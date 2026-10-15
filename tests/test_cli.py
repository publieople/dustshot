"""Command line surface that works without a GUI."""

from __future__ import annotations

import json

import pytest

from catchlight import cli
from catchlight.config import Settings


def test_parser_lists_commands() -> None:
    parser = cli.build_parser()
    args = parser.parse_args([])
    assert args.command is None
    args = parser.parse_args(["region", "--pin"])
    assert args.command == "region"
    assert args.pin is True
    args = parser.parse_args(["record", "--gif", "--duration", "3"])
    assert args.command == "record"
    assert args.gif is True
    assert args.duration == 3
    args = parser.parse_args(["codes"])
    assert args.command == "codes"
    args = parser.parse_args(["history", "--gui"])
    assert args.command == "history"
    assert args.gui is True


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["version"]) == 0
    assert "catchlight" in capsys.readouterr().out


def test_hotkeys_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["hotkeys", "--compositor", "niri"]) == 0
    output = capsys.readouterr().out
    assert "catchlight" in output
    assert "spawn" in output


def test_settings_show_is_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["settings", "--show"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "capture" in payload
    assert "annotation" in payload


def test_unknown_command_is_an_error() -> None:
    with pytest.raises(SystemExit):
        cli.main(["nope"])


def test_set_setting_coerces_types() -> None:
    settings = Settings()
    cli.set_setting(settings, "capture.image_format=jpg")
    cli.set_setting(settings, "capture.copy_after_capture=false")
    cli.set_setting(settings, "annotation.shape_width=5")
    cli.set_setting(settings, "capture.last_region=[1, 2, 3, 4]")
    assert settings.capture.image_format == "jpg"
    assert settings.capture.copy_after_capture is False
    assert settings.annotation.shape_width == 5
    assert settings.capture.last_region == [1, 2, 3, 4]


def test_set_setting_rejects_unknown_key() -> None:
    with pytest.raises(SystemExit):
        cli.set_setting(Settings(), "capture.nope=1")
    with pytest.raises(SystemExit):
        cli.set_setting(Settings(), "nope.value=1")


def test_parse_rect_and_point() -> None:
    assert cli.parse_rect("10,20,300,200") == cli.parse_rect("10,20,300,200")
    assert (cli.parse_rect("1,2,3,4").width) == 3
    assert cli.parse_point("10,20") == (10, 20)
    with pytest.raises(SystemExit):
        cli.parse_rect("1,2,3")


def test_codes_command_prints_symbols(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from PIL import Image

    from catchlight import barcode

    monkeypatch.setattr(cli, "load_image", lambda path: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(
        barcode,
        "decode",
        lambda image, **kwargs: [barcode.Code("hello", "QR-Code", "x.png")],
    )
    assert cli.main(["codes", "x.png"]) == 0
    assert "QR-Code\thello" in capsys.readouterr().out


def test_codes_command_reports_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from PIL import Image

    from catchlight import barcode

    monkeypatch.setattr(cli, "load_image", lambda path: Image.new("RGB", (8, 8)))
    monkeypatch.setattr(barcode, "decode", lambda image, **kwargs: [])
    assert cli.main(["codes", "x.png"]) == 0
    assert "没有找到" in capsys.readouterr().err


def test_parser_accepts_redact() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["redact", "--mode", "blur", "--kinds", "email"])
    assert args.command == "redact"
    assert args.mode == "blur"
    assert args.kinds == "email"


def test_redact_command_masks_matches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    from PIL import Image

    from catchlight import ocr

    monkeypatch.setattr(cli, "load_image", lambda path: Image.new("RGB", (60, 20), "white"))
    monkeypatch.setattr(
        ocr,
        "recognize",
        lambda image, **kwargs: ocr.OcrResult(
            text="po@example.com",
            words=[ocr.WordBox("po@example.com", 2, 2, 50, 14, 95.0, 1001)],
            languages="eng",
            confidence=95.0,
        ),
    )
    target = tmp_path / "out.png"
    assert cli.main(["redact", "x.png", "--output", str(target)]) == 0
    assert "email" in capsys.readouterr().out
    assert target.exists()


def test_parser_accepts_scroll() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["scroll", "--steps", "3", "--manual"])
    assert args.command == "scroll"
    assert args.steps == 3
    assert args.manual is True


class _Store:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self) -> Settings:
        return self._settings

    def save(self) -> None:
        return None


class _History:
    def record_image(self, *args, **kwargs) -> None:
        return None

    def save(self) -> None:
        return None


def test_scroll_command_stitches_the_frames(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    from PIL import Image, ImageDraw

    from catchlight import scroll

    page = Image.new("RGB", (60, 300), "white")
    draw = ImageDraw.Draw(page)
    for y in range(0, 300, 10):
        colour = ((y * 13) % 256, (y * 29) % 256, (y * 7) % 256)
        draw.rectangle([2, y, 50, y + 4], fill=colour)
    frames = iter([page.crop((0, 0, 60, 150)), page.crop((0, 100, 60, 250))])

    monkeypatch.setattr(cli, "load_store", lambda: _Store(Settings()))
    monkeypatch.setattr(cli, "History", _History)
    monkeypatch.setattr(cli, "capture_region", lambda region: next(frames))
    monkeypatch.setattr(scroll, "advance_scroll", lambda *args, **kwargs: None)

    target = tmp_path / "long.png"
    code = cli.main(
        [
            "scroll",
            "--steps",
            "2",
            "--rect",
            "0,0,60,150",
            "--no-copy",
            "--no-editor",
            "--output",
            str(target),
        ]
    )
    assert code == 0
    assert target.exists()
    assert Image.open(target).size == (60, 250)
    assert "已保存滚动截图" in capsys.readouterr().out
