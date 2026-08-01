from enum import (
    StrEnum,
)


class ReviewSource(StrEnum):
    PULL_REQUEST = "pull_request"
    LOCAL_DIFF = "local_diff"
    UPLOAD = "upload"


class ReviewStatus(StrEnum):
    QUEUED = "queued"
    INDEXING = "indexing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Severity(StrEnum):
    """Уровень находки.

    Определяется по рубрике: находка, которая не может объяснить, что именно
    сломается, понижается в уровне.
    """

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    NITPICK = "nitpick"


class FindingCategory(StrEnum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STYLE = "style"
    TESTS = "tests"
    ARCHITECTURE = "architecture"


class FindingStatus(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"
    PUBLISHED = "published"


class FindingProducer(StrEnum):
    LLM = "llm"
    STATIC_ANALYZER = "static_analyzer"


class FeedbackVerdict(StrEnum):
    """Оценка находки человеком. Источник данных для eval-набора."""

    USEFUL = "useful"
    FALSE_POSITIVE = "false_positive"
    WONTFIX = "wontfix"


class EvidenceKind(StrEnum):
    RETRIEVED_CHUNK = "retrieved_chunk"
    QUOTED_CODE = "quoted_code"
    TOOL_OUTPUT = "tool_output"


SEVERITY_RANK = {
    Severity.CRITICAL: 3,
    Severity.MAJOR: 2,
    Severity.MINOR: 1,
    Severity.NITPICK: 0,
}
"""Порядок уровней от старшего к младшему.

Нужен там, где находки сравниваются между собой: порог `--fail-on`, отбор
представителя при слиянии дублей.
"""


TERMINAL_STATUSES = frozenset(
    {
        ReviewStatus.COMPLETED,
        ReviewStatus.FAILED,
        ReviewStatus.CANCELLED,
    }
)

RESTARTABLE_STATUSES = frozenset(
    {
        ReviewStatus.FAILED,
        ReviewStatus.CANCELLED,
    }
)
"""Завершившиеся не своей волей.

Успешный прогон не перезапускается: его результат — то, ради чего дело
заводили, и затирать его повторным чтением тех же файлов незачем.
"""
