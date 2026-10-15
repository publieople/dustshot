"""Unit tests for the ScreenCast portal backend (no D-Bus involved)."""

from __future__ import annotations

import os

import pytest
from PIL import Image

from catchlight.capture import portal
from catchlight.capture.base import Frame, Geometry, OutputInfo
from catchlight.capture.screencopy import CaptureError


def frame_at(x: int, y: int, width: int, height: int, colour: tuple[int, int, int]) -> Frame:
    image = Image.new("RGB", (width, height), colour)
    output = OutputInfo(
        name=f"portal-{x}",
        logical=Geometry(x, y, width, height),
        scale=1.0,
        physical=Geometry(0, 0, width, height),
    )
    return Frame(image=image, output=output)


def test_portal_error_is_a_capture_error() -> None:
    assert issubclass(portal.PortalError, CaptureError)


def test_backend_choice_prefers_grim_in_auto_mode() -> None:
    assert portal.backend_choice("auto", grim=True, portal=True) == "grim"
    assert portal.backend_choice("", grim=True, portal=False) == "grim"


def test_backend_choice_falls_back_to_the_portal() -> None:
    assert portal.backend_choice("auto", grim=False, portal=True) == "portal"
    assert portal.backend_choice("PORTAL", grim=True, portal=True) == "portal"


def test_backend_choice_requires_one_backend() -> None:
    with pytest.raises(CaptureError, match="没有可用的截图后端"):
        portal.backend_choice("auto", grim=False, portal=False)


def test_backend_choice_explains_unavailable_requests() -> None:
    with pytest.raises(CaptureError, match="grim 不可用"):
        portal.backend_choice("grim", grim=False, portal=True)
    with pytest.raises(CaptureError, match="ScreenCast portal 不可用"):
        portal.backend_choice("portal", grim=True, portal=False)
    with pytest.raises(CaptureError, match="未知截图后端"):
        portal.backend_choice("gstreamer", grim=True, portal=True)


def test_parse_streams_reads_size_and_position() -> None:
    streams = portal.parse_streams([(7, {"size": (64, 48), "position": (1920, 0), "source_type": 2})])
    assert len(streams) == 1
    stream = streams[0]
    assert (stream.node_id, stream.size, stream.position, stream.source_type) == (
        7,
        (64, 48),
        (1920, 0),
        2,
    )
    assert stream.geometry == Geometry(1920, 0, 64, 48)


def test_parse_streams_tolerates_missing_or_broken_properties() -> None:
    assert portal.parse_streams(None) == []
    assert portal.parse_streams([]) == []
    stream = portal.parse_streams([(3, {})])[0]
    assert (stream.size, stream.position, stream.geometry) == (None, None, None)
    assert [stream.node_id for stream in portal.parse_streams([(1,), "nope", (2, {"size": "wide"})])] == [2]
    assert portal.parse_streams([(4, {"size": (10, 20), "position": "x"})])[0].position is None


def test_parse_streams_accepts_glib_variants() -> None:
    class Fake:
        def unpack(self) -> object:
            return [(9, {"size": (10, 20)})]

    assert portal.parse_streams(Fake())[0].node_id == 9


def test_stream_output_uses_physical_pixels() -> None:
    stream = portal.Stream(node_id=4, size=(2560, 1600), position=(0, 0))
    output = stream.output()
    assert output.name == "portal-4"
    assert output.scale == 1.0
    assert output.logical == Geometry(0, 0, 2560, 1600)
    assert output.physical == Geometry(0, 0, 2560, 1600)
    assert output.primary is True
    assert portal.Stream(node_id=5, size=(10, 10)).output(1).primary is False


def test_request_and_session_paths_follow_the_portal_scheme() -> None:
    assert portal.request_path(":1.42", "tok") == "/org/freedesktop/portal/desktop/request/1_42/tok"
    assert portal.session_path(":1.42", "s") == "/org/freedesktop/portal/desktop/session/1_42/s"
    assert portal.request_path("1.9", "t") == "/org/freedesktop/portal/desktop/request/1_9/t"


def test_option_builders() -> None:
    assert portal.create_options("h", "s") == {"handle_token": "h", "session_handle_token": "s"}
    options = portal.select_options(
        "h", types=portal.SOURCE_WINDOW, multiple=True, cursor=portal.CURSOR_HIDDEN
    )
    assert options["types"] == 2
    assert options["multiple"] is True
    assert options["cursor_mode"] == 1
    assert "restore_token" not in options
    assert "persist_mode" not in options
    persisted = portal.select_options("h", restore_token="abc", persist=2)
    assert persisted["restore_token"] == "abc"
    assert persisted["persist_mode"] == 2
    assert portal.start_options("h") == {"handle_token": "h"}


def test_new_token_is_unique_and_prefixed() -> None:
    tokens = {portal.new_token("t") for _ in range(50)}
    assert len(tokens) == 50
    assert all(token.startswith("t") for token in tokens)


