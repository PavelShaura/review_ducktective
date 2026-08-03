from uuid import (
    uuid4,
)

from ducktective.core.exceptions import (
    LlmContextOverflowError,
    LlmInvocationError,
    LlmOutputError,
    LlmOutputTruncatedError,
    LlmRateLimitError,
    LlmTimeoutError,
    LlmUnavailableError,
    VcsOperationError,
)
from ducktective.core.review.degradation import (
    DegradationKind,
    NodeDegradation,
    ReviewStage,
    classify_failure,
    failing_model,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    ReviewSource,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    TenantId,
)
from ducktective.storage.mappers.review import (
    _config_from_domain,
    _degradations_to_domain,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    MODIFIED_AND_ADDED_PATCH,
)


def test_truncated_answer_is_not_confused_with_unparsed_one() -> None:
    """Обрыв на лимите наследует ошибке разбора, а лечится иначе."""
    assert classify_failure(LlmOutputTruncatedError("оборван")) is DegradationKind.OUTPUT_EXHAUSTED
    assert classify_failure(LlmOutputError("не разобран")) is DegradationKind.INVALID_OUTPUT


def test_every_way_the_model_can_fail_has_its_own_kind() -> None:
    assert classify_failure(LlmContextOverflowError("окно")) is DegradationKind.CONTEXT_OVERFLOW
    assert classify_failure(LlmTimeoutError("молчит")) is DegradationKind.TIMEOUT
    assert classify_failure(LlmRateLimitError("часто")) is DegradationKind.RATE_LIMITED
    assert classify_failure(LlmUnavailableError("нет")) is DegradationKind.PROVIDER_UNAVAILABLE


def test_unfamiliar_failure_is_named_unknown_instead_of_guessed() -> None:
    assert classify_failure(VcsOperationError("git отказал")) is DegradationKind.UNKNOWN
    assert classify_failure(LlmInvocationError("что-то ещё")) is DegradationKind.UNKNOWN


def test_model_is_taken_from_the_error_instead_of_its_wording() -> None:
    assert failing_model(LlmTimeoutError("молчит", model="lm_studio/qwen")) == "lm_studio/qwen"
    assert failing_model(VcsOperationError("git отказал")) is None


def build_review_run() -> ReviewRun:
    return ReviewRun.create(
        tenant_id=TenantId(uuid4()),
        repository_id=RepositoryId(uuid4()),
        source=ReviewSource.LOCAL_DIFF,
        diff=UnifiedDiffParser().parse(
            MODIFIED_AND_ADDED_PATCH,
            base_sha=CommitSha("a" * 40),
            head_sha=CommitSha("b" * 40),
        ),
    )


def build_mark(**overrides: object) -> NodeDegradation:
    fields: dict[str, object] = {
        "stage": ReviewStage.REVIEW,
        "file_path": "app/service.py",
        "kind": DegradationKind.TIMEOUT,
        "detail": "Модель lm_studio/qwen не ответила за 180 с",
        "reviewer": "reviewer:security",
        "model": "lm_studio/qwen",
    }
    fields.update(overrides)
    return NodeDegradation(**fields)  # type: ignore[arg-type]


def test_marks_survive_the_trip_through_jsonb() -> None:
    run = build_review_run()
    run.record_node_failures([build_mark()])

    assert _degradations_to_domain(_config_from_domain(run)) == [build_mark()]


def test_run_without_failures_keeps_its_config_empty() -> None:
    assert _config_from_domain(build_review_run()) == {}


def test_unreadable_mark_does_not_take_the_run_down_with_it() -> None:
    """Прогон открывают ради находок, а не ради служебного поля."""
    stored = _config_from_domain_with([{"stage": "неизвестный этап"}, "мусор"])

    assert _degradations_to_domain(stored) == []


def _config_from_domain_with(entries: list[object]) -> dict[str, object]:
    return {"degradations": entries}
