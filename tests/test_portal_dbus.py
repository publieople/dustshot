"""Cross-process tests for the ScreenCast portal client.

The client runs in this process and the portal is a small fake in another one,
because a process cannot call itself over D-Bus. Run under a private bus:

    dbus-run-session -- python3 -m pytest tests/test_portal_dbus.py
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from catchlight.capture import portal

pytestmark = pytest.mark.skipif(not os.environ.get("DBUS_SESSION_BUS_ADDRESS"), reason="需要一个会话总线")

ROOT = Path(__file__).resolve().parents[1]
HELPER = Path(__file__).with_name("portal_process.py")


def _portal_is_owned() -> bool:
    """True when a real portal already owns the name, so the fake cannot."""

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (portal.BUS_NAME,)),
        GLib.VariantType("(b)"),
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )
    return bool(reply.unpack()[0])


def _spawn(log: Path, mode: str = "normal") -> subprocess.Popen:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.Popen(
        [sys.executable, str(HELPER), "portal", str(log), mode],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    assert process.stdout is not None
    line = process.stdout.readline().strip()
    if line != "ready":
        process.kill()
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise AssertionError(f"fake portal did not start: {line!r} {stderr}")
    return process


@pytest.fixture()
def fake(tmp_path: Path) -> Path:
    if _portal_is_owned():
        pytest.skip("真实 portal 正在运行，无法用假 portal 占用总线名")
    log = tmp_path / "portal.jsonl"
    process = _spawn(log)
    yield log
    process.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)


def _calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_client_runs_the_whole_screencast_dance(fake: Path) -> None:
    session = portal.open_session(multiple=True, timeout=15)
    try:
        assert session.handle.startswith("/org/freedesktop/portal/desktop/session/")
        assert session.restore_token == "restore-me"
        assert len(session.streams) == 1
        stream = session.streams[0]
        assert (stream.node_id, stream.size, stream.position) == (7, (64, 48), (1920, 0))

        fd = session.pipewire_fd(timeout=15)
        assert os.read(fd, 32) == b"portal-fd-ok"
    finally:
        session.close()

    entries = _calls(fake)
    assert [entry["method"] for entry in entries] == [
        "CreateSession",
        "SelectSources",
        "Start",
        "OpenPipeWireRemote",
        "Close",
    ]
    create = entries[0]["options"]
    assert set(create) == {"handle_token", "session_handle_token"}
    assert entries[1]["session"] == session.handle
    assert entries[1]["options"]["types"] == portal.SOURCE_MONITOR
    assert entries[1]["options"]["cursor_mode"] == portal.CURSOR_EMBEDDED
    assert entries[1]["options"]["multiple"] is True
    assert set(entries[2]["options"]) == {"handle_token"}
    assert entries[2]["parent"] == ""
    assert entries[3]["session"] == session.handle
    assert entries[4]["session"] == session.handle


def test_portal_version_probe_reads_the_property(fake: Path) -> None:
    assert portal.portal_version(timeout=15) == 5
    assert portal.have_portal() is True


def test_a_cancelled_share_raises(tmp_path: Path) -> None:
    if _portal_is_owned():
        pytest.skip("真实 portal 正在运行，无法用假 portal 占用总线名")
    log = tmp_path / "cancel.jsonl"
    process = _spawn(log, mode="cancel")
    try:
        with pytest.raises(portal.PortalError, match="屏幕共享被取消"):
            portal.open_session(timeout=15)
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
