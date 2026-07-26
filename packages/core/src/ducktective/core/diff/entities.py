from dataclasses import (
    dataclass,
    field,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
    LineRange,
)
from ducktective.core.types import (
    CommitSha,
)


@dataclass(frozen=True, kw_only=True)
class DiffHunk:
    """Блок изменений внутри файла в терминах unified diff."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    patch_text: str

    @property
    def new_range(self) -> LineRange | None:
        if self.new_lines == 0:
            return None
        return LineRange(start=self.new_start, end=self.new_start + self.new_lines - 1)

    @property
    def old_range(self) -> LineRange | None:
        if self.old_lines == 0:
            return None
        return LineRange(start=self.old_start, end=self.old_start + self.old_lines - 1)


@dataclass(frozen=True, kw_only=True)
class DiffFile:
    path: str
    previous_path: str | None = None
    change_type: ChangeType
    language: str | None = None
    added_lines: int = 0
    removed_lines: int = 0
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def is_reviewable(self) -> bool:
        """Удалённые файлы и файлы без блоков изменений ревьюить нечего."""
        return self.change_type is not ChangeType.DELETED and bool(self.hunks)


@dataclass(frozen=True, kw_only=True)
class Diff:
    base_sha: CommitSha
    head_sha: CommitSha
    files: list[DiffFile] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.files

    @property
    def added_lines(self) -> int:
        return sum(file.added_lines for file in self.files)

    @property
    def removed_lines(self) -> int:
        return sum(file.removed_lines for file in self.files)

    def reviewable_files(self) -> list[DiffFile]:
        return [file for file in self.files if file.is_reviewable]
