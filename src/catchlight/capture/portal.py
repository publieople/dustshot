"""Capture backend that drives the org.freedesktop.portal.ScreenCast portal.

Compositors without wlr-screencopy (GNOME, KDE, ...) still publish the
ScreenCast portal, which hands out one PipeWire stream per shared monitor. This
module runs the portal request/response dance (CreateSession -> SelectSources ->
Start -> OpenPipeWireRemote) and pulls a frame per stream through a small
GStreamer pipeline, so "catchlight full" and "catchlight region --rect" work
there too.

Everything that talks to D-Bus or GStreamer is imported lazily inside
functions, so the module - and its unit tests - keep working when PyGObject is
not installed.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import time
from dataclasses import dataclass, field, replace
from typing import Any

from PIL import Image

from .base import Frame, Geometry, OutputInfo
from .screencopy import CaptureError

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_INTERFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"

SOURCE_MONITOR = 1
SOURCE_WINDOW = 2
SOURCE_VIRTUAL = 4
SOURCE_TYPES = {"monitor": SOURCE_MONITOR, "window": SOURCE_WINDOW, "virtual": SOURCE_VIRTUAL}

CURSOR_HIDDEN = 1
CURSOR_EMBEDDED = 2
CURSOR_METADATA = 4

RESPONSE_SUCCESS = 0
RESPONSE_CANCELLED = 1
RESPONSE_OTHER = 2

PORTAL_TIMEOUT = 120.0
FRAME_TIMEOUT = 15.0
PROBE_TIMEOUT = 3.0

#: Pipeline descriptions tried in order, with {fd} and {node} filled in.
#: Compositors that only offer DMA-BUF buffers (niri) cannot negotiate those
#: against videoconvert, so the second description imports them through GL.
PIPELINES = (
    "pipewiresrc fd={fd} path={node} client-name=Catchlight do-timestamp=true ! "
    "videoconvert ! video/x-raw,format=RGB ! "
    "appsink name=catchlight-sink max-buffers=1 drop=true sync=false",
    "pipewiresrc fd={fd} path={node} client-name=Catchlight do-timestamp=true ! "
    "glupload ! glcolorconvert ! gldownload ! videoconvert ! video/x-raw,format=RGB ! "
    "appsink name=catchlight-sink max-buffers=1 drop=true sync=false",
)

#: How long one appsink pull waits before the pipeline is checked for errors.
PULL_SECONDS = 0.2


class PortalError(CaptureError):
    """Raised when the portal could not be used for a capture."""


@dataclass(frozen=True)
class Stream:
    """One PipeWire stream as the portal described it."""

    node_id: int
    size: tuple[int, int] | None = None
    position: tuple[int, int] | None = None
    source_type: int = SOURCE_MONITOR
    properties: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def geometry(self) -> Geometry | None:
        if self.size is None:
            return None
        x, y = self.position or (0, 0)
        return Geometry(x, y, self.size[0], self.size[1])

    def output(self, index: int = 0) -> OutputInfo:
        """Describe the stream as an output.

        Portal frames are physical pixels and the portal reports positions in
        compositor coordinates, so the logical geometry is the stream size at
        the reported position with a scale of 1.
        """

        size = self.size or (0, 0)
        x, y = self.position or (0, 0)
        return OutputInfo(
            name=f"portal-{self.node_id}",
            description=f"ScreenCast stream {self.node_id}",
            logical=Geometry(x, y, size[0], size[1]),
            scale=1.0,
            physical=Geometry(0, 0, size[0], size[1]),
            primary=index == 0,
        )


def _detail(warning: str) -> str:
    return f"（{warning}）" if warning else ""


def output_for_frame(stream: Stream, image: Image.Image, index: int = 0) -> OutputInfo:
    """Describe a stream for a frame that was really grabbed.

    Some compositors report the logical size in the portal but hand out buffers
    at the physical resolution (niri at 1.25 scale does), so the scale comes
    from the frame itself whenever the two disagree.
    """

    output = stream.output(index)
    logical = output.logical
    width, height = image.size
    if logical.width <= 0 or logical.height <= 0 or (width, height) == (logical.width, logical.height):
        return output
    return replace(output, scale=width / logical.width, physical=Geometry(0, 0, width, height))


def _pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def parse_streams(value: Any) -> list[Stream]:
    """Turn a Start() response's "streams" value into Stream objects.

    The input is the unpacked form of the portal's a(ua{sv}) signature.
    """

    if value is None:
        return []
    if hasattr(value, "unpack"):
        value = value.unpack()
    streams: list[Stream] = []
    for entry in value:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            continue
        node_id, raw = entry
        properties = dict(raw or {}) if isinstance(raw, dict) else {}
        streams.append(
            Stream(
                node_id=int(node_id),
                size=_pair(properties.get("size")),
                position=_pair(properties.get("position")),
                source_type=int(properties.get("source_type", SOURCE_MONITOR)),
                properties=properties,
            )
        )
    return streams


def _escape(unique_name: str) -> str:
    sender = unique_name[1:] if unique_name.startswith(":") else unique_name
    return sender.replace(".", "_")


def request_path(unique_name: str, token: str) -> str:
    """Predict the request object path the portal will use for a handle token."""

    return f"{OBJECT_PATH}/request/{_escape(unique_name)}/{token}"


def session_path(unique_name: str, token: str) -> str:
    """Predict the session object path the portal will use for a session token."""

    return f"{OBJECT_PATH}/session/{_escape(unique_name)}/{token}"


def new_token(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(8)}"


def create_options(token: str, session_token: str) -> dict[str, Any]:
    return {"handle_token": token, "session_handle_token": session_token}


def select_options(
    token: str,
    *,
    types: int = SOURCE_MONITOR,
    multiple: bool = False,
    cursor: int = CURSOR_EMBEDDED,
    restore_token: str = "",
    persist: int = 0,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "handle_token": token,
        "types": types,
        "multiple": multiple,
        "cursor_mode": cursor,
    }
    if restore_token:
        options["restore_token"] = restore_token
    if persist:
        options["persist_mode"] = persist
    return options


def start_options(token: str) -> dict[str, Any]:
    return {"handle_token": token}


def _typed_options(options: dict[str, Any], GLib: Any) -> dict[str, Any]:
    """Wrap plain Python values so they can be used in an a{sv} variant.

    GLib requires every value of an a{sv} to be a GLib.Variant already, so the
    option builders above keep working with plain Python types.
    """

    typed: dict[str, Any] = {}
    for key, value in options.items():
        if isinstance(value, bool):
            typed[key] = GLib.Variant("b", value)
        elif isinstance(value, int):
            typed[key] = GLib.Variant("u", value)
        elif isinstance(value, str):
            typed[key] = GLib.Variant("s", value)
        else:  # pragma: no cover - defensive
            raise PortalError(f"portal 选项值类型不支持：{key}={value!r}")
    return typed


def backend_choice(requested: str = "auto", *, grim: bool, portal: bool) -> str:
    """Pick a capture backend, or explain why the requested one is unusable."""

    wanted = (requested or "auto").lower()
    if wanted == "grim":
        if not grim:
            raise CaptureError("grim 不可用：请安装 grim，或改用 --backend portal")
        return "grim"
    if wanted == "portal":
        if not portal:
            raise CaptureError("ScreenCast portal 不可用：请确认 xdg-desktop-portal 及其后端正在运行")
        return "portal"
    if wanted != "auto":
        raise CaptureError(f"未知截图后端：{requested}")
    if grim:
        return "grim"
    if portal:
        return "portal"
    raise CaptureError("没有可用的截图后端：安装 grim，或启动 xdg-desktop-portal")


def stitch_frames(frames: list[Frame]) -> Image.Image:
    """Stitch portal frames onto one canvas using their logical positions."""

    if not frames:
        raise PortalError("portal 没有返回任何画面")
    if len(frames) == 1:
        return frames[0].image
    union = frames[0].output.logical
    for frame in frames[1:]:
        union = union.union(frame.output.logical)
    canvas = Image.new("RGB", (max(1, union.width), max(1, union.height)))
    for frame in frames:
        offset = (
            frame.output.logical.x - union.x,
            frame.output.logical.y - union.y,
        )
        canvas.paste(frame.image, offset)
    return canvas


# --------------------------------------------------------------------- D-Bus


def _gi() -> tuple[Any, Any]:
    try:
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except Exception as exc:  # pragma: no cover - depends on host
        raise PortalError(f"缺少 PyGObject，无法使用 ScreenCast portal：{exc}") from exc
    return Gio, GLib


def _connection(Gio: Any) -> Any:
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception as exc:  # pragma: no cover - depends on host
        raise PortalError(f"连接会话总线失败：{exc}") from exc


def portal_version(timeout: float = PROBE_TIMEOUT) -> int | None:
    """Return the ScreenCast portal version, or None when it is unavailable."""

    try:
        Gio, GLib = _gi()
        connection = _connection(Gio)
        reply = connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            PROPERTIES_INTERFACE,
            "Get",
            GLib.Variant("(ss)", (SCREENCAST_INTERFACE, "version")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NONE,
            int(timeout * 1000),
            None,
        )
    except Exception:
        return None
    if reply is None:
        return None
    value = reply.unpack()[0]
    return int(value) if isinstance(value, int) else None


def have_portal() -> bool:
    return portal_version() is not None


class PortalSession:
    """An open ScreenCast session."""

    def __init__(
        self,
        connection: Any,
        GLib: Any,
        handle: str,
        streams: list[Stream],
        *,
        restore_token: str = "",
    ) -> None:
        self.connection = connection
        self.GLib = GLib
        self.handle = handle
        self.streams = streams
        self.restore_token = restore_token
        self._fds: list[int] = []
        self._closed = False

    def __enter__(self) -> PortalSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def frame(self, stream: Stream, timeout: float = FRAME_TIMEOUT) -> Image.Image:
        """Grab one frame from a stream, trying every pipeline in turn."""

        problems: list[str] = []
        for template in PIPELINES:
            # PipeWire takes ownership of the descriptor it is handed, so give
            # it a copy and keep ours for close().
            fd = os.dup(self.pipewire_fd())
            try:
                grabber = _Grabber(fd, stream.node_id, template)
            except PortalError as exc:
                problems.append(str(exc))
                with contextlib.suppress(OSError):
                    os.close(fd)
                continue
            try:
                return grabber.grab(timeout)
            except PortalError as exc:
                problems.append(str(exc))
            finally:
                grabber.close()
        raise PortalError("无法读取 portal 画面：" + "；".join(problems))

    def frames(self, timeout: float = FRAME_TIMEOUT) -> list[Frame]:
        """Grab one frame per stream, keeping the portal's geometry."""

        frames: list[Frame] = []
        for index, stream in enumerate(self.streams):
            image = self.frame(stream, timeout)
            frames.append(Frame(image=image, output=output_for_frame(stream, image, index)))
        return frames

    def pipewire_fd(self, timeout: float = PROBE_TIMEOUT) -> int:
        Gio, GLib = _gi()
        fd = _open_pipewire_remote(Gio, GLib, self.connection, self.handle, timeout)
        self._fds.append(fd)
        return fd

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd in self._fds:
            with contextlib.suppress(OSError):
                os.close(fd)
        self._fds.clear()
        try:
            Gio, _GLib = _gi()
            self.connection.call_sync(
                BUS_NAME,
                self.handle,
                SESSION_INTERFACE,
                "Close",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                int(PROBE_TIMEOUT * 1000),
                None,
            )
        except Exception:
            pass


