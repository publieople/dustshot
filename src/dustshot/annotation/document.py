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

from ..capture.base import Geometry
from ..config import AnnotationSettings
from .items import Item, SerialItem, items_from_jsonable, items_to_jsonable
from .render import render

PROJECT_SUFFIX = ".cln"
FORMAT_VERSION = 1
MAX_HISTORY = 200

#: Crop and rotate replace the base image, so those history entries carry it.
#: A full screen frame is about 12 MiB, hence a much smaller cap than MAX_HISTORY.
MAX_IMAGE_HISTORY = 12

#: One undo entry: the base image (None when the step did not touch it) and the
#: annotation list. Images are never mutated in place, so referencing them is safe.
_Snapshot = tuple[Image.Image | None, list[dict[str, Any]]]


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
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
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

    def crop(self, box: Geometry) -> bool:
        """Keep only the given rectangle and move the annotations with it."""

        box = box.clamped(self.base.width, self.base.height)
        if box.is_empty() or box.as_tuple() == (0, 0, self.base.width, self.base.height):
            return False
        self.push_undo(self.base)
        self.base = self.base.crop(box.as_pil_box())
        for item in self.items:
            item.move(-box.x, -box.y)
        self.items = [item for item in self.items if _overlaps(item, self.base.size)]
        self.touch()
        return True

    def rotate(self, turns: int = 1) -> bool:
        """Rotate the picture by whole quarter turns; negative goes anticlockwise."""

        steps = turns % 4
        if steps == 0:
            return False
        self.push_undo(self.base)
        for _ in range(steps):
            size = (self.base.width, self.base.height)
            self.base = self.base.transpose(Image.Transpose.ROTATE_270)
            for item in self.items:
                item.rotate_quarter(size, clockwise=True)
        self.touch()
        return True

    # ------------------------------------------------------------------- history
    def _snapshot(self, base: Image.Image | None = None) -> _Snapshot:
        return (base, items_to_jsonable(self.items))

    def push_undo(self, base: Image.Image | None = None) -> None:
        self._undo.append(self._snapshot(base))
        if len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        self._trim_image_history()
        self._redo.clear()
        self.touch()

    def _trim_image_history(self) -> None:
        """Drop the oldest undo entries once too many base images are pinned."""

        images = [index for index, (image, _items) in enumerate(self._undo) if image is not None]
        if len(images) > MAX_IMAGE_HISTORY:
            del self._undo[: images[0] + 1]

    def _rewind(self, source: list[_Snapshot], target: list[_Snapshot]) -> bool:
        if not source:
            return False
        base, items = source.pop()
        # Going back over a crop or a rotation has to hand the current image on
        # to the opposite stack, so redoing puts the same picture back.
        target.append((self.base if base is not None else None, items_to_jsonable(self.items)))
        if base is not None:
            self.base = base
        self.items = items_from_jsonable(items)
        self.touch()
        return True

    def undo(self) -> bool:
        return self._rewind(self._undo, self._redo)

    def redo(self) -> bool:
        return self._rewind(self._redo, self._undo)

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


def _overlaps(item: Item, size: tuple[int, int]) -> bool:
    """True when the item still touches a picture of the given size."""

    box = item.bbox()
    return box.right > 0 and box.bottom > 0 and box.x < size[0] and box.y < size[1]


def _png_bytes(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
