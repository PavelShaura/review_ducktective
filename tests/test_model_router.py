from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.llm.router import (
    ModelChoice,
    ModelRouter,
)


LOCAL = ModelChoice(model="ollama/qwen2.5-coder:14b", provider="ollama", api_base="http://local")
CLOUD = ModelChoice(model="anthropic/claude-sonnet-5", provider="anthropic", api_key="secret")


def build_router(*, cloud_enabled: bool = True, with_cloud: bool = True) -> ModelRouter:
    return ModelRouter(
        local_choice=LOCAL,
        cloud_choice=CLOUD if with_cloud else None,
        cloud_enabled=cloud_enabled,
    )


def test_deep_reasoning_goes_to_cloud_when_allowed() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, cloud_allowed=True))

    assert choice is CLOUD


def test_repository_policy_overrides_availability() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, cloud_allowed=False))

    assert choice is LOCAL


def test_airgapped_profile_never_uses_cloud() -> None:
    router = build_router(cloud_enabled=False)

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, cloud_allowed=True))

    assert choice is LOCAL
    assert router.cloud_available is False


def test_missing_cloud_configuration_falls_back_to_local() -> None:
    router = build_router(with_cloud=False)

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, cloud_allowed=True))

    assert choice is LOCAL


def test_cheap_work_stays_local() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_deep_reasoning=False, cloud_allowed=True))

    assert choice is LOCAL


TOOLLESS_LOCAL = ModelChoice(model="ollama/old", provider="ollama", supports_tools=False)


def test_tool_calling_leaves_a_model_that_cannot_call_tools() -> None:
    router = ModelRouter(local_choice=TOOLLESS_LOCAL, cloud_choice=CLOUD, cloud_enabled=True)

    choice = router.select(ModelRequirements(needs_tool_calling=True, cloud_allowed=True))

    assert choice is CLOUD


def test_tool_calling_stays_local_when_the_local_model_can_call_tools() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_tool_calling=True, cloud_allowed=True))

    assert choice is LOCAL


NARROW_LOCAL = ModelChoice(model="ollama/small", provider="ollama", context_window=8192)


def test_node_that_needs_a_wider_window_gets_the_cloud_model() -> None:
    """Цикл с инструментами копит диалог и упирается там, где проходу хватало."""
    router = ModelRouter(
        local_choice=NARROW_LOCAL,
        cloud_choice=ModelChoice(model="anthropic/claude-sonnet-5", provider="anthropic"),
        cloud_enabled=True,
    )

    choice = router.select(ModelRequirements(min_context_tokens=16384, cloud_allowed=True))

    assert choice.provider == "anthropic"


def test_window_that_fits_keeps_the_work_local() -> None:
    router = ModelRouter(
        local_choice=ModelChoice(model="ollama/wide", provider="ollama", context_window=32768),
        cloud_choice=CLOUD,
        cloud_enabled=True,
    )

    choice = router.select(ModelRequirements(min_context_tokens=16384, cloud_allowed=True))

    assert choice is not CLOUD


def test_unknown_window_is_not_a_reason_to_leave() -> None:
    """Сервер о размере не сказал — это не то же самое, что «не поместится»."""
    router = build_router()

    choice = router.select(ModelRequirements(min_context_tokens=16384, cloud_allowed=True))

    assert choice is LOCAL


def test_narrow_window_stays_local_when_the_policy_forbids_the_cloud() -> None:
    """Отказ оставил бы файл без ревью; откат на одноразовый проход есть у ревьюера."""
    router = ModelRouter(local_choice=NARROW_LOCAL, cloud_choice=CLOUD, cloud_enabled=True)

    choice = router.select(ModelRequirements(min_context_tokens=16384, cloud_allowed=False))

    assert choice is NARROW_LOCAL


def test_agentic_mode_knows_in_advance_that_it_has_nowhere_to_run() -> None:
    """Ответ нужен до прогона, а не на первом вызове посреди файла."""
    router = ModelRouter(local_choice=TOOLLESS_LOCAL, cloud_choice=CLOUD, cloud_enabled=True)

    assert router.supports_tool_calling(cloud_allowed=True)
    assert not router.supports_tool_calling(cloud_allowed=False)
    assert build_router().supports_tool_calling(cloud_allowed=False)