def _request(
    Gio: Any,
    GLib: Any,
    connection: Any,
    method: str,
    parameters: Any,
    token: str,
    timeout: float,
) -> dict[str, Any]:
    """Call one portal request method and wait for its Response signal."""

    path = request_path(connection.get_unique_name(), token)
    loop = GLib.MainLoop()
    state: dict[str, Any] = {"code": None, "results": {}, "answered": False}

    def on_response(_conn: Any, _sender: Any, _path: Any, _iface: Any, _signal: Any, params: Any) -> None:
        code, results = params.unpack()
        state["code"] = int(code)
        state["results"] = dict(results or {})
        state["answered"] = True
        loop.quit()

    def on_timeout() -> bool:
        state["expired"] = True
        loop.quit()
        return False

    subscription = connection.signal_subscribe(
        BUS_NAME,
        REQUEST_INTERFACE,
        "Response",
        path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
    )
    source = GLib.timeout_add(int(timeout * 1000), on_timeout)
    try:
        connection.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            SCREENCAST_INTERFACE,
            method,
            parameters,
            None,
            Gio.DBusCallFlags.NONE,
            int(timeout * 1000),
            None,
        )
        if not state["answered"]:
            loop.run()
    except PortalError:
        raise
    except Exception as exc:
        raise PortalError(f"portal {method} 调用失败：{exc}") from exc
    finally:
        if not state.get("expired"):
            GLib.source_remove(source)
        connection.signal_unsubscribe(subscription)

    if not state["answered"]:
        raise PortalError(f"portal {method} 在 {timeout:.0f} 秒内没有回应")
    code = int(state["code"])
    if code == RESPONSE_CANCELLED:
        raise PortalError("屏幕共享被取消")
    if code != RESPONSE_SUCCESS:
        raise PortalError(f"portal {method} 返回错误码 {code}")
    return state["results"]


