from dataclasses import (
    dataclass,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)


@dataclass(frozen=True, kw_only=True)
class FilePatchView:
    """Патч одного файла для отображения на клиенте."""

    path: str
    previous_path: str | None
    change_type: ChangeType
    language: str | None
    added_lines: int
    removed_lines: int
    is_too_large: bool
    patch_size_bytes: int
    patch: str


@dataclass(frozen=True, kw_only=True)
class FileContextView:
    """Фрагмент файла для раскрытия контекста вокруг изменений."""

    path: str
    side: DiffSide
    commit_sha: str
    start_line: int
    end_line: int
    total_lines: int
    lines: list[str]
