"""Tests for the optional gtk4-layer-shell plumbing."""

from __future__ import annotations

from dustshot.ui import layer


def _no_find_library(monkeypatch):
    monkeypatch.setattr("ctypes.util.find_library", lambda _name: None)


def test_the_loader_path_is_searched_first(monkeypatch, tmp_path):
    monkeypatch.setenv("LD_LIBRARY_PATH", str(tmp_path))
    directories = layer.library_dirs()
    assert directories[0] == str(tmp_path)
    assert "/app/lib" in layer.LIBRARY_DIRS


def test_library_path_finds_a_sandbox_copy(monkeypatch, tmp_path):
    library = tmp_path / "libgtk4-layer-shell.so.0"
    library.write_bytes(b"")
    monkeypatch.setenv("LD_LIBRARY_PATH", str(tmp_path))
    _no_find_library(monkeypatch)
    assert layer.library_path() == str(library)


def test_library_path_is_none_without_a_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("LD_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setattr(layer, "LIBRARY_DIRS", ())
    _no_find_library(monkeypatch)
    assert layer.library_path() is None


def test_a_bare_soname_is_not_treated_as_a_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LD_LIBRARY_PATH", str(tmp_path))
    monkeypatch.setattr(layer, "LIBRARY_DIRS", ())
    monkeypatch.setattr("ctypes.util.find_library", lambda _name: "libgtk4-layer-shell.so.0")
    assert layer.library_path() is None


def test_preload_active_reads_the_environment(monkeypatch):
    monkeypatch.delenv("LD_PRELOAD", raising=False)
    assert layer.preload_active() is False
    monkeypatch.setenv("LD_PRELOAD", "libgtk4-layer-shell.so.0")
    assert layer.preload_active() is True


def test_ensure_preload_respects_the_escape_hatch(monkeypatch):
    monkeypatch.setenv("DUSTSHOT_NO_REEXEC", "1")
    monkeypatch.delenv("LD_PRELOAD", raising=False)
    assert layer.ensure_preload() is False
