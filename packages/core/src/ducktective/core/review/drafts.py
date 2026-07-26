from dataclasses import (
    dataclass,
    field,
)

from ducktective.core.diff.value_objects import (
    DiffSide,
)
from ducktective.core.review.value_objects import (
    FindingCategory,
    Severity,
)


@dataclass(frozen=True, kw_only=True)
class EvidenceDraft:
    file_path: str
    snippet: str
    line_start: int | None = None
    line_end: int | None = None


@dataclass(frozen=True, kw_only=True)
class FindingDraft:
    """Находка, предложенная ревьюером, но ещё не принятая в прогон.

    Отделена от Finding намеренно: черновик приходит извне и может быть отброшен
    проверкой доказательств, дедупликацией или привязкой к строкам вне диффа.
    """

    file_path: str
    line_start: int
    line_end: int
    side: DiffSide
    severity: Severity
    category: FindingCategory
    title: str
    body_markdown: str
    anchor_symbol: str | None = None
    code_fragment: str = ""
    suggested_patch: str | None = None
    confidence: float | None = None
    evidence: list[EvidenceDraft] = field(default_factory=list)
