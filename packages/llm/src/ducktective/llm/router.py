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

    context_window: int = 0
    """Сколько токенов помещается в эту модель, ноль — неизвестно.

    Величина берётся из настройки, потому что называет её сервер, а не модель:
    у `gemma-4-12b` в LM Studio `max_context_length` — 262 144, а загружена
    она была с 16 640, и считать надо по второму. Неизвестное окно требованиям
    узла не противоречит: отказать модели за то, что она о себе не рассказала,
    хуже, чем попробовать.
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
        """Модель под требования узла.

        Локальная выбирается, пока она этим требованиям отвечает: облако
        стоит денег и выпускает код наружу, поэтому уход туда обязан быть
        обоснован тем, чего локальная модель не умеет, а не общим желанием
        качества.

        При запрещённом или отсутствующем облаке узел получает локальную
        модель, даже если она его требований не выполняет: отказ оставил бы
        файл без ревью, а откат на одноразовый проход у ревьюера уже есть
        и сработает по настоящей причине — переполнению окна.
        """
        if not requirements.cloud_allowed or not self.cloud_available:
            return self._local_choice

        assert self._cloud_choice is not None
        if not self._satisfies(self._local_choice, requirements):
            return self._cloud_choice
        if not requirements.needs_deep_reasoning:
            return self._local_choice

        return self._cloud_choice

    @staticmethod
    def _satisfies(choice: ModelChoice, requirements: ModelRequirements) -> bool:
        """Отвечает ли модель тому, что попросил узел.

        Неизвестное окно считается достаточным: сервер о нём не сказал,
        а отказ по невысказанному признаку уводил бы в облако весь агентный
        режим на любой сборке, которая себя не описывает.
        """
        if requirements.needs_tool_calling and not choice.supports_tools:
            return False
        return not (
            choice.context_window and requirements.min_context_tokens > choice.context_window
        )
