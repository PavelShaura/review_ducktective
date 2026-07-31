from ducktective.core.exceptions import (
    LlmContextOverflowError,
)
from ducktective.llm.client import (
    _context_overflow_error,
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