def open_session(
    *,
    types: int = SOURCE_MONITOR,
    multiple: bool = False,
    cursor: int = CURSOR_EMBEDDED,
    restore_token: str = "",
    persist: int = 0,
    timeout: float = PORTAL_TIMEOUT,
) -> PortalSession:
    """Run CreateSession -> SelectSources -> Start and return the session."""

    Gio, GLib = _gi()
    connection = _connection(Gio)

    create_token = new_token("create")
    created = _request(
        Gio,
        GLib,
        connection,
        "CreateSession",
        GLib.Variant(
            "(a{sv})",
            (_typed_options(create_options(create_token, new_token("session")), GLib),),
        ),
        create_token,
        timeout,
    )
    handle = str(created.get("session_handle", ""))
    if not handle:
        raise PortalError("portal 没有返回 session_handle")

    select_token = new_token("select")
    select_args = _typed_options(
        select_options(
            select_token,
            types=types,
            multiple=multiple,
            cursor=cursor,
            restore_token=restore_token,
            persist=persist,
        ),
        GLib,
    )
    _request(
        Gio,
        GLib,
        connection,
        "SelectSources",
        GLib.Variant("(oa{sv})", (handle, select_args)),
        select_token,
        timeout,
    )

    start_token = new_token("start")
    started = _request(
        Gio,
        GLib,
        connection,
        "Start",
        GLib.Variant("(osa{sv})", (handle, "", _typed_options(start_options(start_token), GLib))),
        start_token,
        timeout,
    )
    streams = parse_streams(started.get("streams"))
    if not streams:
        with contextlib.suppress(Exception):
            connection.call_sync(
                BUS_NAME,
                handle,
                SESSION_INTERFACE,
                "Close",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                int(PROBE_TIMEOUT * 1000),
                None,
            )
        raise PortalError("portal 没有返回可用的画面流")
    return PortalSession(
        connection,
        GLib,
        handle,
        streams,
        restore_token=str(started.get("restore_token", "")),
    )


