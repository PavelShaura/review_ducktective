from dataclasses import (
    dataclass,
)

from ducktective.core.llm.value_objects import (
    ModelRequirements,
)


@dataclass(frozen=True, kw_only=True)
class ModelChoice:
    model: str
    provider: str
    api_base: str | None = None
    api_key: str | None = None


class ModelRouter:
    """Выбор модели под требования узла и политику репозитория.

    Облачная модель используется только тогда, когда это разрешено политикой
    конкретного репозитория и профилем развёртывания: в air-gapped режиме
    любой запрос уходит в локальную модель, даже если качество будет ниже.
    """

    def __init__(
        self,
        *,
        local_choice: ModelChoice,
        cloud_choice: ModelChoice | None = None,
        cloud_enabled: bool = False,
    ) -> None:
        self._local_choice = local_choice
        self._cloud_choice = cloud_choice
        self._cloud_enabled = cloud_enabled

    @property
    def cloud_available(self) -> bool:
        return self._cloud_enabled and self._cloud_choice is not None

    def select(self, requirements: ModelRequirements) -> ModelChoice:
        if not requirements.cloud_allowed or not self.cloud_available:
            return self._local_choice
        if not requirements.needs_deep_reasoning:
            return self._local_choice

        assert self._cloud_choice is not None
        return self._cloud_choice
