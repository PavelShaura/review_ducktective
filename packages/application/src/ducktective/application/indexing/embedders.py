from collections.abc import (
    Iterable,
    Sequence,
)
from dataclasses import (
    dataclass,
)
from typing import (
    Protocol,
)


class EmbedderBackend(Protocol):
    """Описание сервера эмбеддингов, каким его отдаёт конфигурация."""

    @property
    def key(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def note(self) -> str: ...
    @property
    def vector_set_name(self) -> str: ...


@dataclass(frozen=True, kw_only=True)
class EmbedderChoice:
    """Сервер эмбеддингов, каким его видит человек и индекс."""

    key: str
    title: str
    vector_set: str
    note: str = ""


@dataclass(frozen=True)
class EmbedderCatalogue:
    """Серверы эмбеддингов установки; первый — по умолчанию.

    Неизвестный ключ разрешается в сервер по умолчанию: реестр правится
    руками, а репозиторий помнит ключ, которого в нём может уже не быть.
    """

    choices: Sequence[EmbedderChoice]

    def __post_init__(self) -> None:
        if not self.choices:
            raise ValueError("Каталог эмбеддеров пуст")

    @classmethod
    def from_backends(cls, backends: Iterable[EmbedderBackend]) -> "EmbedderCatalogue":
        return cls(
            [
                EmbedderChoice(
                    key=backend.key,
                    title=backend.title,
                    vector_set=backend.vector_set_name,
                    note=backend.note,
                )
                for backend in backends
            ]
        )

    @property
    def default(self) -> EmbedderChoice:
        return self.choices[0]

    def resolve(self, key: str | None) -> EmbedderChoice:
        for choice in self.choices:
            if choice.key == key:
                return choice
        return self.default

    def is_known(self, key: str) -> bool:
        return any(choice.key == key for choice in self.choices)
