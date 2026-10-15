"""Capture history bookkeeping."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from catchlight.history import MAX_ENTRIES, History


def make_history(tmp_path: Path) -> History:
    return History(tmp_path / "history.json")


def test_add_and_recent(tmp_path: Path) -> None:
    history = make_history(tmp_path)
    for index in range(3):
        history.add(tmp_path / f"shot{index}.png", 100 + index, 200, kind="region")

    recent = history.recent(limit=2)
    assert len(recent) == 2
    assert recent[0].width == 102
    assert recent[1].width == 101


def test_save_and_load(tmp_path: Path) -> None:
    history = make_history(tmp_path)
    history.add(tmp_path / "shot.png", 10, 20, kind="full", note="hello")
    history.save()

    again = History(tmp_path / "history.json")
    again.load()
    assert len(again.entries) == 1
    assert again.entries[0].kind == "full"
    assert again.entries[0].note == "hello"


def test_record_image_uses_size(tmp_path: Path) -> None:
    history = make_history(tmp_path)
    image = Image.new("RGB", (64, 48), (0, 0, 0))
    entry = history.record_image(tmp_path / "shot.png", image, kind="editor")
    assert (entry.width, entry.height) == (64, 48)
    assert entry.kind == "editor"


def test_last_region_reads_note(tmp_path: Path) -> None:
    history = make_history(tmp_path)
    history.add(tmp_path / "shot.png", 300, 200, kind="region", note=json.dumps([10, 20, 300, 200]))
    assert history.last_region() == [10, 20, 300, 200]


def test_prune_removes_missing_files(tmp_path: Path) -> None:
    history = make_history(tmp_path)
    existing = tmp_path / "here.png"
    existing.write_bytes(b"x")
    history.add(existing, 10, 10)
    history.add(tmp_path / "gone.png", 10, 10)
    removed = history.prune()
    assert removed == 1
    assert len(history.entries) == 1


def test_max_entries_is_enforced(tmp_path: Path) -> None:
    history = make_history(tmp_path)
    for index in range(MAX_ENTRIES + 5):
        history.add(tmp_path / f"shot{index}.png", 10, 10)
    assert len(history.entries) == MAX_ENTRIES
