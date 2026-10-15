"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dustshot import i18n
from dustshot.config import SettingsStore


@pytest.fixture(autouse=True)
def untranslated_interface(monkeypatch):
    """Pin the interface language so no test depends on the ambient locale.

    gettext maps a C/POSIX environment onto en_US, so a CI runner with LANG=C.UTF-8
    picks up the English catalogue and breaks the assertions that expect the source
    strings.  LANGUAGE=zz names a catalogue that cannot exist, which makes every
    lookup fall back to the original message; the tests that exercise the plumbing
    ask for their language explicitly.
    """

    monkeypatch.setenv("LANGUAGE", "zz")
    monkeypatch.delenv(i18n.LANGUAGE_VARIABLE, raising=False)
    original = i18n._translation
    i18n.install()
    yield
    i18n._translation = original


@pytest.fixture()
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "config" / "config.json")


@pytest.fixture()
def settings(store: SettingsStore):
    return store.load()
