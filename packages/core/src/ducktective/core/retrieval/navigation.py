from dataclasses import (
    dataclass,
)
from enum import (
    StrEnum,
)
from typing import (
    Protocol,
)

from ducktective.core.types import (
    RepositoryId,
)


MAX_FRAGMENT_CHARS = 4000
"""Предел одного фрагмента в ответе инструмента.

Отвечают инструменты модели, у которой окно конечно, а источник фрагментов
ровных кусков не обещает: файл без определений даёт чанк на весь себя,
а совпадение грепа — строку в три тысячи символов. Предел стоит на стороне
навигатора, потому что это его обещание, а не забота вызывающего.
"""


class NavigationSource(StrEnum):
    """Чем добыт ответ.

    Едет вместе с фрагментами и попадает в подсказку модели: пустой ответ
    лексического поиска и пустой ответ обхода графа означают разное, и путать
    их — значит выдавать «греп не нашёл» за «вызывающих нет».
    """

    INDEX = "index"
    GIT = "git"


class FragmentRole(StrEnum):
    """Зачем показан фрагмент.

    Читается по-разному: вызываемое — это контракт, вызывающее — список того,
    что сломается, совпадение поиска — вероятностная догадка. Без роли всё
    это сливается в один список кусков кода, и вес каждого приходится
    угадывать по содержимому.
    """

    DEFINITION = "definition"
    CALLEE = "callee"
    CALLER = "caller"
    MATCH = "match"


@dataclass(frozen=True, kw_only=True)
class CodeFragment:
    """Кусок кода, показанный спрашивающему, вместе с его местом."""

    path: str
    start_line: int
    end_line: int
    text: str
    role: FragmentRole = FragmentRole.DEFINITION
    title: str | None = None
    """Полное имя символа или хлебные крошки — то, чем фрагмент назван."""

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


@dataclass(frozen=True, kw_only=True)
class NavigationAnswer:
    """Ответ инструмента навигации.

    Оговорка живёт рядом с фрагментами, а не в логе: приблизительные границы
    определения и урезанная выдача меняют то, как читать ответ, и сказать
    об этом нужно тому, кто его читает.
    """

    source: NavigationSource
    fragments: tuple[CodeFragment, ...] = ()
    note: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.fragments

    def of_role(self, role: FragmentRole) -> tuple[CodeFragment, ...]:
        return tuple(fragment for fragment in self.fragments if fragment.role is role)


class CodeNavigator(Protocol):
    """Операции навигации по коду одной ревизии.

    Реализация решает, чем отвечать: собранным индексом или средствами git.
    Перечень операций от этого не меняется — меняются точность и оговорки,
    поэтому вызывающий пишется один раз (D-021).
    """

    source: NavigationSource

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        """Ищет фрагменты по свободному запросу."""
        ...

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        """Показывает определение символа. Одноимённые возвращаются все."""
        ...

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        """Показывает, откуда символ вызывается, — что сломается, если его тронуть."""
        ...

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        """Показывает окружение участка файла."""
        ...


class CodeNavigatorFactory(Protocol):
    """Навигатор по конкретному репозиторию.

    Репозиторий выбирается один раз при создании, а не передаётся в каждую
    операцию: у навигатора по git его вовсе нет — там путь и ревизия.
    """

    def for_repository(self, repository_id: RepositoryId) -> CodeNavigator: ...


def clip_code(text: str, limit: int = MAX_FRAGMENT_CHARS) -> str:
    """Обрезает фрагмент, честно говоря об этом.

    Молчаливое усечение хуже обрезанного текста: модель, не знающая об остатке,
    делает вывод по половине определения и цитирует несуществующий конец.
    """
    if len(text) <= limit:
        return text

    remainder = len(text) - limit
    return f"{text[:limit].rstrip()}\n… обрезано, ещё {remainder} символов"
