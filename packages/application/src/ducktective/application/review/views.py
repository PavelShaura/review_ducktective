from dataclasses import (
    dataclass,
)
from datetime import (
    datetime,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
    DiffSide,
)
from ducktective.core.review.value_objects import (
    FeedbackVerdict,
    FindingCategory,
    Severity,
)
from ducktective.core.types import (
    FindingId,
    ReviewRunId,
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
    context_side: DiffSide
    total_lines: int | None


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


@dataclass(frozen=True, kw_only=True)
class MarkedFindingView:
    """Находка вместе с последней проставленной на ней отметкой."""

    run_id: ReviewRunId
    finding_id: FindingId
    file_path: str
    line_start: int
    severity: Severity
    category: FindingCategory
    title: str
    producer_name: str
    verdict: FeedbackVerdict
    comment: str | None
    marked_at: datetime


@dataclass(frozen=True, kw_only=True)
class FeedbackDigestView:
    """Разметка находок, накопленная по репозиторию.

    Доля полезных считается от всех размеченных находок, включая отложенные:
    это precision ревьюера, и знаменатель здесь обязан совпадать с тем,
    по которому её будет считать оценка качества.
    """

    marked: tuple[MarkedFindingView, ...]
    counts: dict[str, int]
    total_findings: int

    @property
    def marked_count(self) -> int:
        return len(self.marked)

    @property
    def useful_share(self) -> float | None:
        if not self.marked:
            return None
        return self.counts.get(FeedbackVerdict.USEFUL.value, 0) / len(self.marked)
