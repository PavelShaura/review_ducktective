from dataclasses import (
    dataclass,
)
from enum import (
    StrEnum,
)
from pathlib import (
    Path,
)
from typing import (
    Protocol,
)

from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.core.types import (
    RepositoryId,
)


MAX_FRAGMENT_CHARS = 4000
"""Предел фрагмента, размер которого навигатор выбирает сам: совпадения
поиска и определения. Явно названный диапазон строк отдаётся целиком,
его обрезает вызывающий (D-030).
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
    SUBCLASS = "subclass"
    IMPORTER = "importer"
    RAISER = "raiser"
    DECORATED = "decorated"
    RELATED = "related"
    SOURCE = "source"
    NAME = "name"


class ReferenceRelation(StrEnum):
    """Чем именно ссылаются на символ.

    Перечень короче, чем видов рёбер в графе: спрашивают о том, что меняет
    решение. «Кто наследует этот класс» и «кто импортирует этот модуль» —
    разные последствия правки, а `references` не спрашивают вовсе, потому
    что ответ на него — «примерно всё».
    """

    ANY = "any"
    SUBCLASSES = "subclasses"
    IMPORTERS = "importers"
    RAISED_BY = "raised_by"


RELATION_EDGES: dict[ReferenceRelation, tuple[EdgeKind, ...]] = {
    ReferenceRelation.ANY: (),
    ReferenceRelation.SUBCLASSES: (EdgeKind.INHERITS,),
    ReferenceRelation.IMPORTERS: (EdgeKind.IMPORTS,),
    ReferenceRelation.RAISED_BY: (EdgeKind.RAISES,),
}
"""Какими рёбрами отвечает каждый вопрос. Пустой набор — любыми."""

EDGE_ROLES: dict[EdgeKind, FragmentRole] = {
    EdgeKind.CALLS: FragmentRole.CALLER,
    EdgeKind.INHERITS: FragmentRole.SUBCLASS,
    EdgeKind.IMPORTS: FragmentRole.IMPORTER,
    EdgeKind.RAISES: FragmentRole.RAISER,
    EdgeKind.DECORATES: FragmentRole.DECORATED,
    EdgeKind.REFERENCES: FragmentRole.RELATED,
}
"""Как читать соседа, пришедшего по ребру этого вида."""

DOC_LANGUAGES = ("markdown", "text")
"""Языки, на которых пишут документацию, а не код."""

EDGE_NAMES: dict[EdgeKind, str] = {
    EdgeKind.CALLS: "вызовы",
    EdgeKind.INHERITS: "наследование",
    EdgeKind.IMPORTS: "импорт",
    EdgeKind.RAISES: "возбуждение исключения",
    EdgeKind.DECORATES: "декорирование",
    EdgeKind.REFERENCES: "упоминание",
}
"""Как связь называется в оговорке к ответу."""


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
        """Показывает, откуда символ вызывается, — что сломается, если его тронуть.

        Отвечает вызовами и только ими. Наследование, импорт и остальные
        связи спрашиваются отдельно: они тоже показывают, что сломается,
        но сломается по-другому, и лечится это по-другому.
        """
        ...

    async def find_references(
        self,
        name: str,
        *,
        relation: ReferenceRelation = ReferenceRelation.ANY,
        limit: int = 20,
    ) -> NavigationAnswer:
        """Показывает, кто ссылается на символ и каким образом.

        Дополняет `find_callers` там, где связь не вызов: базовый класс
        ломает наследников, а не вызывающих, и перечень последних на вопрос
        «что сломается от правки контракта» отвечает пустотой.
        """
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

    async def read_file(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
    ) -> NavigationAnswer:
        """Показывает строки файла как строки.

        Отвечает там, где `get_file_context` отвечать нечем: у миграции,
        файла настроек и шаблона проиндексированных символов нет, и обход
        по графу возвращает пустоту, из которой читается «здесь ничего нет».
        """
        ...

    async def get_file_outline(self, path: str, *, limit: int = 60) -> NavigationAnswer:
        """Перечисляет символы файла с их местами, без тел.

        Карта крупного файла: на тысяче строк оглавление занимает два
        десятка строк, а `get_file_context` вернёт обрезанное тело одного
        класса и место в окне, которого хватило бы на весь ответ.
        """
        ...

    async def find_symbol(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        """Ищет символы по имени, а не по смыслу.

        Между «найти похожее по содержанию» и «разрешить полное имя» лежит
        частый случай: спрашивающий помнит слово из имени, но не помнит
        ни файла, ни полного пути к символу.
        """
        ...

    async def project_docs(self, query: str, *, limit: int = 5) -> NavigationAnswer:
        """Ищет по документации репозитория, а не по коду.

        «Как здесь принято» и «как здесь сделано» — разные вопросы, а в общей
        выдаче README проигрывает коду просто по объёму: файлов с кодом
        в проекте на два порядка больше.
        """
        ...

    async def describe_repository(self) -> NavigationAnswer:
        """Рассказывает, из чего репозиторий состоит.

        Первый ход почти любого разговора: на чём это написано, где что
        лежит, велик ли проект. Без него ответ собирается из трёх перечней
        файлов, и на небольшой модели это половина бюджета шагов.
        """
        ...

    async def list_files(self, pattern: str, *, limit: int = 40) -> NavigationAnswer:
        """Перечисляет файлы репозитория, подходящие под образец.

        Отвечает на вопрос «что тут вообще есть»: посмотреть по типу файлов,
        по каталогу, по имени. Без него спрашивающий проверяет догадки —
        ищет `import React`, не находит и заключает, что фронта нет вовсе,
        хотя в репозитории пятьсот файлов на другом фреймворке.

        Ответ — перечень путей, а не содержимое: карта нужна, чтобы выбрать,
        что читать дальше, и десяток файлов целиком вытеснил бы из окна всё
        остальное.
        """
        ...


class CodeNavigatorFactory(Protocol):
    """Навигатор по конкретному репозиторию.

    Репозиторий выбирается один раз при создании, а не передаётся в каждую
    операцию: у навигатора по git его вовсе нет — там путь и ревизия.
    """

    def for_repository(self, repository_id: RepositoryId) -> CodeNavigator: ...


class GitNavigatorFactory(Protocol):
    """Навигатор по ревизии в рабочем каталоге репозитория.

    Объявлен отдельно от индексного, потому что опознаёт репозиторий иначе:
    у git нет идентификатора из нашей базы, у него есть путь и ревизия.
    """

    def for_revision(
        self,
        repository_path: Path,
        revision: str,
        *,
        reason: str = "",
    ) -> CodeNavigator:
        """Навигатор по ревизии; `reason` объясняет, почему не индекс.

        Причина едет в ответы инструментов: «индекса нет» и «индекс собран
        на другом коммите» — разные новости, и для модели вторая означает,
        что структурные связи существуют, просто отсюда не видны.
        """
        ...


def clip_code(text: str, limit: int = MAX_FRAGMENT_CHARS) -> str:
    """Обрезает фрагмент, честно говоря об этом.

    Молчаливое усечение хуже обрезанного текста: модель, не знающая об остатке,
    делает вывод по половине определения и цитирует несуществующий конец.
    """
    if len(text) <= limit:
        return text

    remainder = len(text) - limit
    return f"{text[:limit].rstrip()}\n… обрезано, ещё {remainder} символов"
