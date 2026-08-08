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


def test_agentic_mode_knows_in_advance_that_it_has_nowhere_to_run() -> None:
    """Ответ нужен до прогона, а не на первом вызове посреди файла."""
    router = ModelRouter(local_choice=TOOLLESS_LOCAL, cloud_choice=CLOUD, cloud_enabled=True)

    assert router.supports_tool_calling(cloud_allowed=True)
    assert not router.supports_tool_calling(cloud_allowed=False)
    assert build_router().supports_tool_calling(cloud_allowed=False)
