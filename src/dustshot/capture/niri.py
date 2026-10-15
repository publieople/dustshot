"""Capture through niri's own screenshot picker.

niri's IPC has no request that hands back pixels: `niri msg action screenshot` opens the
compositor picker and the finished crop goes to the clipboard and, when a path was given, to
that file. We pass an explicit path so the frame arrives somewhere deterministic, and
`screenshot-screen` -- which has no picker -- is read back from the clipboard it fills.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from ..i18n import _
from .base import in_flatpak
from .screencopy import CaptureError, niri_path

UI_TIMEOUT = 120.0
SCREEN_TIMEOUT = 5.0
IPC_TIMEOUT = 5.0
ACTION_TIMEOUT = 30.0
POLL = 0.1


def have_niri() -> bool:
    return shutil.which(niri_path()) is not None


def ipc_alive(timeout: float = IPC_TIMEOUT) -> bool:
    """True when a running compositor answers on the niri IPC socket."""

    try:
        result = subprocess.run(
            [niri_path(), "msg", "version"], capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def ui_available() -> bool:
    """True when niri can open its picker for us."""

    return not in_flatpak() and have_niri() and ipc_alive()


def ui_command(path: Path, show_pointer: bool = False) -> list[str]:
    """The action that opens niri's picker and saves the crop to *path*."""

    return [
        niri_path(),
        "msg",
        "action",
        "screenshot",
        "--path",
        str(path),
        "--show-pointer",
        "true" if show_pointer else "false",
    ]


def screen_command() -> list[str]:
    """The action that screenshots the focused output without a picker."""

    return [niri_path(), "msg", "action", "screenshot-screen", "--write-to-disk", "false"]


def _run(cmd: Sequence[str], timeout: float = ACTION_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:  # pragma: no cover - depends on host tooling
        raise CaptureError(_("找不到 niri 命令：{path}").format(path=cmd[0])) from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - depends on host tooling
        raise CaptureError(_("niri 命令超时：{path}").format(path=cmd[0])) from exc


def _detail(result: subprocess.CompletedProcess[bytes]) -> str:
    text = (
        result.stderr.decode("utf-8", "replace").strip() or result.stdout.decode("utf-8", "replace").strip()
    )
    return text or str(result.returncode)


def require_niri() -> None:
    """Raise a CaptureError unless the compositor picker can be driven from here."""

    if in_flatpak():
        raise CaptureError(_("niri 后端不可用：Flatpak 沙箱里连不上合成器的 IPC"))
    if not have_niri():
        raise CaptureError(_("niri 后端不可用：找不到 niri 命令"))
    if not ipc_alive():
        raise CaptureError(_("niri 后端不可用：niri 的 IPC 没有响应"))


def request_ui(path: Path, show_pointer: bool = False) -> None:
    """Ask the compositor to open its picker, saving the crop to *path*."""

    result = _run(ui_command(path, show_pointer))
    if result.returncode != 0:
        raise CaptureError(_("无法打开 niri 截图界面：{detail}").format(detail=_detail(result)))


def wait_for_file(path: Path, timeout: float = UI_TIMEOUT, poll: float = POLL) -> bool:
    """Wait until the compositor has written a non-empty screenshot to *path*."""

    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            if path.exists() and path.stat().st_size > 0:
                return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


def capture_ui(timeout: float = UI_TIMEOUT, show_pointer: bool = False) -> Image.Image:
    """Open niri's picker and return the frame the user saved there.

    The compositor writes our private temporary file when the user confirms with Space; a
    cancelled picker never writes anything, so the wait ends at *timeout*.
    """

    require_niri()
    directory = Path(tempfile.mkdtemp(prefix="dustshot-niri-"))
    target = directory / "shot.png"
    try:
        request_ui(target, show_pointer)
        if not wait_for_file(target, timeout):
            raise CaptureError(_("niri 截图超时（界面可能已取消）"))
        with Image.open(target) as handle:
            handle.load()
            return handle.convert("RGB")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _same_image(one: Image.Image | None, other: Image.Image | None) -> bool:
    if one is None or other is None:
        return one is other
    return one.size == other.size and one.tobytes() == other.tobytes()


def capture_screen() -> Image.Image:
    """Screenshot the focused output without opening the picker.

    niri only writes to disk when `screenshot-path` is configured, so the frame is read back
    from the clipboard the compositor fills.
    """

    from ..clipboard import paste_image

    require_niri()
    before = paste_image()
    result = _run(screen_command())
    if result.returncode != 0:
        raise CaptureError(_("niri 截图失败：{detail}").format(detail=_detail(result)))

    deadline = time.monotonic() + SCREEN_TIMEOUT
    while True:
        image = paste_image()
        if image is not None and not _same_image(image, before):
            return image
        if time.monotonic() >= deadline:
            raise CaptureError(_("没有从剪贴板读到 niri 的截图"))
        time.sleep(POLL)
