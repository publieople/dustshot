"""niri's own screenshot picker as a capture backend."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from dustshot.capture import niri


def test_ui_command_asks_for_our_private_file() -> None:
    target = Path("/tmp/dustshot-niri-test/shot.png")
    command = niri.ui_command(target)
    assert command[:4] == [niri.niri_path(), "msg", "action", "screenshot"]
    assert command[command.index("--path") + 1] == str(target)
    assert command[command.index("--show-pointer") + 1] == "false"
    assert niri.ui_command(target, show_pointer=True)[-1] == "true"


def test_screen_command_keeps_the_compositor_off_the_disk() -> None:
    assert niri.screen_command()[:4] == [niri.niri_path(), "msg", "action", "screenshot-screen"]
    assert niri.screen_command()[-2:] == ["--write-to-disk", "false"]


def test_wait_for_file_needs_a_non_empty_file(tmp_path: Path) -> None:
    target = tmp_path / "shot.png"
    assert niri.wait_for_file(target, timeout=0.0) is False
    target.write_bytes(b"")
    assert niri.wait_for_file(target, timeout=0.0) is False
    target.write_bytes(b"png")
    assert niri.wait_for_file(target, timeout=0.0) is True


def test_capture_ui_returns_what_the_picker_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[Path] = []

    def fake_request(path: Path, show_pointer: bool = False) -> None:
        written.append(path)
        Image.new("RGB", (4, 3), "red").save(path)

    monkeypatch.setattr(niri, "require_niri", lambda: None)
    monkeypatch.setattr(niri, "request_ui", fake_request)
    image = niri.capture_ui(timeout=1.0)
    assert image.size == (4, 3)
    assert written
    assert not written[0].exists()  # the private temporary directory is gone


def test_capture_ui_reports_a_cancelled_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niri, "require_niri", lambda: None)
    monkeypatch.setattr(niri, "request_ui", lambda path, show_pointer=False: None)
    with pytest.raises(niri.CaptureError):
        niri.capture_ui(timeout=0.05)


def test_capture_ui_fails_loudly_without_niri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niri, "in_flatpak", lambda: True)
    with pytest.raises(niri.CaptureError):
        niri.capture_ui(timeout=0.05)


def test_capture_screen_waits_for_a_new_clipboard_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    from dustshot import clipboard as clipboard_module

    before = Image.new("RGB", (2, 2), "black")
    after = Image.new("RGB", (5, 4), "white")
    frames = [before, before, after]

    monkeypatch.setattr(niri, "require_niri", lambda: None)
    monkeypatch.setattr(
        niri,
        "_run",
        lambda command, timeout=niri.ACTION_TIMEOUT: subprocess.CompletedProcess(command, 0, b"", b""),
    )
    monkeypatch.setattr(clipboard_module, "paste_image", lambda: frames.pop(0) if frames else after)

    assert niri.capture_screen().size == (5, 4)


def test_capture_screen_reports_a_silent_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    from dustshot import clipboard as clipboard_module

    monkeypatch.setattr(niri, "require_niri", lambda: None)
    monkeypatch.setattr(niri, "SCREEN_TIMEOUT", 0.0)
    monkeypatch.setattr(niri, "_run", lambda command, timeout=niri.ACTION_TIMEOUT: _done(command))
    monkeypatch.setattr(clipboard_module, "paste_image", lambda: None)
    with pytest.raises(niri.CaptureError):
        niri.capture_screen()


def _done(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(command, 0, b"", b"")


def test_ui_available_is_false_inside_a_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niri, "in_flatpak", lambda: True)
    monkeypatch.setattr(niri, "have_niri", lambda: True)
    monkeypatch.setattr(niri, "ipc_alive", lambda timeout=niri.IPC_TIMEOUT: True)
    assert niri.ui_available() is False


def test_ui_available_follows_the_ipc_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niri, "in_flatpak", lambda: False)
    monkeypatch.setattr(niri, "have_niri", lambda: True)
    monkeypatch.setattr(niri, "ipc_alive", lambda timeout=niri.IPC_TIMEOUT: False)
    assert niri.ui_available() is False
    monkeypatch.setattr(niri, "ipc_alive", lambda timeout=niri.IPC_TIMEOUT: True)
    assert niri.ui_available() is True
