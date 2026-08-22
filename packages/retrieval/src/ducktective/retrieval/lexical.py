import re
from typing import (
    Any,
)

from sqlalchemy import (
    ColumnElement,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.indexing.search import (
    build_search_text,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    SymbolHit,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    QualifiedName,
    RepositoryId,
)
from ducktective.retrieval.deadline import (
    DEFAULT_SEARCH_TIMEOUT_MS,
    within_deadline,
)
from ducktective.storage.models.indexing import (
    CodeChunkModel,
    CodeSymbolModel,
    SourceFileModel,
)


SEARCH_CONFIGURATION = "simple"

MAX_QUERY_TERMS = 40
"""Сколько слов запроса доходит до базы.

Слова соединяются через «или», поэтому длина запроса решает не точность,
а объём работы: под условие из семисот слов подходит почти каждый фрагмент
базы, ранг приходится считать для всех, и `LIMIT` не спасает — сортировать
всё равно надо посчитанное. На закрытой базы такой запрос — 762 слова на 38 826
чанков — шёл восемь минут и держал прогон целиком.

Предел стоит здесь, а не у вызывающего: запрос из целого файла может
прийти и от внешнего клиента, а обещание отвечать за отведённое время
даёт поиск, а не тот, кто его позвал.
"""

TERM_SEPARATOR = re.compile(r"[^\w/.\-]+", re.UNICODE)
"""Что разделяет слова запроса.

Пробелов мало: в чат вставляют код, и сигнатура
`def get_branch_for_reader(profile: ReaderProfile)` разбивается пробелами в слово
`get_branch_for_reader(profile` — со скобкой и параметром внутри. Такого токена
в индексе нет, и точная ступень промахивается на самом прямом из запросов.

Слитно остаётся то, что бывает слитно в коде: буквы, цифры, подчёркивание,
точка, дефис и слеш — путь `/catalog_branch_select` и имя `app.module` должны
дойти целиком.
"""

_UNSAFE = str.maketrans("", "", "'\"\\")
_EDGE_PUNCTUATION = "()[]{},;:!?<>=+*&|~`@#$%^ .-"

MIN_SUBSTRING_LENGTH = 5
"""Короче этого подстрокой не ищут: найдётся всюду и ничего не сузит."""

MIN_TERM_LENGTH = 3
"""Короткое слово есть везде и не различает ничего.

Отбор идёт по длине: составные имена вроде `catalog_section` и `weasyprint`
сужают выдачу, а `if`, `to` и `id` только расширяют её до всей базы.
"""


class PostgresLexicalSearch:
    """Полнотекстовый поиск средствами Postgres.

    Отдельный поисковый движок не поднимается: индекс уже лежит рядом
    с данными, и лишнее хранилище дало бы рассинхронизацию вместо выигрыша.

    Запрос проходит ту же подготовку, что и индексируемый текст: иначе
    «ReviewRun» не нашёл бы то, что записано как «review run».
    """

    def __init__(
        self, session: AsyncSession, *, timeout_ms: int = DEFAULT_SEARCH_TIMEOUT_MS
    ) -> None:
        self._session = session
        self._timeout_ms = timeout_ms

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ChunkHit]:
        """Ищет фрагменты, начиная с самой точной формулировки запроса.

        Порядок ступеней — по убыванию точности: точное слово, слова вопроса,
        подстрока внутри слова и только последним — части составных имён.
        Подстрока стоит раньше разбора не по цене, а по смыслу: `branch_select`
        внутри `/catalog_branch_select` — это то самое место, а `unit | select` —
        любое из сотни, где встретилось хоть одно из двух слов.
        """
        exact, split = _query_stages(query)

        for terms in exact:
            hits = await self._chunks_matching(repository_id, terms, limit)
            if hits:
                return hits

        contained = await self._chunks_containing(repository_id, query, limit)
        if contained:
            return contained

        for terms in split:
            hits = await self._chunks_matching(repository_id, terms, limit)
            if hits:
                return hits

        return []

    async def _chunks_containing(
        self,
        repository_id: RepositoryId,
        query: str,
        limit: int,
    ) -> list[ChunkHit]:
        """Последняя попытка: подстрока внутри слова.

        Полнотекстовый поиск ищет целыми словами, и `branch_select` внутри
        `/catalog_branch_select` для него не существует — а человек ищет именно
        так, по куску имени, который помнит. Полный проход по содержимому
        стоит около трети секунды на сорока тысячах фрагментов, поэтому
        он и стоит последним: только когда точный поиск ничего не дал.

        Ищется одно слово — самое длинное из кодовых. Прозу подстрокой
        искать бессмысленно: «проверяются» не встречается в английском коде,
        а короткое слово найдётся всюду.
        """
        candidates = [
            term
            for term in _terms_of(query, split_identifiers=False)
            if _is_code_like(term) and len(term) >= MIN_SUBSTRING_LENGTH
        ]
        if not candidates:
            return []

        needle = max(candidates, key=len)
        statement = (
            select(
                CodeChunkModel.id,
                CodeChunkModel.symbol_id,
                SourceFileModel.path,
                CodeChunkModel.breadcrumb,
                CodeChunkModel.content,
                CodeChunkModel.start_line,
                CodeChunkModel.end_line,
            )
            .join(SourceFileModel, SourceFileModel.id == CodeChunkModel.file_id)
            .where(
                CodeChunkModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                CodeChunkModel.content.icontains(needle, autoescape=True),
            )
            .order_by(func.length(CodeChunkModel.content))
            .limit(limit)
        )

        rows = await within_deadline(
            self._session,
            lambda: self._session.execute(statement),
            timeout_ms=self._timeout_ms,
        )
        return [
            ChunkHit(
                chunk_id=CodeChunkId(row.id),
                symbol_id=CodeSymbolId(row.symbol_id) if row.symbol_id else None,
                path=row.path,
                breadcrumb=row.breadcrumb,
                content=row.content,
                start_line=row.start_line,
                end_line=row.end_line,
                score=0.0,
            )
            for row in rows
        ]

    async def _chunks_matching(
        self,
        repository_id: RepositoryId,
        terms: ColumnElement[Any],
        limit: int,
    ) -> list[ChunkHit]:
        rank = func.ts_rank_cd(CodeChunkModel.search_vector, terms)
        statement = (
            select(
                CodeChunkModel.id,
                CodeChunkModel.symbol_id,
                SourceFileModel.path,
                CodeChunkModel.breadcrumb,
                CodeChunkModel.content,
                CodeChunkModel.start_line,
                CodeChunkModel.end_line,
                rank.label("score"),
            )
            .join(SourceFileModel, SourceFileModel.id == CodeChunkModel.file_id)
            .where(
                CodeChunkModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                CodeChunkModel.search_vector.op("@@")(terms),
            )
            .order_by(rank.desc())
            .limit(limit)
        )

        rows = await within_deadline(
            self._session,
            lambda: self._session.execute(statement),
            timeout_ms=self._timeout_ms,
        )
        return [
            ChunkHit(
                chunk_id=CodeChunkId(row.id),
                symbol_id=CodeSymbolId(row.symbol_id) if row.symbol_id else None,
                path=row.path,
                breadcrumb=row.breadcrumb,
                content=row.content,
                start_line=row.start_line,
                end_line=row.end_line,
                score=float(row.score),
            )
            for row in rows
        ]

    async def search_symbols(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[SymbolHit]:
        exact, split = _query_stages(query)
        for terms in (*exact, *split):
            hits = await self._symbols_matching(repository_id, terms, limit)
            if hits:
                return hits
        return []

    async def _symbols_matching(
        self,
        repository_id: RepositoryId,
        terms: ColumnElement[Any],
        limit: int,
    ) -> list[SymbolHit]:
        rank = func.ts_rank_cd(CodeSymbolModel.search_vector, terms)
        statement = (
            select(
                CodeSymbolModel.id,
                CodeSymbolModel.qualified_name,
                CodeSymbolModel.kind,
                SourceFileModel.path,
                CodeSymbolModel.start_line,
                CodeSymbolModel.end_line,
                CodeSymbolModel.signature,
                rank.label("score"),
            )
            .join(SourceFileModel, SourceFileModel.id == CodeSymbolModel.file_id)
            .where(
                CodeSymbolModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                CodeSymbolModel.search_vector.op("@@")(terms),
            )
            .order_by(rank.desc())
            .limit(limit)
        )

        rows = await within_deadline(
            self._session,
            lambda: self._session.execute(statement),
            timeout_ms=self._timeout_ms,
        )
        return [
            SymbolHit(
                symbol_id=CodeSymbolId(row.id),
                qualified_name=QualifiedName(row.qualified_name),
                kind=row.kind,
                path=row.path,
                start_line=row.start_line,
                end_line=row.end_line,
                signature=row.signature,
                score=float(row.score),
            )
            for row in rows
        ]


def looks_literal(query: str) -> bool:
    """Спрашивают ли о том, что написано в коде, а не о том, что оно делает.

    Различие меняет, чему верить в слиянии: у запроса с литералом ответ
    лексический и точный, у запроса словами — векторный, потому что код
    английский, а спрашивают по-русски, и совпадать там нечему.
    """
    return any(_is_code_like(term) for term in _terms_of(query, split_identifiers=False))


def _query_stages(query: str) -> tuple[list[ColumnElement[Any]], list[ColumnElement[Any]]]:
    """Запросы к базе двумя группами: точные и с разбором составных имён.

    Первым идёт то, что человек написал сам: `/catalog_branch_select` лежит
    в индексе целиком, вместе со слешем, и совпадение по нему единственное
    на всю базу. Вторым — то же плюс части составных имён: без них запрос
    «ReviewRun» не найдёт `review_run`, потому что разбор делит по
    подчёркиванию, а слитное имя оставляет как есть.

    Стадии именно по очереди, а не одним «или». Ранжирование считает
    частоту, и одно точное вхождение проигрывает десяткам вхождений слова
    `unit`: на живом индексе закрытой базы запрос `/catalog_branch_select` возвращал
    `import_branch`, а нужный класс не попадал и в первую тройку.
    """
    written = _terms_of(query, split_identifiers=False)
    code_like = {term for term in written if _is_code_like(term)}
    everything = _terms_of(query, split_identifiers=True)

    exact: list[set[str]] = []
    for terms in (_most_distinctive(code_like), code_like, written):
        if terms and terms not in exact:
            exact.append(terms)

    split = [everything] if everything and everything not in exact else []

    return (
        [_expression(terms) for terms in exact],
        [_expression(terms) for terms in split],
    )


def _most_distinctive(terms: set[str]) -> set[str]:
    """Одно слово запроса, различающее сильнее прочих.

    Вставленная сигнатура `def get_branch_for_reader(profile: ReaderProfile) ->
    Optional[Unit]` содержит и редкое имя, и `Unit` с `Optional`, которые
    есть в каждом втором файле. Соединённые через «или», они топят редкое
    ранжированием: оно считает частоту, и одно вхождение проигрывает сотне.

    Различает длина: составное имя длиннее типа, а тип длиннее ключевого
    слова. Ступень пробуется первой и уступает следующей, если ничего
    не нашла, — потерять из-за неё нельзя ничего.
    """
    long_enough = {term for term in terms if len(term) >= MIN_SUBSTRING_LENGTH}
    if len(long_enough) < 2:
        return set()
    return {max(long_enough, key=len)}


def _is_code_like(term: str) -> bool:
    """Похоже ли слово на то, что написано в коде, а не сказано о коде.

    Вопрос обычно смешивает прозу с литералом: «как используется
    url = '/catalog_branch_select'». Слова вокруг встречаются повсюду и топят
    единственное точное совпадение, поэтому сначала ищется то, что могло
    быть написано в файле: путь, составное имя, имя с заглавной внутри.
    """
    if any(character in term for character in "_/."):
        return True
    if any(character.isdigit() for character in term):
        return True
    return term != term.lower() and term != term.upper()


def _expression(terms: set[str]) -> ColumnElement[Any]:
    """Собирает «или» из лексем в кавычках.

    Кавычки обязательны: разбор `to_tsquery` спотыкается на всём, что не
    буква, а точно ищут как раз такие слова — пути, адреса, литералы.
    """
    return func.to_tsquery(SEARCH_CONFIGURATION, " | ".join(f"'{term}'" for term in sorted(terms)))


def _terms_of(query: str, *, split_identifiers: bool, limit: int = MAX_QUERY_TERMS) -> set[str]:
    """Отбирает слова, которые сужают выдачу, а не расширяют её.

    Короткий запрос доходит целиком: у человека, спросившего два слова,
    отбирать нечего. Обрезается длинный — тот, что собран из целого файла.
    """
    source = build_search_text(query) if split_identifiers else query
    words = {cleaned for word in TERM_SEPARATOR.split(source) if (cleaned := _clean_term(word))}
    if len(words) <= limit:
        return words

    long_enough = {word for word in words if len(word) >= MIN_TERM_LENGTH} or words
    return set(sorted(long_enough, key=lambda word: (-len(word), word))[:limit])


def _clean_term(word: str) -> str:
    """Убирает у слова то, чем оно не ищется.

    Кавычки и обратный слеш вырезаются целиком: они ломают разбор запроса,
    а внутри лексемы не значат ничего. Знаки препинания по краям снимаются —
    `('/catalog_branch_select',` и `/catalog_branch_select` должны искаться
    одинаково.
    """
    stripped = word.translate(_UNSAFE).strip(_EDGE_PUNCTUATION)
    return stripped if any(character.isalnum() for character in stripped) else ""