def _open_pipewire_remote(Gio: Any, GLib: Any, connection: Any, handle: str, timeout: float) -> int:
    fd_list = Gio.UnixFDList.new()
    try:
        reply, out_fds = connection.call_with_unix_fd_list_sync(
            BUS_NAME,
            OBJECT_PATH,
            SCREENCAST_INTERFACE,
            "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (handle, {})),
            GLib.VariantType("(h)"),
            Gio.DBusCallFlags.NONE,
            int(timeout * 1000),
            fd_list,
            None,
        )
    except Exception as exc:
        raise PortalError(f"portal OpenPipeWireRemote 失败：{exc}") from exc
    index = int(reply.unpack()[0])
    fds = list(out_fds.steal_fds())
    if not fds:
        raise PortalError("portal 没有返回 PipeWire 文件描述符")
    return int(fds[index if 0 <= index < len(fds) else 0])


# ------------------------------------------------------------------ GStreamer


class _Grabber:
    """A one-shot pipewiresrc -> appsink pipeline."""

    def __init__(self, fd: int, node_id: int, template: str = PIPELINES[0]) -> None:
        try:
            import gi

            gi.require_version("Gst", "1.0")
            gi.require_version("GstApp", "1.0")
            from gi.repository import Gst, GstApp
        except Exception as exc:  # pragma: no cover - depends on host
            raise PortalError(f"缺少 GStreamer Python 绑定，无法读取 portal 画面：{exc}") from exc

        Gst.init(None)
        self.Gst = Gst
        self.GstApp = GstApp
        description = template.format(fd=fd, node=node_id)
        try:
            self.pipeline = Gst.parse_launch(description)
        except Exception as exc:
            raise PortalError(f"无法创建 GStreamer 管线：{exc}") from exc
        self.sink = self.pipeline.get_by_name("catchlight-sink")
        if self.sink is None:
            raise PortalError("GStreamer 管线缺少 appsink")
        if not hasattr(self.sink, "try_pull_sample"):
            raise PortalError("GstApp 绑定不可用：无法从 appsink 取样")

    def grab(self, timeout: float = FRAME_TIMEOUT) -> Image.Image:
        self.pipeline.set_state(self.Gst.State.PLAYING)
        bus = self.pipeline.get_bus()
        deadline = time.monotonic() + timeout
        warning = ""
        while True:
            sample = self.sink.try_pull_sample(int(PULL_SECONDS * self.Gst.SECOND))
            if sample is not None:
                return _sample_to_image(sample)
            message = bus.timed_pop_filtered(0, self.Gst.MessageType.ERROR | self.Gst.MessageType.WARNING)
            if message is not None:
                if message.type == self.Gst.MessageType.ERROR:
                    error, _debug = message.parse_error()
                    raise PortalError(f"portal 画面管线出错：{error.message}{_detail(warning)}")
                warn, _debug = message.parse_warning()
                warning = warn.message
            if time.monotonic() >= deadline:
                raise PortalError(f"portal 画面在 {timeout:.0f} 秒内没有到达{_detail(warning)}")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.pipeline.set_state(self.Gst.State.NULL)


