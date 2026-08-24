from dataclasses import (
    dataclass,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.llm.registry import (
    build_tenant_choices,
)


@dataclass(frozen=True, kw_only=True)
class Spec:
    name: str
    model: str
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    supports_tools: bool = True
    context_window: int = 0


def test_bare_identifier_gets_its_provider_in_front() -> None:
    """Перечень провайдера отдаёт голые имена, а по ним адресат неизвестен."""
    choices = build_tenant_choices(
        [Spec(name="go/kimi-k3", model="kimi-k3", provider="openai", base_url="https://x/v1")]
    )

    assert choices[0].model == "openai/kimi-k3"
    assert choices[0].api_base == "https://x/v1"


def test_identifier_that_already_names_a_provider_is_left_alone() -> None:
    choices = build_tenant_choices(
        [Spec(name="sonnet", model="anthropic/claude-sonnet-5", provider="anthropic")]
    )

    assert choices[0].model == "anthropic/claude-sonnet-5"


def test_own_server_is_addressed_as_openai_compatible() -> None:
    """Другого протокола у собственного адреса не бывает."""
    choices = build_tenant_choices(
        [Spec(name="gateway/my-model", model="my-model", base_url="https://gateway/v1")]
    )

    assert choices[0].model == "openai/my-model"
    assert choices[0].provider == "openai"