def test_source_types_match_the_portal_values() -> None:
    assert portal.SOURCE_TYPES == {"monitor": 1, "window": 2, "virtual": 4}


def test_stitch_frames_places_monitors_by_position() -> None:
    left = frame_at(0, 0, 10, 8, (255, 0, 0))
    right = frame_at(10, 0, 6, 8, (0, 255, 0))
    canvas = portal.stitch_frames([left, right])
    assert canvas.size == (16, 8)
    assert canvas.getpixel((0, 0)) == (255, 0, 0)
    assert canvas.getpixel((10, 0)) == (0, 255, 0)
    assert canvas.getpixel((15, 7)) == (0, 255, 0)


def test_stitch_frames_offsets_by_the_union_origin() -> None:
    bottom = frame_at(0, 100, 4, 4, (1, 2, 3))
    top = frame_at(0, 0, 4, 6, (9, 9, 9))
    canvas = portal.stitch_frames([bottom, top])
    assert canvas.size == (4, 104)
    assert canvas.getpixel((1, 1)) == (9, 9, 9)
    assert canvas.getpixel((1, 101)) == (1, 2, 3)


def test_stitch_frames_returns_the_only_frame() -> None:
    single = frame_at(0, 0, 4, 4, (5, 6, 7))
    assert portal.stitch_frames([single]) is single.image


def test_stitch_frames_rejects_an_empty_list() -> None:
    with pytest.raises(portal.PortalError, match="没有返回任何画面"):
        portal.stitch_frames([])


def test_portal_probe_never_raises() -> None:
    assert isinstance(portal.have_portal(), bool)


def test_output_for_frame_raises_the_scale_to_match_the_buffer() -> None:
    stream = portal.Stream(node_id=4, size=(2048, 1280), position=(0, 0))
    output = portal.output_for_frame(stream, Image.new("RGB", (2560, 1600)))
    assert output.scale == pytest.approx(1.25)
    assert output.logical == Geometry(0, 0, 2048, 1280)
    assert output.physical == Geometry(0, 0, 2560, 1600)


def test_output_for_frame_keeps_a_matching_buffer_unchanged() -> None:
    stream = portal.Stream(node_id=4, size=(64, 48), position=(10, 20))
    assert portal.output_for_frame(stream, Image.new("RGB", (64, 48))) == stream.output()


def test_output_for_frame_tolerates_a_stream_without_a_size() -> None:
    stream = portal.Stream(node_id=4)
    assert portal.output_for_frame(stream, Image.new("RGB", (8, 8))) == stream.output()


def test_pipelines_are_ready_to_format() -> None:
    assert len(portal.PIPELINES) >= 2
    for template in portal.PIPELINES:
        description = template.format(fd=7, node=9)
        assert "pipewiresrc fd=7 path=9" in description
        assert "appsink name=catchlight-sink" in description
    assert "glupload" in portal.PIPELINES[1]


def test_frame_falls_back_to_the_next_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    class FakeGrabber:
        def __init__(self, fd: int, node_id: int, template: str) -> None:
            attempts.append(template)
            self.template = template

        def grab(self, timeout: float) -> Image.Image:
            if self.template == portal.PIPELINES[0]:
                raise portal.PortalError("portal 画面管线出错：not-negotiated")
            return Image.new("RGB", (4, 2), (1, 2, 3))

        def close(self) -> None:
            attempts.append("closed")

    monkeypatch.setattr(portal, "_Grabber", FakeGrabber)
    session = portal.PortalSession(None, None, "/session", [portal.Stream(node_id=7, size=(4, 2))])
    fd = os.open(os.devnull, os.O_RDONLY)
    monkeypatch.setattr(session, "pipewire_fd", lambda timeout=0: fd)
    try:
        image = session.frame(session.streams[0])
    finally:
        os.close(fd)
    assert image.size == (4, 2)
    assert attempts == [portal.PIPELINES[0], "closed", portal.PIPELINES[1], "closed"]


def test_frame_reports_every_pipeline_it_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGrabber:
        def __init__(self, fd: int, node_id: int, template: str) -> None:
            pass

        def grab(self, timeout: float) -> Image.Image:
            raise portal.PortalError("portal 画面管线出错：no more input formats")

        def close(self) -> None:
            pass

    monkeypatch.setattr(portal, "_Grabber", FakeGrabber)
    session = portal.PortalSession(None, None, "/session", [portal.Stream(node_id=7, size=(4, 2))])
    fd = os.open(os.devnull, os.O_RDONLY)
    monkeypatch.setattr(session, "pipewire_fd", lambda timeout=0: fd)
    try:
        with pytest.raises(portal.PortalError, match=r"无法读取 portal 画面.*no more input formats"):
            session.frame(session.streams[0])
    finally:
        os.close(fd)
