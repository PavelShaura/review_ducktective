from collections.abc import (
    Mapping,
    Sequence,
)
from typing import (
    Protocol,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.llm.router import (
    ModelChoice,
)


class RemoteModelSpec(Protocol):
    """Описание удалённой модели, как его хранит установка.

    Протокол, а не импорт из настроек: пакет моделей не зависит от
    конфигурации приложений, но и переписывать одно и то же преобразование
    в каждой точке входа незачем — их четыре.
    """

    name: str
    model: str
    provider: str
    base_url: str
    api_key_env: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int


def build_remote_choices(
    specs: Sequence[RemoteModelSpec],
    *,
    environment: Mapping[str, str],
) -> tuple[ModelChoice, ...]:
    """Превращает реестр в кандидатов роутера.

    Модель, чей ключ не найден в окружении, пропускается молча только
    в одном смысле — она не попадает в список; точка входа видит разницу
    между описанным и собранным и говорит о ней в журнале. Брать модель
    без ключа значило бы узнать об этом посреди прогона, отказом провайдера.

    Модели без `api_key_env` берутся как есть: локальные шлюзы и совместимые
    серверы часто не спрашивают ключа вовсе.
    """
    choices: list[ModelChoice] = []
    for spec in specs:
        api_key = environment.get(spec.api_key_env, "") if spec.api_key_env else ""
        if spec.api_key_env and not api_key:
            continue

        choices.append(
            ModelChoice(
                name=spec.name,
                model=spec.model,
                provider=spec.provider or spec.model.split("/", 1)[0],
                api_base=spec.base_url or None,
                api_key=api_key or None,
                trust=spec.trust,
                supports_tools=spec.supports_tools,
                context_window=spec.context_window,
            )
        )
    return tuple(choices)


class ResolvedModelSpec(Protocol):
    """Модель с готовым ключом — так её отдаёт хранилище организации.

    Поля объявлены свойствами, а не переменными: описание модели неизменяемо
    по построению, и протокол с изменяемыми атрибутами отверг бы его.
    """

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def provider(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    @property
    def api_key(self) -> str: ...

    @property
    def trust(self) -> ModelTrust: ...

    @property
    def supports_tools(self) -> bool: ...

    @property
    def context_window(self) -> int: ...


def build_tenant_choices(specs: Sequence[ResolvedModelSpec]) -> tuple[ModelChoice, ...]:
    """Превращает модели организации в кандидатов роутера.

    Отличие от реестра установки одно: ключ уже расшифрован и пришёл
    значением, а не именем переменной окружения.
    """
    return tuple(
        ModelChoice(
            name=spec.name,
            model=spec.model,
            provider=spec.provider or spec.model.split("/", 1)[0],
            api_base=spec.base_url or None,
            api_key=spec.api_key or None,
            trust=spec.trust,
            supports_tools=spec.supports_tools,
            context_window=spec.context_window,
        )
        for spec in specs
    )
