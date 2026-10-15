"""A small index of recent captures.

Only metadata is stored; the images themselves live wherever the user saved
them. This powers the history browser and the restore-last-region shortcut.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import data_dir

MAX_ENTRIES = 500


@dataclass
class HistoryEntry:
    path: str
    created: float
    width: int
    height: int
    bytes: int = 0
    kind: str = "image"
    project: str = ""
    note: str = ""

    def exists(self) -> bool:
        return Path(self.path).exists()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        return cls(
            path=str(data.get("path", "")),
            created=float(data.get("created", 0.0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            bytes=int(data.get("bytes", 0)),
            kind=str(data.get("kind", "image")),
            project=str(data.get("project", "")),
            note=str(data.get("note", "")),
        )


class History:
    """JSON backed capture index."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else data_dir() / "history.json"
        self.entries: list[HistoryEntry] = []

    def load(self) -> list[HistoryEntry]:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                self.entries = [HistoryEntry.from_dict(entry) for entry in payload.get("entries", [])]
            except (OSError, ValueError):
                self.entries = []
        return self.entries

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": [entry.to_dict() for entry in self.entries[:MAX_ENTRIES]]}
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.path

    def add(
        self,
        path: str | Path,
        width: int,
        height: int,
        kind: str = "image",
        project: str = "",
        note: str = "",
        created: float | None = None,
    ) -> HistoryEntry:
        target = Path(path)
        size = target.stat().st_size if target.exists() else 0
        entry = HistoryEntry(
            path=str(target),
            created=created if created is not None else time.time(),
            width=width,
            height=height,
            bytes=size,
            kind=kind,
            project=project,
            note=note,
        )
        self.entries.insert(0, entry)
        del self.entries[MAX_ENTRIES:]
        self.save()
        return entry

    def record_image(self, path: str | Path, image, **kwargs: Any) -> HistoryEntry:
        width, height = image.size
        return self.add(path, width, height, **kwargs)

    def recent(self, limit: int = 20) -> list[HistoryEntry]:
        return self.entries[:limit]

    def prune(self) -> int:
        """Drop entries whose files vanished; returns how many were removed."""

        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.exists()]
        removed = before - len(self.entries)
        if removed:
            self.save()
        return removed

    def last_region(self) -> list[int]:
        for entry in self.entries:
            if entry.kind == "region" and entry.note:
                try:
                    values = json.loads(entry.note)
                except ValueError:
                    continue
                if isinstance(values, list) and len(values) == 4:
                    return [int(v) for v in values]
        return []
