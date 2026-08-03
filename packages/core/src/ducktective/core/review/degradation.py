from dataclasses import (
    dataclass,
)
from enum import (
    StrEnum,
)

from ducktective.core.exceptions import (
    DomainError,
    LlmContextOverflowError,
    LlmInvocationError,
    LlmOutputError,
    LlmOutputTruncatedError,
    LlmRateLimitError,
    LlmTimeoutError,
    LlmUnavailableError,
)


class ReviewStage(StrEnum):
    """Этап конвейера из `05-review-pipeline.md`.

    Имена совпадают с именами узлов графа: отметка о деградации называет
    место сбоя, и называть его иначе, чем оно называется в логе прогона,
    значит заводить второй словарь для того же самого.
    """

    BUILD_CONTEXT = "build_context"
    PLAN_REVIEW = "plan_review"
    REVIEW = "review"
    AGGREGATE = "aggregate"
    VERIFY = "verify"


class DegradationKind(StrEnum):
    """Почему этап не отработал.

    Вид, а не текст: одно и то же переполнение окна приходит от разных
    провайдеров разными словами, а лечится одинаково. Совет, который
    показывается человеку, привязан к виду.
    """

    CONTEXT_OVERFLOW = "context_overflow"
    OUTPUT_EXHAUSTED = "output_exhausted"
    INVALID_OUTPUT = "invalid_output"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class NodeDegradation:
    """Что именно не отработало на одном файле.

    Прогон продолжается без упавшего узла, поэтому одной причины на прогон
    мало: с четырьмя ревьюерами «часть файлов не прочитана» не говорит ни
    кто не прочитал, ни какой из них, а чинятся эти случаи по-разному.
    """

    stage: ReviewStage
    file_path: str
    kind: DegradationKind
    detail: str
    reviewer: str | None = None
    model: str | None = None


_KINDS_BY_ERROR: tuple[tuple[type[DomainError], DegradationKind], ...] = (
    (LlmContextOverflowError, DegradationKind.CONTEXT_OVERFLOW),
    (LlmOutputTruncatedError, DegradationKind.OUTPUT_EXHAUSTED),
    (LlmOutputError, DegradationKind.INVALID_OUTPUT),
    (LlmTimeoutError, DegradationKind.TIMEOUT),
    (LlmRateLimitError, DegradationKind.RATE_LIMITED),
    (LlmUnavailableError, DegradationKind.PROVIDER_UNAVAILABLE),
)


def classify_failure(error: DomainError) -> DegradationKind:
    """Вид деградации по типу ошибки.

    Порядок проверки — от частного к общему: обрыв на лимите наследует
    ошибке разбора, и общее правило поглотило бы его.
    """
    for error_type, kind in _KINDS_BY_ERROR:
        if isinstance(error, error_type):
            return kind
    return DegradationKind.UNKNOWN


def failing_model(error: DomainError) -> str | None:
    """Модель, отказавшая на этом файле, если ошибка её называет."""
    if isinstance(error, LlmInvocationError | LlmOutputError):
        return error.model
    return None
