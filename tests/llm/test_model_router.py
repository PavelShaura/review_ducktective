from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
    ModelTrust,
)
from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.llm.router import (
    ModelChoice,
    ModelRouter,
)


LOCAL = ModelChoice(
    name="local",
    model="ollama/qwen2.5-coder:14b",
    provider="ollama",
    api_base="http://local",
)
PRIVATE_CLOUD = ModelChoice(
    name="sonnet",
    model="anthropic/claude-sonnet-5",
    provider="anthropic",
    api_key="secret",
    trust=ModelTrust.PRIVATE_REMOTE,
)
FREE_CLOUD = ModelChoice(
    name="free",
    model="openrouter/some-free-model:free",
    provider="openrouter",
    api_key="secret",
    trust=ModelTrust.TRAINING_REMOTE,
)

ANY_CLOUD = EgressPolicy.ALLOW_TRAINING_CLOUD.max_trust
PRIVATE_ONLY = EgressPolicy.ALLOW_CLOUD.max_trust
NO_CLOUD = EgressPolicy.LOCAL_ONLY.max_trust


def build_router(*, remote_enabled: bool = True, with_remote: bool = True) -> ModelRouter:
    return ModelRouter(
        local_choice=LOCAL,
        remote_choices=(PRIVATE_CLOUD,) if with_remote else (),
        remote_enabled=remote_enabled,
    )


def test_deep_reasoning_goes_to_the_remote_model_when_allowed() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, allowed_trust=PRIVATE_ONLY))

    assert choice is PRIVATE_CLOUD


def test_repository_policy_overrides_availability() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, allowed_trust=NO_CLOUD))

    assert choice is LOCAL


def test_airgapped_profile_never_leaves_the_machine() -> None:
    router = build_router(remote_enabled=False)

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, allowed_trust=ANY_CLOUD))

    assert choice is LOCAL
    assert router.cloud_available is False


def test_empty_registry_falls_back_to_local() -> None:
    router = build_router(with_remote=False)

    choice = router.select(ModelRequirements(needs_deep_reasoning=True, allowed_trust=ANY_CLOUD))

    assert choice is LOCAL


def test_cheap_work_stays_local() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_deep_reasoning=False, allowed_trust=ANY_CLOUD))

    assert choice is LOCAL


def test_model_that_learns_on_requests_needs_an_explicit_permission() -> None:
    """Разница между «можно облако» и «можно бесплатное» — суть D-028."""
    router = ModelRouter(
        local_choice=LOCAL,
        remote_choices=(FREE_CLOUD,),
        remote_enabled=True,
    )

    assert (
        router.select(ModelRequirements(needs_deep_reasoning=True, allowed_trust=PRIVATE_ONLY))
        is LOCAL
    )
    assert (
        router.select(ModelRequirements(needs_deep_reasoning=True, allowed_trust=ANY_CLOUD))
        is FREE_CLOUD
    )


def test_chosen_model_is_used_when_it_passes_the_policy() -> None:
    router = ModelRouter(
        local_choice=LOCAL,
        remote_choices=(PRIVATE_CLOUD, FREE_CLOUD),
        remote_enabled=True,
    )

    choice = router.select(ModelRequirements(preferred_model="free", allowed_trust=ANY_CLOUD))

    assert choice is FREE_CLOUD


def test_chosen_model_forbidden_by_the_policy_yields_to_an_allowed_one() -> None:
    """Файл без ревью хуже файла, проверенного не той моделью."""
    router = ModelRouter(
        local_choice=LOCAL,
        remote_choices=(PRIVATE_CLOUD, FREE_CLOUD),
        remote_enabled=True,
    )

    choice = router.select(ModelRequirements(preferred_model="free", allowed_trust=PRIVATE_ONLY))

    assert choice is LOCAL


def test_catalogue_shows_only_what_the_policy_allows() -> None:
    router = ModelRouter(
        local_choice=LOCAL,
        remote_choices=(PRIVATE_CLOUD, FREE_CLOUD),
        remote_enabled=True,
    )

    assert router.catalogue(allowed_trust=NO_CLOUD) == (LOCAL,)
    assert router.catalogue(allowed_trust=PRIVATE_ONLY) == (LOCAL, PRIVATE_CLOUD)
    assert router.catalogue(allowed_trust=ANY_CLOUD) == (LOCAL, PRIVATE_CLOUD, FREE_CLOUD)


TOOLLESS_LOCAL = ModelChoice(
    name="local", model="ollama/old", provider="ollama", supports_tools=False
)


def test_tool_calling_leaves_a_model_that_cannot_call_tools() -> None:
    router = ModelRouter(
        local_choice=TOOLLESS_LOCAL,
        remote_choices=(PRIVATE_CLOUD,),
        remote_enabled=True,
    )

    choice = router.select(ModelRequirements(needs_tool_calling=True, allowed_trust=PRIVATE_ONLY))

    assert choice is PRIVATE_CLOUD


def test_tool_calling_stays_local_when_the_local_model_can_call_tools() -> None:
    router = build_router()

    choice = router.select(ModelRequirements(needs_tool_calling=True, allowed_trust=PRIVATE_ONLY))

    assert choice is LOCAL


NARROW_LOCAL = ModelChoice(
    name="local",
    model="ollama/small",
    provider="ollama",
    context_window=8192,
)


def test_node_that_needs_a_wider_window_gets_the_remote_model() -> None:
    """Цикл с инструментами копит диалог и упирается там, где проходу хватало."""
    router = ModelRouter(
        local_choice=NARROW_LOCAL,
        remote_choices=(PRIVATE_CLOUD,),
        remote_enabled=True,
    )

    choice = router.select(ModelRequirements(min_context_tokens=16384, allowed_trust=PRIVATE_ONLY))

    assert choice.provider == "anthropic"


def test_window_that_fits_keeps_the_work_local() -> None:
    router = ModelRouter(
        local_choice=ModelChoice(
            name="local",
            model="ollama/wide",
            provider="ollama",
            context_window=32768,
        ),
        remote_choices=(PRIVATE_CLOUD,),
        remote_enabled=True,
    )

    choice = router.select(ModelRequirements(min_context_tokens=16384, allowed_trust=PRIVATE_ONLY))

    assert choice is not PRIVATE_CLOUD


def test_unknown_window_is_not_a_reason_to_leave() -> None:
    """Сервер о размере не сказал — это не то же самое, что «не поместится»."""
    router = build_router()

    choice = router.select(ModelRequirements(min_context_tokens=16384, allowed_trust=PRIVATE_ONLY))

    assert choice is LOCAL


def test_narrow_window_stays_local_when_the_policy_forbids_the_cloud() -> None:
    """Отказ оставил бы файл без ревью; откат на одноразовый проход есть у ревьюера."""
    router = ModelRouter(
        local_choice=NARROW_LOCAL,
        remote_choices=(PRIVATE_CLOUD,),
        remote_enabled=True,
    )

    choice = router.select(ModelRequirements(min_context_tokens=16384, allowed_trust=NO_CLOUD))

    assert choice is NARROW_LOCAL


def test_agentic_mode_knows_in_advance_that_it_has_nowhere_to_run() -> None:
    """Ответ нужен до прогона, а не на первом вызове посреди файла."""
    router = ModelRouter(
        local_choice=TOOLLESS_LOCAL,
        remote_choices=(PRIVATE_CLOUD,),
        remote_enabled=True,
    )

    assert router.supports_tool_calling(allowed_trust=PRIVATE_ONLY)
    assert not router.supports_tool_calling(allowed_trust=NO_CLOUD)
    assert build_router().supports_tool_calling(allowed_trust=NO_CLOUD)
