from ducktective.llm.headers import (
    OPENCODE_SESSION_HEADER,
    USER_AGENT,
    provider_headers,
)
from ducktective.llm.router import (
    ModelChoice,
)


def _choice(api_base: str | None) -> ModelChoice:
    return ModelChoice(name="remote", model="openai/x", provider="openai", api_base=api_base)


def test_opencode_gets_session_and_user_agent() -> None:
    headers = provider_headers(_choice("https://opencode.ai/zen/go/v1"), "run-42")

    assert headers[OPENCODE_SESSION_HEADER] == "run-42"
    assert headers["User-Agent"] == USER_AGENT


def test_opencode_without_session_key_still_identifies_itself() -> None:
    headers = provider_headers(_choice("https://opencode.ai/zen/v1"))

    assert headers[OPENCODE_SESSION_HEADER]
    assert headers["User-Agent"] == USER_AGENT


def test_other_providers_get_nothing() -> None:
    assert provider_headers(_choice("http://localhost:1234/v1"), "run-42") == {}
    assert provider_headers(_choice(None), "run-42") == {}
