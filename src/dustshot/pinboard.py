"""Pin groups: move and zoom several pinned snippets as one."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MIN_SCALE = 0.15
MAX_SCALE = 4.0


class PinBoard:
    """Track pins and the groups that move or zoom together.

    A pin can be a member of at most one group. Group actions always include the
    pin that received the gesture, so callers can apply every returned target.
    """

    def __init__(self) -> None:
        self._groups: dict[str, list[Any]] = {}
        self._owner: dict[Any, str] = {}
        self._counter = 0

    # ------------------------------------------------------------ membership
    def add(self, pin: Any, group: str | None = None) -> str | None:
        """Register a pin, optionally in an existing group."""

        self.remove(pin)
        if group is None:
            return None
        members = self._groups.setdefault(group, [])
        if pin not in members:
            members.append(pin)
        self._owner[pin] = group
        return group

    def remove(self, pin: Any) -> None:
        """Forget a pin; a group left with fewer than two members disappears."""

        group = self._owner.pop(pin, None)
        if group is None:
            return
        members = self._groups.get(group)
        if members is None:
            return
        if pin in members:
            members.remove(pin)
        if len(members) < 2:
            for member in members:
                self._owner.pop(member, None)
            del self._groups[group]

    def group(self, pins: Iterable[Any]) -> str | None:
        """Put the given pins in one new group and return its id.

        Fewer than two distinct pins cannot form a group and return None; the
        pins keep their previous membership in that case.
        """

        unique: list[Any] = []
        for pin in pins:
            if pin not in unique:
                unique.append(pin)
        if len(unique) < 2:
            return None
        for pin in unique:
            self.remove(pin)
        self._counter += 1
        name = "group-" + str(self._counter)
        self._groups[name] = list(unique)
        for pin in unique:
            self._owner[pin] = name
        return name

    def ungroup(self, pin: Any) -> None:
        """Detach one pin from its group without touching the others."""

        self.remove(pin)

    def group_of(self, pin: Any) -> str | None:
        return self._owner.get(pin)

    def members(self, pin: Any) -> list[Any]:
        """Every pin that shares a gesture with `pin`, including itself."""

        group = self._owner.get(pin)
        if group is None:
            return [pin]
        members = self._groups.get(group)
        if not members:
            return [pin]
        return list(members)

    def groups(self) -> list[list[Any]]:
        return [list(members) for members in self._groups.values()]

    # -------------------------------------------------------------- gestures
    def move(self, pin: Any, x: int, y: int) -> list[tuple[Any, int, int]]:
        """Move `pin` to (x, y) and shift its group mates by the same delta.

        Coordinates are clamped to zero per pin, so a mate pushed off the top-left
        corner stops there instead of following the delta exactly.
        """

        current = getattr(pin, "position", (x, y))
        dx = int(x) - int(current[0])
        dy = int(y) - int(current[1])
        moves: list[tuple[Any, int, int]] = []
        for member in self.members(pin):
            position = getattr(member, "position", (0, 0))
            moves.append((member, max(0, int(position[0]) + dx), max(0, int(position[1]) + dy)))
        return moves

    def zoom(
        self,
        pin: Any,
        factor: float,
        minimum: float = MIN_SCALE,
        maximum: float = MAX_SCALE,
    ) -> list[tuple[Any, float]]:
        """Scale `pin` by `factor` and apply the same factor to its mates."""

        result: list[tuple[Any, float]] = []
        for member in self.members(pin):
            scale = float(getattr(member, "scale", 1.0)) * float(factor)
            result.append((member, max(minimum, min(maximum, scale))))
        return result