def _sample_to_image(sample: Any) -> Image.Image:
    structure = sample.get_caps().get_structure(0)
    width = int(structure.get_value("width"))
    height = int(structure.get_value("height"))
    buffer = sample.get_buffer()
    size = int(buffer.get_size())
    if width <= 0 or height <= 0 or size <= 0:
        raise PortalError("portal 返回了空画面")
    stride = size // height
    data = bytes(buffer.extract_dup(0, size))
    image = Image.frombytes("RGB", (max(1, stride // 3), height), data)
    if image.width != width:
        image = image.crop((0, 0, width, height))
    return image


# ------------------------------------------------------------------- capture


def grab_frames(
    *,
    timeout: float = PORTAL_TIMEOUT,
    multiple: bool = False,
    cursor: int = CURSOR_EMBEDDED,
) -> list[Frame]:
    """Open a session, grab one frame per shared monitor, close the session."""

    session = open_session(multiple=multiple, cursor=cursor, timeout=timeout)
    try:
        return session.frames()
    finally:
        session.close()


def capture_all(*, timeout: float = PORTAL_TIMEOUT) -> Image.Image:
    """Capture every shared monitor stitched into one desktop sized image."""

    session = open_session(multiple=True, timeout=timeout)
    try:
        if len(session.streams) > 1 and any(stream.position is None for stream in session.streams):
            raise PortalError(
                "portal 没有报告显示器位置，无法拼接全部输出；请只共享一个显示器，或用 --rect 指定区域"
            )
        frames = session.frames()
    finally:
        session.close()
    return stitch_frames(frames)


def capture_region(region: Geometry, *, timeout: float = PORTAL_TIMEOUT) -> Image.Image:
    """Capture one logical region out of the shared monitors."""

    if region.is_empty():
        raise ValueError("cannot capture an empty region")
    for frame in grab_frames(timeout=timeout, multiple=True):
        if frame.output.logical.intersects(region):
            return frame.crop_logical(region)
    raise PortalError("选区不在 portal 共享的画面里")


def capture_output(*, timeout: float = PORTAL_TIMEOUT) -> Frame:
    """Capture the first shared monitor as a Frame."""

    return grab_frames(timeout=timeout)[0]
