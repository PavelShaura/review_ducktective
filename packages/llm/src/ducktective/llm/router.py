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
    supports_tools: bool = True
    """Модель умеет вызывать инструменты.

    Признак задаётся настройкой, а не выясняется у сервера: локальные сборки
    отвечают на неподдерживаемое поле по-разному — от молчаливого игнорирования
    до ошибки, — и узнать правду можно только неудачным прогоном.
    """


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

    def supports_tool_calling(self, *, cloud_allowed: bool) -> bool:
        """Есть ли под эту политику модель, умеющая инструменты.

        Спрашивается до прогона: агентный ревьюер, которому не на чем работать,
        обязан честно откатиться к одноразовому проходу, а не выяснять это
        на первом же вызове посреди файла.
        """
        if self._local_choice.supports_tools:
            return True
        if not cloud_allowed or not self.cloud_available or self._cloud_choice is None:
            return False
        return self._cloud_choice.supports_tools

    def select(self, requirements: ModelRequirements) -> ModelChoice:
        if not requirements.cloud_allowed or not self.cloud_available:
            return self._local_choice

        assert self._cloud_choice is not None
        if requirements.needs_tool_calling and not self._local_choice.supports_tools:
            return self._cloud_choice
        if not requirements.needs_deep_reasoning:
            return self._local_choice

        return self._cloud_choice
