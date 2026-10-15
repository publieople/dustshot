"""The annotation document: a base image plus an ordered list of annotations.

Undo and redo use whole-list snapshots. Annotations are small dictionaries, so
snapshotting is cheap and cannot drift out of sync the way per-command inverse
operations can. Documents can be saved to a small zip archive (.cln) that holds
the pristine base image and the annotation list, which makes a capture
re-editable after the fact.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import AnnotationSettings
from .items import Item, SerialItem, items_from_jsonable, items_to_jsonable
from .render import render

PROJECT_SUFFIX = ".cln"
FORMAT_VERSION = 1
MAX_HISTORY = 200


class Document:
    """Editable annotation state for one captured image."""

    def __init__(
        self,
        image: Image.Image,
        settings: AnnotationSettings | None = None,
        items: Sequence[Item] | None = None,
        source: str = "",
    ) -> None:
        self.base = image.convert("RGB")
        self.settings = settings or AnnotationSettings()
        self.items: list[Item] = list(items or [])
        self.source = source
        self._undo: list[list[dict[str, Any]]] = []
        self._redo: list[list[dict[str, Any]]] = []
        self.serial_counter = max(1, int(self.settings.serial_start))
        self.revision = 0

    def touch(self) -> int:
        """Mark the document as changed so renderers can drop their cache."""

        self.revision += 1
        return self.revision

    # ------------------------------------------------------------------ geometry
    @property
    def size(self) -> tuple[int, int]:
        return self.base.size

    @property
    def dirty(self) -> bool:
        return bool(self.items)

    def contains(self, x: float, y: float) -> bool:
        return 0 <= x < self.size[0] and 0 <= y < self.size[1]

    # ------------------------------------------------------------------- history
    def _snapshot(self) -> list[dict[str, Any]]:
        return items_to_jsonable(self.items)

    def push_undo(self) -> None:
        self._undo.append(self._snapshot())
        if len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()
        self.touch()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self.items = items_from_jsonable(self._undo.pop())
        self.touch()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self.items = items_from_jsonable(self._redo.pop())
        self.touch()
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    # ------------------------------------------------------------------- editing
    def add(self, item: Item) -> Item:
        self.push_undo()
        self.items.append(item)
        self.touch()
        return item

    def update(self, item: Item) -> None:
        for index, existing in enumerate(self.items):
            if existing.id == item.id:
                self.push_undo()
                self.items[index] = item
                self.touch()
                return

    def remove(self, item_id: str) -> bool:
        for index, existing in enumerate(self.items):
            if existing.id == item_id:
                self.push_undo()
                del self.items[index]
                self.touch()
                return True
        return False

    def remove_last(self) -> bool:
        if not self.items:
            return False
        self.push_undo()
        self.items.pop()
        self.touch()
        return True

    def clear(self) -> None:
        if not self.items:
            return
        self.push_undo()
        self.items.clear()
        self.touch()

    def last(self) -> Item | None:
        return self.items[-1] if self.items else None

    def hit_test(self, x: float, y: float) -> Item | None:
        """Return the topmost item whose bounding box contains the point."""

        for item in reversed(self.items):
            if item.bbox().contains_point(x, y):
                return item
        return None

    def next_serial(self) -> int:
        value = self.serial_counter
        self.serial_counter += 1
        return value

    def add_serial(self, x: float, y: float, size: int | None = None) -> SerialItem:
        from .items import Style

        size = size or self.settings.serial_size
        item = SerialItem(
            x=round(x - size / 2),
            y=round(y - size / 2),
            number=self.next_serial(),
            size=size,
            style=Style(color=self.settings.color, width=self.settings.shape_width),
        )
        return self.add(item)  # type: ignore[return-value]

    # ------------------------------------------------------------------ rendering
    def render(self, keep_alpha: bool = False) -> Image.Image:
        return render(self.base, self.items, keep_alpha=keep_alpha)

    # ---------------------------------------------------------------- persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "source": self.source,
            "image_size": list(self.size),
            "serial_counter": self.serial_counter,
            "items": items_to_jsonable(self.items),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        image: Image.Image,
        settings: AnnotationSettings | None = None,
    ) -> Document:
        document = cls(
            image,
            settings=settings,
            items=items_from_jsonable(data.get("items", [])),
            source=str(data.get("source", "")),
        )
        document.serial_counter = int(data.get("serial_counter", 1))
        return document

    def save_project(self, path: str | Path) -> Path:
        path = Path(path)
        if path.suffix != PROJECT_SUFFIX:
            path = path.with_suffix(PROJECT_SUFFIX)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = json.dumps(self.to_dict(), indent=2).encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("annotations.json", meta)
            archive.writestr("image.png", _png_bytes(self.base))
        return path

    @classmethod
    def load_project(cls, path: str | Path, settings: AnnotationSettings | None = None) -> Document:
        path = Path(path)
        with zipfile.ZipFile(path, "r") as archive:
            meta = json.loads(archive.read("annotations.json").decode("utf-8"))
            import io

            image = Image.open(io.BytesIO(archive.read("image.png"))).convert("RGB")
        document = cls.from_dict(meta, image, settings=settings)
        document.source = str(path)
        return document


def _png_bytes(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
