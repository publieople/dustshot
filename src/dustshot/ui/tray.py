"""A StatusNotifierItem tray icon for Dustshot.

The icon is published on the session bus for the StatusNotifierWatcher host
(quickshell / noctalia, KDE, waybar ...) and its menu speaks
com.canonical.dbusmenu, so the host draws the menu itself. Choosing a row spawns
the matching CLI command in its own process, which keeps the tray a thin
launcher: capture, recording and the history window behave exactly as they do
from a shell.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from .. import tray as model
from ..i18n import _


class TrayError(RuntimeError):
    """The tray item could not be published on the session bus."""


SNI_XML = """<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>"""

DBUSMENU_XML = """<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
</node>"""

NAME_FLAG_DO_NOT_QUEUE = 0x4
NAME_RESULT_PRIMARY_OWNER = 1
CALL_TIMEOUT_MS = 5000


class TrayItem:
    """The StatusNotifierItem plus the dbusmenu the host renders."""

    def __init__(
        self,
        settings: Any = None,
        spawn: Callable[[tuple[str, ...]], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        application: str | None = None,
    ) -> None:
        self.settings = settings
        self._bus_names = model.item_bus_names(os.getpid(), os.environ.get("FLATPAK_ID"))
        self.bus_name = self._bus_names[0]
        self.on_quit = on_quit
        self._application = application or sys.executable
        self._spawn = spawn or self._spawn_command
        self._revision = 1
        self._icon = model.icon_pixmap(48)
        self._menu = model.entries()
        self._registrations: list[int] = []
        self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if self._connection is None:
            raise TrayError(_("连不上会话总线（DBUS_SESSION_BUS_ADDRESS 没有设置？）"))
        try:
            self._own_name()
            self._register_objects()
            self._register_with_watcher()
        except BaseException:
            self.close()
            raise

    def _own_name(self) -> None:
        problems = []
        for name in self._bus_names:
            try:
                reply = self._connection.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "RequestName",
                    GLib.Variant("(su)", (name, NAME_FLAG_DO_NOT_QUEUE)),
                    None,
                    Gio.DBusCallFlags.NONE,
                    CALL_TIMEOUT_MS,
                    None,
                )
            except GLib.Error as exc:
                # A sandbox denies the org.kde name, so the item falls back to its own id.
                problems.append(f"{name}: {exc.message}")
                continue
            if reply.unpack()[0] == NAME_RESULT_PRIMARY_OWNER:
                self.bus_name = name
                return
            problems.append(_("总线名 {bus_name} 已被占用").format(bus_name=name))
        raise TrayError(_("无法获得会话总线名：{detail}").format(detail="；".join(problems)))

    def _register_objects(self) -> None:
        item = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_XML).interfaces[0]
        self._registrations.append(
            self._connection.register_object(
                model.ITEM_PATH, item, self._on_item_call, self._on_item_property, None
            )
        )
        self._registrations.append(
            self._connection.register_object(
                model.MENU_PATH, menu, self._on_menu_call, self._on_menu_property, None
            )
        )

    def _register_with_watcher(self) -> None:
        try:
            self._connection.call_sync(
                model.WATCHER_NAME,
                model.WATCHER_PATH,
                model.WATCHER_NAME,
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self.bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                CALL_TIMEOUT_MS,
                None,
            )
        except GLib.Error as exc:
            raise TrayError(
                _("会话总线上没有托盘宿主（{WATCHER_NAME}）：{message}").format(
                    WATCHER_NAME=model.WATCHER_NAME, message=exc.message
                )
            ) from exc

    # ----------------------------------------------------------------- item

    def _on_item_property(self, _connection, _sender, _path, _interface, name, *_rest):
        pixmaps = [(self._icon[0], self._icon[1], self._icon[2])]
        if name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if name == "Id":
            return GLib.Variant("s", "dustshot")
        if name == "Title":
            return GLib.Variant("s", model.TITLE)
        if name == "Status":
            return GLib.Variant("s", "Active")
        if name == "WindowId":
            return GLib.Variant("i", 0)
        if name in {"IconName", "OverlayIconName", "AttentionIconName", "AttentionMovieName"}:
            return GLib.Variant("s", "")
        if name == "IconPixmap":
            return GLib.Variant("a(iiay)", pixmaps)
        if name in {"OverlayIconPixmap", "AttentionIconPixmap"}:
            return GLib.Variant("a(iiay)", [])
        if name == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", ("", pixmaps, model.TITLE, model.TOOLTIP))
        if name == "ItemIsMenu":
            return GLib.Variant("b", False)
        if name == "Menu":
            return GLib.Variant("o", model.MENU_PATH)
        return None

    def _on_item_call(self, _connection, _sender, _path, _interface, method, parameters, invocation):
        if method == "Activate":
            self._activate(1)
        elif method == "SecondaryActivate":
            self._activate(5)
        invocation.return_value(None)

    # ----------------------------------------------------------------- menu

    def _on_menu_property(self, _connection, _sender, _path, _interface, name, *_rest):
        if name == "Version":
            return GLib.Variant("u", 4)
        if name == "TextDirection":
            return GLib.Variant("s", "ltr")
        if name == "Status":
            return GLib.Variant("s", "normal")
        if name == "IconThemePath":
            return GLib.Variant("as", [])
        return None

    def _on_menu_call(self, _connection, _sender, _path, _interface, method, parameters, invocation):
        if method == "GetLayout":
            parent, depth, _names = parameters.unpack()
            layout = self._layout(parent, depth)
            invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("u", self._revision), layout))
            return
        if method == "GetGroupProperties":
            ids, _names = parameters.unpack()
            wanted = ids or [row.id for row in self._menu]
            rows = [(row_id, self._properties(row_id)) for row_id in wanted]
            invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("a(ia{sv})", rows)))
            return
        if method == "GetProperty":
            row_id, name = parameters.unpack()
            value = self._properties(row_id).get(name)
            if value is None:
                invocation.return_value(GLib.Variant("(v)", (GLib.Variant("s", ""),)))
                return
            invocation.return_value(GLib.Variant("(v)", (value,)))
            return
        if method == "Event":
            row_id, event_id, _data, _timestamp = parameters.unpack()
            if event_id == "clicked":
                self._activate(int(row_id))
            invocation.return_value(None)
            return
        if method == "EventGroup":
            (events,) = parameters.unpack()
            for row_id, event_id, _data, _timestamp in events:
                if event_id == "clicked":
                    self._activate(int(row_id))
            invocation.return_value(GLib.Variant("(ai)", ([],)))
            return
        if method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
            return
        if method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
            return
        invocation.return_value(None)

    def _properties(self, row_id: int) -> dict[str, GLib.Variant]:
        if row_id == model.MENU_ROOT:
            return {"children-display": GLib.Variant("s", "submenu")}
        row = model.entry(row_id)
        if row is None:
            return {}
        if row.separator:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", row.label)}

    def _layout(self, row_id: int, depth: int) -> GLib.Variant:
        children: list[Any] = []
        if row_id == model.MENU_ROOT:
            properties = self._properties(model.MENU_ROOT)
            if depth != 0:
                children = [self._layout(row.id, depth - 1) for row in self._menu]
        else:
            properties = self._properties(row_id)
        return GLib.Variant.new_tuple(
            GLib.Variant("i", row_id), GLib.Variant("a{sv}", properties), GLib.Variant("av", children)
        )

    # -------------------------------------------------------------- actions

    def _activate(self, row_id: int) -> None:
        if model.is_quit(row_id):
            self.close()
            if self.on_quit is not None:
                self.on_quit()
            return
        command = model.command_for(row_id)
        if command is not None:
            self._spawn(command)

    def _spawn_command(self, command: tuple[str, ...]) -> None:
        subprocess.Popen([self._application, "-m", "dustshot.cli", *command], start_new_session=True)

    def close(self) -> None:
        if self._connection is None:
            return
        for registration in self._registrations:
            with contextlib.suppress(Exception):
                self._connection.unregister_object(registration)
        self._registrations = []
        with contextlib.suppress(Exception):
            self._connection.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ReleaseName",
                GLib.Variant("(s)", (self.bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
        self._connection = None


def _signal_source():
    # PyGObject moved this off GLib, and its callbacks arrive positionally.
    try:
        gi.require_version("GLibUnix", "2.0")
    except ValueError:  # pragma: no cover - missing on old PyGObject
        return GLib.unix_signal_add
    from gi.repository import GLibUnix

    return GLibUnix.signal_add


def _stop(loop: GLib.MainLoop) -> bool:
    loop.quit()
    return False


def run_tray(settings: Any = None) -> int:
    """Publish the tray item and run until the menu quits it."""

    loop = GLib.MainLoop()
    try:
        item = TrayItem(settings, on_quit=loop.quit)
    except TrayError as exc:
        print(_("托盘图标不可用：{exc}").format(exc=exc), file=sys.stderr)
        return 1
    for number in (signal.SIGINT, signal.SIGTERM):
        _signal_source()(GLib.PRIORITY_DEFAULT, number, _stop, loop)
    print(
        _("托盘图标已注册：{bus_name}（在菜单里选「退出托盘」，或按 Ctrl+C 结束）").format(
            bus_name=item.bus_name
        ),
        file=sys.stderr,
    )
    try:
        loop.run()
    finally:
        item.close()
    return 0
