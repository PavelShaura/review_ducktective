from dataclasses import (
    dataclass,
)
from enum import (
    StrEnum,
)

from ducktective.core.exceptions import (
    InvariantViolationError,
)


class ChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class DiffSide(StrEnum):
    """Сторона диффа: находка может относиться к удалённому или к новому коду."""

    OLD = "old"
    NEW = "new"


@dataclass(frozen=True, kw_only=True)
class LineRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 1:
            raise InvariantViolationError("Нумерация строк начинается с единицы")
        if self.end < self.start:
            raise InvariantViolationError("Конец диапазона строк раньше начала")

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end

    def overlaps(self, other: "LineRange") -> bool:
        return self.start <= other.end and other.start <= self.end
