"""The StatusNotifierItem server, exercised across process boundaries.

A synchronous D-Bus call from a connection to itself never dispatches its own
handler, so pytest talks to a tray item and to a stub watcher that each live in a
process of their own:

    dbus-run-session -- python -m pytest tests/test_tray_dbus.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

gi = pytest.importorskip("gi")

gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from catchlight import tray as model

ROOT = Path(__file__).resolve().parents[1]
HELPER = Path(__file__).with_name("tray_process.py")
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
TIMEOUT_MS = 5000

pytestmark = pytest.mark.skipif(
    not os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    reason="需要一个会话总线（用 dbus-run-session 跑）",
)


def _connection():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _spawn(role: str, *arguments: str) -> subprocess.Popen:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    return subprocess.Popen(
        [sys.executable, str(HELPER), role, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


def _wait_for(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _property(connection, service: str, path: str, interface: str, name: str):
    reply = connection.call_sync(
        service,
        path,
        "org.freedesktop.DBus.Properties",
        "Get",
        GLib.Variant("(ss)", (interface, name)),
        GLib.VariantType.new("(v)"),
        Gio.DBusCallFlags.NONE,
        TIMEOUT_MS,
        None,
    )
    return reply.unpack()[0]


def _call(connection, service: str, path: str, interface: str, method: str, parameters, signature=None):
    reply = connection.call_sync(
        service,
        path,
        interface,
        method,
        parameters,
        GLib.VariantType.new(signature) if signature else None,
        Gio.DBusCallFlags.NONE,
        TIMEOUT_MS,
        None,
    )
    return None if reply is None else reply.unpack()


def _has_name(connection, name: str) -> bool:
    reply = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (name,)),
        None,
        Gio.DBusCallFlags.NONE,
        TIMEOUT_MS,
        None,
    )
    return bool(reply.unpack()[0])


def _click(connection, service: str, row_id: int) -> None:
    _call(
        connection,
        service,
        model.MENU_PATH,
        "com.canonical.dbusmenu",
        "Event",
        GLib.Variant("(isvu)", (row_id, "clicked", GLib.Variant("s", ""), 0)),
    )


@pytest.fixture(scope="module")
def watcher():
    if _has_name(_connection(), WATCHER_NAME):
        pytest.skip("会话总线上已经有托盘宿住在运行")
    process = _spawn("watcher")
    first = process.stdout.readline().strip()
    assert first == "ready", first
    yield
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture()
def bus():
    return _connection()


@pytest.fixture()
def item(watcher, tmp_path: Path):
    log = tmp_path / "spawned.log"
    process = _spawn("item", str(log))
    first = process.stdout.readline().strip()
    assert first.startswith(model.BUS_PREFIX), first
    handle = SimpleNamespace(process=process, name=first, log=log)
    yield handle
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)


def test_item_registers_itself_with_the_watcher(watcher, bus, item):
    registered = _property(
        bus, WATCHER_NAME, model.WATCHER_PATH, WATCHER_NAME, "RegisteredStatusNotifierItems"
    )
    assert registered == [item.name]
    assert (
        _property(bus, WATCHER_NAME, model.WATCHER_PATH, WATCHER_NAME, "IsStatusNotifierHostRegistered")
        is True
    )


def test_item_publishes_the_sni_properties(watcher, bus, item):
    assert _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "Id") == "catchlight"
    assert _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "Title") == model.TITLE
    assert _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "Status") == "Active"
    assert (
        _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "Category")
        == "ApplicationStatus"
    )
    assert _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "ItemIsMenu") is False
    assert _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "Menu") == model.MENU_PATH
    pixmaps = _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "IconPixmap")
    assert len(pixmaps) == 1
    width, height, data = pixmaps[0]
    assert (width, height) == (48, 48)
    assert len(data) == 48 * 48 * 4
    tooltip = _property(bus, item.name, model.ITEM_PATH, "org.kde.StatusNotifierItem", "ToolTip")
    assert tooltip[2] == model.TITLE
    assert tooltip[3] == model.TOOLTIP


def test_menu_layout_mirrors_the_model(watcher, bus, item):
    revision, layout = _call(
        bus,
        item.name,
        model.MENU_PATH,
        "com.canonical.dbusmenu",
        "GetLayout",
        GLib.Variant("(iias)", (model.MENU_ROOT, -1, [])),
        "(u(ia{sv}av))",
    )
    assert revision >= 1
    root_id, root_properties, children = layout
    assert root_id == model.MENU_ROOT
    assert root_properties["children-display"] == "submenu"
    assert [child[0] for child in children] == [row.id for row in model.entries()]
    assert children[0][1]["label"] == "区域截图"
    assert len([child for child in children if child[1].get("type") == "separator"]) == 2


def test_group_properties_reports_labels(watcher, bus, item):
    (rows,) = _call(
        bus,
        item.name,
        model.MENU_PATH,
        "com.canonical.dbusmenu",
        "GetGroupProperties",
        GLib.Variant("(aias)", ([1, 5], [])),
        "(a(ia{sv}))",
    )
    assert {row_id: properties["label"] for row_id, properties in rows} == {
        1: "区域截图",
        5: "截图历史",
    }


def test_layout_depth_zero_lists_no_children(watcher, bus, item):
    _revision, layout = _call(
        bus,
        item.name,
        model.MENU_PATH,
        "com.canonical.dbusmenu",
        "GetLayout",
        GLib.Variant("(iias)", (model.MENU_ROOT, 0, [])),
        "(u(ia{sv}av))",
    )
    assert layout[2] == []


def test_clicking_a_row_spawns_its_command(watcher, bus, item):
    _click(bus, item.name, 5)
    assert _wait_for(lambda: item.log.read_text().strip() == "history --gui")


def test_event_group_dispatches_every_click(watcher, bus, item):
    _call(
        bus,
        item.name,
        model.MENU_PATH,
        "com.canonical.dbusmenu",
        "EventGroup",
        GLib.Variant("(a(isvu))", ([(1, "clicked", GLib.Variant("s", ""), 0)],)),
        "(ai)",
    )
    assert _wait_for(lambda: item.log.read_text().strip() == "region")


def test_activate_runs_the_region_capture(watcher, bus, item):
    _call(
        bus,
        item.name,
        model.ITEM_PATH,
        "org.kde.StatusNotifierItem",
        "Activate",
        GLib.Variant("(ii)", (0, 0)),
    )
    assert _wait_for(lambda: item.log.read_text().strip() == "region")


def test_quit_row_stops_the_item_and_releases_its_name(watcher, bus, item):
    _click(bus, item.name, model.QUIT_ID)
    assert item.process.wait(timeout=10) == 0
    assert _wait_for(lambda: not _has_name(bus, item.name), timeout=5)
