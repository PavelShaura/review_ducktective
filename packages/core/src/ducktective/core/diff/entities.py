from collections.abc import (
    Sequence,
)
from dataclasses import (
    dataclass,
    field,
)
from fnmatch import (
    fnmatch,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
    LineRange,
)
from ducktective.core.types import (
    CommitSha,
)


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


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

    def include_only(self, patterns: Sequence[str]) -> "Diff":
        """Оставляет файлы, чей путь совпал хотя бы с одним шаблоном.

        Используется fnmatch, где `*` покрывает и разделители каталогов: шаблон
        `src/*.py` найдёт файл на любой глубине внутри `src`. Пустой список
        шаблонов ничего не отсекает.
        """
        if not patterns:
            return self

        return Diff(
            base_sha=self.base_sha,
            head_sha=self.head_sha,
            files=[file for file in self.files if _matches_any(file.path, patterns)],
        )
