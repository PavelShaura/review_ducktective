from ducktective.core.exceptions import (
    SearchTimedOutError,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.retrieval.context import (
    ORIGIN_PRIORITY,
    ContextBudget,
    ContextOrigin,
    ContextPiece,
    DiffContext,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    ChunkSearch,
    SymbolContext,
    SymbolReader,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.types import (
    CodeSymbolId,
    RepositoryId,
)
from ducktective.indexing.hashing import (
    estimate_tokens,
)


DEFAULT_TOKEN_BUDGET = 2000
"""Сколько токенов контекста класть в подсказку по умолчанию.

Значение подобрано под окно локальной модели: у `gemma-4-e4b` оно 8192, и туда
должны поместиться системный промпт, патч, контекст и весь ответ. При бюджете
4000 модель упиралась в предел на середине рассуждений и возвращала обрезанный
текст вместо JSON — ревью файла терялось целиком.

Для модели с большим окном значение поднимается настройкой: контекста много
не бывает, бывает мало места под ответ.
"""
NEIGHBOUR_LIMIT = 12
SIMILAR_LIMIT = 6


class DiffContextBuilder:
    """Собирает контекст вокруг изменённого файла.

    Точка входа — не текстовый запрос, а сам дифф: строки ханка превращаются
    в затронутые символы, и уже от них идёт обход графа. Это то, чего нет
    у поиска по запросу, и то, что отвечает на главный вопрос ревью —
    что сломается от изменения.

    Порядок наполнения задан приоритетом источника: сначала сам изменённый
    символ, затем то, что он вызывает, затем те, кто вызывает его, и лишь
    потом похожие места из поиска. Структурные соседи точны по построению,
    поиск вероятностен, поэтому первые вытесняют вторых.
    """

    def __init__(
        self,
        symbols: SymbolReader,
        search: ChunkSearch,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> None:
        self._symbols = symbols
        self._search = search
        self._token_budget = token_budget

    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        changed = await self._changed_symbols(repository_id, file)
        budget = ContextBudget(limit=self._token_budget)
        pieces: list[ContextPiece] = []

        self._collect(pieces, budget, changed, ContextOrigin.CHANGED_SYMBOL)

        anchor_ids = [symbol.symbol_id for symbol in changed]
        if anchor_ids:
            callees = await self._symbols.callees(anchor_ids, limit=NEIGHBOUR_LIMIT)
            self._collect(pieces, budget, callees, ContextOrigin.CALLEE)

            callers = await self._symbols.callers(anchor_ids, limit=NEIGHBOUR_LIMIT)
            self._collect(pieces, budget, callers, ContextOrigin.CALLER)

        similar = await self._similar(repository_id, file, exclude=set(anchor_ids))
        self._collect_hits(pieces, budget, similar)

        pieces.sort(key=lambda piece: (ORIGIN_PRIORITY[piece.origin], piece.path, piece.start_line))
        return DiffContext(
            path=file.path,
            pieces=tuple(pieces),
            dropped=budget.dropped,
            token_budget=self._token_budget,
        )

    async def _changed_symbols(
        self,
        repository_id: RepositoryId,
        file: ReviewFile,
    ) -> list[SymbolContext]:
        """Символы, задетые ханками файла.

        Модуль целиком отбрасывается: он покрывает любую строку и вытеснил бы
        собой весь бюджет, ничего не объяснив.
        """
        found: dict[CodeSymbolId, SymbolContext] = {}

        for hunk in file.hunks:
            lines = hunk.new_range
            if lines is None:
                continue

            for symbol in await self._symbols.symbols_covering(
                repository_id,
                file.path,
                lines.start,
                lines.end,
            ):
                if symbol.kind is not SymbolKind.MODULE:
                    found.setdefault(symbol.symbol_id, symbol)

        return list(found.values())

    async def _similar(
        self,
        repository_id: RepositoryId,
        file: ReviewFile,
        *,
        exclude: set[CodeSymbolId],
    ) -> list[ChunkHit]:
        """Похожие места по содержимому изменений.

        Ловит копипасту и расхождения с принятыми в проекте решениями —
        то, что обходом графа не находится.

        Ищется по добавленному, а не по патчу целиком: контекстные
        и удалённые строки описывают код, которого изменение не касалось.

        Не успевший поиск возвращает пустоту, а не срывает сборку: похожие
        места — самая необязательная часть окружения, и файл без них
        полезнее, чем прогон, стоящий на одном запросе.
        """
        query = file.added_code
        if not query.strip():
            return []

        try:
            hits = await self._search.search_chunks(repository_id, query, limit=SIMILAR_LIMIT * 2)
        except SearchTimedOutError:
            return []
        return [
            hit
            for hit in hits
            if hit.path != file.path and (hit.symbol_id is None or hit.symbol_id not in exclude)
        ][:SIMILAR_LIMIT]

    def _collect(
        self,
        pieces: list[ContextPiece],
        budget: ContextBudget,
        symbols: list[SymbolContext],
        origin: ContextOrigin,
    ) -> None:
        for symbol in symbols:
            text = _render(symbol, origin)
            if not text:
                continue

            piece = ContextPiece(
                origin=origin,
                path=symbol.path,
                qualified_name=symbol.qualified_name,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                text=text,
                token_count=estimate_tokens(text),
                symbol_id=symbol.symbol_id,
            )
            if budget.take(piece):
                pieces.append(piece)

    def _collect_hits(
        self,
        pieces: list[ContextPiece],
        budget: ContextBudget,
        hits: list[ChunkHit],
    ) -> None:
        for hit in hits:
            piece = ContextPiece(
                origin=ContextOrigin.SIMILAR,
                path=hit.path,
                qualified_name=None,
                start_line=hit.start_line,
                end_line=hit.end_line,
                text=hit.content,
                token_count=estimate_tokens(hit.content),
                symbol_id=hit.symbol_id,
            )
            if budget.take(piece):
                pieces.append(piece)


def _render(symbol: SymbolContext, origin: ContextOrigin) -> str:
    """Готовит текст символа под его роль в контексте.

    Изменённый символ нужен целиком — по нему модель судит о правках.
    Соседям достаточно сигнатуры и докстринга: от них требуется контракт,
    а не реализация, и класть их телом значит вытеснить всё остальное.
    """
    if origin is ContextOrigin.CHANGED_SYMBOL:
        return symbol.text or symbol.signature or ""

    header = symbol.signature or symbol.qualified_name
    if not symbol.docstring:
        return header

    return f'{header}\n    """{symbol.docstring}"""'
