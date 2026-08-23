from collections.abc import (
    Sequence,
)
from dataclasses import (
    dataclass,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.llm.value_objects import (
    ModelRequirements,
)


@dataclass(frozen=True, kw_only=True)
class ModelChoice:
    name: str
    """Имя, под которым модель видна человеку и приходит из его выбора."""

    model: str
    provider: str
    api_base: str | None = None
    api_key: str | None = None
    trust: ModelTrust = ModelTrust.LOCAL
    """Насколько далеко уедет код, если спросить эту модель.

    У локальной сборки — никуда. У платного провайдера с обязательством не
    хранить запросы — `private_remote`. У бесплатного тира — `training_remote`:
    отсутствие обещания считается обучением, потому что обратное проверить
    нечем (D-028).
    """

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

    Кандидатов столько, сколько описано в настройках: локальная сборка плюс
    любое число удалённых. Удалённая берётся только тогда, когда её уровень
    доверия разрешён политикой репозитория **и** локальная требований узла
    не выполняет: код, уехавший наружу, назад не возвращается, и повод для
    этого должен быть назван, а не подразумеваться.
    """

    def __init__(
        self,
        *,
        local_choice: ModelChoice,
        remote_choices: Sequence[ModelChoice] = (),
        remote_enabled: bool = False,
    ) -> None:
        self._local_choice = local_choice
        self._remote_choices = tuple(remote_choices)
        self._remote_enabled = remote_enabled

    @property
    def cloud_available(self) -> bool:
        return self._remote_enabled and bool(self._remote_choices)

    def catalogue(
        self, *, allowed_trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    ) -> tuple[
        ModelChoice,
        ...,
    ]:
        """Модели, которые вообще можно предложить при такой политике.

        Нужен интерфейсу: выбирать модель человек должен из того, что
        разрешено репозиторию, а не из всего списка с отказом после запуска.
        """
        return (self._local_choice, *self._allowed_remotes(allowed_trust))

    def supports_tool_calling(self, *, allowed_trust: ModelTrust) -> bool:
        """Есть ли под эту политику модель, умеющая инструменты.

        Спрашивается до прогона: агентный ревьюер, которому не на чем работать,
        обязан честно откатиться к одноразовому проходу, а не выяснять это
        на первом же вызове посреди файла.
        """
        return any(choice.supports_tools for choice in self.catalogue(allowed_trust=allowed_trust))

    def select(self, requirements: ModelRequirements) -> ModelChoice:
        """Модель под требования узла.

        Локальная выбирается, пока она этим требованиям отвечает: удалённая
        стоит денег и выпускает код наружу, поэтому уход туда обязан быть
        обоснован тем, чего локальная модель не умеет, а не общим желанием
        качества.

        Выбор человека уважается, если проходит по политике и требованиям:
        он видел список и решил сам. Не прошедший молча уступает подходящей —
        отказ оставил бы файл без ревью, а это хуже ревью не той моделью.
        """
        candidates = self.catalogue(allowed_trust=requirements.allowed_trust)
        named = self._named(requirements.preferred_model, candidates)
        if named is not None and _satisfies(named, requirements):
            return named

        if _satisfies(self._local_choice, requirements) and not requirements.needs_deep_reasoning:
            return self._local_choice

        for choice in self._allowed_remotes(requirements.allowed_trust):
            if _satisfies(choice, requirements):
                return choice

        return self._local_choice

    def alternatives(
        self,
        requirements: ModelRequirements,
        *,
        besides: ModelChoice,
    ) -> tuple[ModelChoice, ...]:
        """Кандидаты, которыми можно заменить отказавшую модель.

        Нужны там, где отказ провайдера — обычное дело, а не поломка:
        бесплатные тиры считают запросы, и заведённая рядом вторая модель
        существует ровно для этого случая. Порядок сохраняется: сначала
        локальная, потом удалённые в порядке реестра.
        """
        return tuple(
            choice
            for choice in self.catalogue(allowed_trust=requirements.allowed_trust)
            if choice is not besides and _satisfies(choice, requirements)
        )

    def _allowed_remotes(self, allowed_trust: ModelTrust) -> tuple[ModelChoice, ...]:
        if not self._remote_enabled:
            return ()
        return tuple(
            choice for choice in self._remote_choices if choice.trust.is_allowed_by(allowed_trust)
        )

    @staticmethod
    def _named(name: str | None, candidates: Sequence[ModelChoice]) -> ModelChoice | None:
        if not name:
            return None
        for choice in candidates:
            if choice.name == name:
                return choice
        return None


def _satisfies(choice: ModelChoice, requirements: ModelRequirements) -> bool:
    """Отвечает ли модель тому, что попросил узел.

    Неизвестное окно считается достаточным: сервер о нём не сказал,
    а отказ по невысказанному признаку уводил бы в облако весь агентный
    режим на любой сборке, которая себя не описывает.
    """
    if requirements.needs_tool_calling and not choice.supports_tools:
        return False
    if choice.context_window and requirements.min_context_tokens > choice.context_window:
        return False
    return choice.trust.is_allowed_by(requirements.allowed_trust)
