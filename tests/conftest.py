"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from catchlight.config import SettingsStore


@pytest.fixture()
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "config" / "config.json")


@pytest.fixture()
def settings(store: SettingsStore):
    return store.load()
