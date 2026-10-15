"""Scrolling capture: overlap detection, stitching and the advance backends."""

from __future__ import annotations

import pytest
from PIL import Image, ImageChops, ImageDraw

from catchlight import scroll


def document(height: int = 400, width: int = 120) -> Image.Image:
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    for y in range(0, height, 20):
        colour = ((y * 13) % 256, (y * 29) % 256, (y * 7) % 256)
        draw.rectangle([4, y, width - 8, y + 8], fill=colour)
    return page


def viewport(page: Image.Image, top: int, height: int = 200) -> Image.Image:
    return page.crop((0, top, page.width, top + height))


def test_row_signature_tracks_each_row() -> None:
    frame = Image.new("RGB", (64, 3), "white")
    frame.paste((0, 0, 0), (0, 1, 64, 2))
    signature = scroll.row_signature(frame)
    assert len(signature) == 3
    assert signature[0] == pytest.approx((255.0, 255.0, 255.0))
    assert signature[1] == pytest.approx((0.0, 0.0, 0.0))


def test_find_overlap_recovers_the_real_scroll_amount() -> None:
    page = document()
    assert scroll.find_overlap(viewport(page, 0, 200), viewport(page, 120, 200)) == 80


def test_find_overlap_gives_up_when_nothing_matches() -> None:
    page = document()
    assert scroll.find_overlap(viewport(page, 0, 200), viewport(page, 200, 200)) == 0


def test_stitch_vertical_rebuilds_the_whole_page() -> None:
    page = document(420, 140)
    frames = [viewport(page, 0, 180), viewport(page, 120, 180), viewport(page, 240, 180)]
    canvas, overlaps = scroll.stitch_vertical(frames)
    assert canvas.size == (140, 420)
    assert overlaps == [60, 60]
    assert ImageChops.difference(canvas, page).getbbox() is None


def test_stitch_vertical_counts_an_unmoved_frame_once() -> None:
    page = document()
    frame = viewport(page, 0, 200)
    canvas, overlaps = scroll.stitch_vertical([frame, frame.copy()])
    assert canvas.size == (120, 200)
    assert overlaps == [200]


def test_stitch_vertical_needs_frames() -> None:
    with pytest.raises(scroll.ScrollError):
        scroll.stitch_vertical([])


def test_build_advance_command_for_wtype() -> None:
    assert scroll.build_advance_command("wtype", amount=2) == ["wtype", "-k", "Next", "-k", "Next"]


def test_build_advance_command_for_ydotool() -> None:
    assert scroll.build_advance_command("ydotool") == ["ydotool", "click", "--", "5"]


def test_build_advance_command_rejects_an_unknown_backend() -> None:
    with pytest.raises(scroll.ScrollError):
        scroll.build_advance_command("nope")


def test_advance_scroll_reports_a_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scroll.shutil, "which", lambda name: None)
    with pytest.raises(scroll.ScrollError):
        scroll.advance_scroll("wtype")


def test_scroll_capture_advances_between_frames() -> None:
    page = document(420, 120)
    frames = [viewport(page, 0, 180), viewport(page, 120, 180), viewport(page, 240, 180)]
    scrolled: list[int] = []

    def capture(region) -> Image.Image:
        return frames[len(scrolled)]

    def advance() -> None:
        scrolled.append(1)

    canvas, overlaps = scroll.scroll_capture(None, steps=3, capture=capture, advance=advance)
    assert len(scrolled) == 2
    assert canvas.height == 420
    assert overlaps == [60, 60]


def test_scroll_capture_settles_between_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    page = document(420, 120)
    frames = [viewport(page, 0, 180), viewport(page, 120, 180)]
    slept: list[float] = []
    monkeypatch.setattr(scroll.time, "sleep", lambda seconds: slept.append(seconds))

    canvas, _overlaps = scroll.scroll_capture(
        None,
        steps=2,
        capture=lambda region: frames.pop(0),
        advance=lambda: None,
        settle=0.25,
    )
    assert slept == [0.25]
    assert canvas.height == 300


def test_scroll_capture_reports_a_screen_that_never_moves() -> None:
    page = document()
    frame = viewport(page, 0, 200)
    with pytest.raises(scroll.ScrollError, match="画面没有滚动"):
        scroll.scroll_capture(
            None,
            steps=3,
            capture=lambda region: frame.copy(),
            advance=lambda: None,
        )
