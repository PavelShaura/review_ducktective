from types import (
    SimpleNamespace,
)

from litellm.exceptions import (
    RateLimitError,
    Timeout,
)

from ducktective.core.exceptions import (
    LlmContextOverflowError,
)
from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.llm.client import (
    LiteLlmClient,
    _build_response,
    _context_overflow_error,
    _mentions_context_overflow,
)
from ducktective.llm.code_reviewer import (
    _truncated_error,
)
from ducktective.llm.router import (
    ModelChoice,
    ModelRouter,
)


LM_STUDIO_MESSAGE = (
    "litellm.ContextWindowExceededError: litellm.BadRequestError: "
    "ContextWindowExceededError: Lm_studioException - Error code: 400 - "
    "{'error': 'Engine protocol predict request returned 400: "
    '{"error":{"code":400,"message":"request (19389 tokens) exceeds the available '
    'context size (16384 tokens), try increasing it","type":"exceed_context_size_error",'
    '"n_prompt_tokens":19389,"n_ctx":16384}}\'}'
)


def test_context_overflow_reports_both_sizes() -> None:
    error = _context_overflow_error("lm_studio/qwen", Exception(LM_STUDIO_MESSAGE))

    assert isinstance(error, LlmContextOverflowError)
    assert "19389" in str(error)
    assert "16384" in str(error)


def test_context_overflow_survives_unknown_message_format() -> None:
    error = _context_overflow_error("lm_studio/qwen", Exception("prompt is too long"))

    assert isinstance(error, LlmContextOverflowError)
    assert "lm_studio/qwen" in str(error)


def _completion(finish_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"findings": []}'),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=4096),
    )


def test_response_hitting_the_output_limit_is_marked_truncated() -> None:
    choice = ModelChoice(model="lm_studio/qwen", provider="lm_studio")

    assert _build_response(_completion("length"), choice, 10).is_truncated
    assert not _build_response(_completion("stop"), choice, 10).is_truncated


def test_truncated_answer_names_the_limit_instead_of_the_schema() -> None:
    error = _truncated_error("lm_studio/qwen", ModelRequirements(max_output_tokens=4096))

    assert "4096" in str(error)
    assert "lm_studio/qwen" in str(error)
    assert "схеме" not in str(error)


def _client(timeout_seconds: float = 180.0) -> LiteLlmClient:
    router = ModelRouter(local_choice=ModelChoice(model="lm_studio/qwen", provider="lm_studio"))
    return LiteLlmClient(router, timeout_seconds=timeout_seconds)


def test_timeout_is_reported_as_timeout() -> None:
    error = _client()._unavailable_error(
        "lm_studio/qwen",
        Timeout(message="timed out", model="qwen", llm_provider="lm_studio"),
    )

    assert "не ответила за 180 с" in str(error)


def test_other_failures_keep_the_generic_wording() -> None:
    error = _client()._unavailable_error("lm_studio/qwen", ConnectionError("отказано"))

    assert "недоступна" in str(error)
    assert "отказано" in str(error)


def test_rate_limit_is_named_separately() -> None:
    error = _client()._unavailable_error(
        "lm_studio/qwen",
        RateLimitError(message="slow down", model="qwen", llm_provider="lm_studio"),
    )

    assert "частоту" in str(error)


LM_STUDIO_STREAM_MESSAGE = (
    "litellm.BadRequestError: Lm_studioException - Error code: 400 - "
    "{'error': 'Engine protocol predict stream returned an error: "
    '{"code":500,"message":"Context size has been exceeded.","type":"server_error"}\'}'
)


def test_overflow_disguised_as_a_plain_bad_request_is_recognised() -> None:
    """LM Studio отдаёт переполнение обычным BadRequestError.

    По типу исключения оно неотличимо от «провайдер отказал», а чинится
    совсем иначе — окном модели. Совет в интерфейсе выбирается по виду
    причины, поэтому назвать её верно важнее, чем удобно.
    """
    assert _mentions_context_overflow(LM_STUDIO_STREAM_MESSAGE)
    assert _mentions_context_overflow(LM_STUDIO_MESSAGE)


def test_ordinary_failure_is_not_taken_for_an_overflow() -> None:
    assert not _mentions_context_overflow("Connection refused")
    assert not _mentions_context_overflow("model not found")
