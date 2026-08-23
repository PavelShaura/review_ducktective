from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.core.retrieval.navigation import (
    EDGE_NAMES,
    EDGE_ROLES,
    RELATION_EDGES,
    CodeFragment,
    CodeNavigator,
    FragmentRole,
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
    clip_code,
)
from ducktective.core.retrieval.ports import (
    CALL_EDGES,
    ChunkHit,
    ChunkSearch,
    SymbolContext,
    SymbolReader,
)
from ducktective.core.types import (
    CodeSymbolId,
    RepositoryId,
)


LISTING_SCAN = 300
"""Сколько путей смотрит перечень, прежде чем сказать «более трёхсот».

Точное число важнее, чем кажется: «нашлось шесть» и «нашлось пятьсот»
ведут к разным следующим шагам — прочитать все или сузить образец.
Считать их все ради ответа незачем: после трёхсот вывод один и тот же.
"""


OUTLINE_HINT = (
    "Оглавление говорит, что в файле есть, но не что там написано: тело нужного "
    "символа покажет get_definition, произвольный участок — read_file."
)

NAME_HINT = "Найдены имена и места, а не тела: нужное покажет get_definition."

NEXT_STEP_HINT = (
    "Перечень говорит, что файлы есть, но не что в них написано: откройте любой "
    "через get_file_context, прежде чем делать вывод о содержимом."
)
"""Подсказка о следующем шаге.

Живой случай: агент перечислил пятьсот файлов фронта и, не открыв ни одного,
пошёл проверять свою прежнюю догадку про React. Перечень путей отвечает
на «что тут есть», но выводы делают по содержимому.
"""


class IndexedCodeNavigator:
    """Навигация по собранному индексу: граф символов и гибридный поиск.

    Определение приходит телом, а вызывающие — контрактом: чтобы понять, что
    сломается от правки, нужны место вызова и сигнатура, а телом два десятка
    вызывающих вытеснили бы всё остальное.
    """

    source = NavigationSource.INDEX

    def __init__(
        self,
        repository_id: RepositoryId,
        *,
        symbols: SymbolReader,
        search: ChunkSearch,
    ) -> None:
        self._repository_id = repository_id
        self._symbols = symbols
        self._search = search

    async def search_code(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        hits = await self._search.search_chunks(self._repository_id, query, limit=limit)
        return NavigationAnswer(
            source=self.source,
            fragments=tuple(_from_chunk(hit) for hit in hits),
        )

    async def get_definition(self, name: str, *, limit: int = 5) -> NavigationAnswer:
        found = await self._symbols.find_by_name(self._repository_id, name, limit=limit)
        return NavigationAnswer(
            source=self.source,
            fragments=tuple(_definition(context) for context in found),
            note=_ambiguity_note(name, len(found)),
        )

    async def find_callers(self, name: str, *, limit: int = 20) -> NavigationAnswer:
        """Вызывающие — и только они.

        Прежде сюда попадал сосед по любому ребру: наследник базового класса
        и модуль, импортировавший функцию, приходили под подписью «вызывается
        из». Правка сигнатуры ломает их иначе, чем вызывающих, а решение
        принималось по общему списку.
        """
        targets = await self._symbols.find_by_name(self._repository_id, name)
        if not targets:
            return NavigationAnswer(source=self.source)

        symbol_ids = [context.symbol_id for context in targets]
        callers = await self._symbols.callers(symbol_ids, limit=limit)
        return NavigationAnswer(
            source=self.source,
            fragments=tuple(_contract(context, FragmentRole.CALLER) for context in callers),
            note=await self._other_kinds_note(symbol_ids, shown=CALL_EDGES),
        )

    async def find_references(
        self,
        name: str,
        *,
        relation: ReferenceRelation = ReferenceRelation.ANY,
        limit: int = 20,
    ) -> NavigationAnswer:
        """Ссылающиеся на символ, подписанные видом ссылки."""
        targets = await self._symbols.find_by_name(self._repository_id, name)
        if not targets:
            return NavigationAnswer(source=self.source)

        symbol_ids = [context.symbol_id for context in targets]
        wanted = RELATION_EDGES[relation]
        related = await self._symbols.referring(symbol_ids, kinds=wanted, limit=limit)
        note = await self._other_kinds_note(symbol_ids, shown=wanted)

        return NavigationAnswer(
            source=self.source,
            fragments=tuple(
                _contract(neighbour.context, EDGE_ROLES[neighbour.kind]) for neighbour in related
            ),
            note=note or _ambiguity_note(name, len(targets)),
        )

    async def _other_kinds_note(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        shown: tuple[EdgeKind, ...],
    ) -> str | None:
        """Называет связи, которые в этот ответ не попали.

        Отфильтрованная выдача читается как исчерпывающая: «вызывающих нет»
        при двенадцати импортёрах — правда, из которой делают вывод, что код
        никому не нужен. Счёт по видам стоит одного запроса и снимает вывод.
        """
        if not shown:
            return None

        counts = await self._symbols.edge_kinds(symbol_ids)
        others = {kind: total for kind, total in counts.items() if kind not in shown and total}
        if not others:
            return None

        listed = ", ".join(
            f"{EDGE_NAMES[kind]} — {total}"
            for kind, total in sorted(others.items(), key=lambda pair: -pair[1])
        )
        return f"Показаны не все связи. Есть и другие: {listed}. Их покажет find_references."

    async def get_file_context(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        covering = await self._symbols.symbols_covering(
            self._repository_id,
            path,
            start_line,
            end_line,
        )
        note: str | None = None

        if not covering:
            resolved = await self._resolve_path(path)
            if resolved is None:
                return NavigationAnswer(
                    source=self.source, note=await self._missing_path_note(path)
                )

            note = f"Путь назван как {path}, в индексе он лежит как {resolved}"
            covering = await self._symbols.symbols_covering(
                self._repository_id,
                resolved,
                start_line,
                end_line,
            )
            path = resolved

        if not covering:
            return NavigationAnswer(
                source=self.source,
                note=f"В {path}:{start_line}-{end_line} проиндексированных символов нет",
            )

        symbol_ids = [context.symbol_id for context in covering]
        callees = await self._symbols.callees(symbol_ids, limit=limit)
        callers = await self._symbols.callers(symbol_ids, limit=limit)

        return NavigationAnswer(
            source=self.source,
            note=note,
            fragments=(
                *(_definition(context) for context in covering),
                *(_contract(context, FragmentRole.CALLEE) for context in callees),
                *(_contract(context, FragmentRole.CALLER) for context in callers),
            ),
        )

    async def read_file(
        self,
        path: str,
        *,
        start_line: int,
        end_line: int,
    ) -> NavigationAnswer:
        """Строки файла из индекса.

        Путь разрешается так же, как в `get_file_context`: спрашивающий
        называет файл так, как видит его у себя, и знать о корне
        репозитория не обязан.
        """
        resolved = await self._resolve_path(path) or path
        text = await self._symbols.read_lines(
            self._repository_id,
            resolved,
            start_line=start_line,
            end_line=end_line,
        )
        if text is None:
            return NavigationAnswer(source=self.source, note=await self._missing_path_note(path))

        note = f"Путь назван как {path}, в индексе он лежит как {resolved}"
        return NavigationAnswer(
            source=self.source,
            note=None if resolved == path else note,
            fragments=(
                CodeFragment(
                    path=resolved,
                    start_line=start_line,
                    end_line=end_line,
                    text=clip_code(text),
                    role=FragmentRole.SOURCE,
                ),
            ),
        )

    async def get_file_outline(self, path: str, *, limit: int = 60) -> NavigationAnswer:
        """Оглавление файла — карта, а не содержимое."""
        resolved = await self._resolve_path(path) or path
        symbols = await self._symbols.symbols_in_file(self._repository_id, resolved, limit=limit)
        if not symbols:
            return NavigationAnswer(
                source=self.source,
                note=(
                    f"В {resolved} проиндексированных символов нет. Строки файла покажет read_file."
                ),
            )

        listed = "\n".join(
            f"  {symbol.start_line}-{symbol.end_line}  {symbol.kind.value} "
            f"{symbol.signature or symbol.qualified_name}"
            for symbol in symbols
        )
        tail = f", показаны первые {limit}" if len(symbols) >= limit else ""
        return NavigationAnswer(
            source=self.source,
            note=(
                f"Оглавление {resolved}, символов {len(symbols)}{tail}:\n{listed}\n{OUTLINE_HINT}"
            ),
        )

    async def find_symbol(self, query: str, *, limit: int = 10) -> NavigationAnswer:
        """Имена, похожие на запрос, вместе с их местами."""
        hits = await self._symbols.search_symbols(self._repository_id, query, limit=limit)
        if not hits:
            return NavigationAnswer(
                source=self.source,
                note=f"Символов, похожих на «{query}», в индексе нет",
            )

        return NavigationAnswer(
            source=self.source,
            note=NAME_HINT,
            fragments=tuple(
                CodeFragment(
                    path=hit.path,
                    start_line=hit.start_line,
                    end_line=hit.end_line,
                    text=hit.signature or str(hit.qualified_name),
                    role=FragmentRole.NAME,
                    title=f"{hit.qualified_name} · {hit.kind.value}",
                )
                for hit in hits
            ),
        )

    async def list_files(self, pattern: str, *, limit: int = 40) -> NavigationAnswer:
        """Пути проиндексированных файлов, подходящих под образец.

        Ответ — карта, а не содержимое: фрагментов здесь нет, потому что
        десяток файлов целиком вытеснил бы из окна всё остальное. Число
        найденного называется всегда: «показаны первые сорок из пятисот
        двадцати» и «нашлось сорок» ведут к разным следующим шагам.
        """
        found = await self._symbols.find_paths(self._repository_id, pattern, limit=LISTING_SCAN)
        if not found:
            return NavigationAnswer(
                source=self.source,
                note=f"Файлов по образцу «{pattern}» в индексе нет",
            )

        total = f"более {LISTING_SCAN}" if len(found) >= LISTING_SCAN else str(len(found))
        shown = _spread(found, limit)
        tail = f", показаны {len(shown)} из {total}" if len(found) > limit else f", всего {total}"
        listed = "\n".join(shown)
        return NavigationAnswer(
            source=self.source,
            note=(f"Файлы по образцу «{pattern}»{tail}:\n{listed}\n{NEXT_STEP_HINT}"),
        )

    async def _resolve_path(self, path: str) -> str | None:
        """Приводит названный путь к тому, как он лежит в индексе.

        В индексе путь относительный, а человек называет файл так, как видит
        его у себя: абсолютным путём из редактора, куском с середины, одним
        именем. Сначала ищется совпадение по концу пути, потом — по имени
        файла: `/home/user/proj/src/app/packs.py` и `packs.py` должны
        приводить к одному и тому же месту.

        Разрешает инструмент, а не спрашивающий: требовать от него знания
        о корне репозитория значит требовать знания об устройстве индекса.
        """
        for needle in _path_needles(path):
            found = await self._symbols.find_paths(self._repository_id, needle, limit=2)
            if len(found) == 1:
                return found[0]
            if found:
                return None
        return None

    async def _missing_path_note(self, path: str) -> str:
        """Объясняет промах и называет похожие пути.

        Пустой ответ и «такого файла нет» читаются одинаково, а значат
        разное: файл может лежать под другим корнем или называться так же,
        как ещё три в соседних плагинах. Названные кандидаты превращают
        тупик в следующий запрос.
        """
        candidates: list[str] = []
        for needle in _path_needles(path):
            candidates = await self._symbols.find_paths(self._repository_id, needle, limit=5)
            if candidates:
                break

        if not candidates:
            return f"Файла {path} в индексе нет"

        listed = ", ".join(candidates)
        return f"Файла {path} в индексе нет. Похожие пути: {listed}"


class IndexedNavigators:
    """Навигаторы по индексу — по одному на репозиторий."""

    def __init__(self, *, symbols: SymbolReader, search: ChunkSearch) -> None:
        self._symbols = symbols
        self._search = search

    def for_repository(self, repository_id: RepositoryId) -> CodeNavigator:
        return IndexedCodeNavigator(
            repository_id,
            symbols=self._symbols,
            search=self._search,
        )


def _spread(paths: list[str], limit: int) -> list[str]:
    """Отбирает перечень так, чтобы были видны разные каталоги.

    Первые сорок по алфавиту — это сорок файлов одной папки, и по ним
    судят обо всём проекте: на живом вопросе про фронт так наверх попали
    вендорные библиотеки из `static`, а код приложения не показался вовсе.

    Сначала по одному файлу из каждого каталога, потом остальные: карта
    важнее полноты, а полноту даёт следующий запрос с уточнённым образцом.
    """
    if len(paths) <= limit:
        return paths

    first_of_directory: list[str] = []
    remainder: list[str] = []
    seen: set[str] = set()

    for path in paths:
        directory = path.rsplit("/", maxsplit=1)[0] if "/" in path else ""
        if directory in seen:
            remainder.append(path)
            continue
        seen.add(directory)
        first_of_directory.append(path)

    return sorted([*first_of_directory, *remainder][:limit])


def _from_chunk(hit: ChunkHit) -> CodeFragment:
    return CodeFragment(
        path=hit.path,
        start_line=hit.start_line,
        end_line=hit.end_line,
        text=clip_code(hit.content.rstrip()),
        role=FragmentRole.MATCH,
        title=hit.breadcrumb,
    )


def _definition(context: SymbolContext) -> CodeFragment:
    return CodeFragment(
        path=context.path,
        start_line=context.start_line,
        end_line=context.end_line,
        text=clip_code(context.text.rstrip() or context.signature or ""),
        title=f"{context.qualified_name} · {context.kind.value}",
    )


def _contract(context: SymbolContext, role: FragmentRole) -> CodeFragment:
    """Сосед по графу приходит контрактом, а не телом.

    От него нужно, что он обещает и где лежит: телом один крупный класс
    вытеснил бы из ответа всех остальных.
    """
    body = context.signature or str(context.qualified_name)
    if context.docstring:
        body = f"{body}\n{context.docstring}"

    return CodeFragment(
        path=context.path,
        start_line=context.start_line,
        end_line=context.end_line,
        text=clip_code(body.rstrip()),
        role=role,
        title=f"{context.qualified_name} · {context.kind.value}",
    )


def _path_needles(path: str) -> list[str]:
    """Куски пути, по которым его стоит искать, от точного к общему."""
    cleaned = path.strip().strip("\"'").lstrip("/")
    if not cleaned:
        return []

    name = cleaned.rsplit("/", maxsplit=1)[-1]
    return [cleaned] if cleaned == name else [cleaned, name]


def _ambiguity_note(name: str, found: int) -> str | None:
    """Одноимённые символы возвращаются все, и об этом стоит сказать.

    Иначе спрашивающий читает первый попавшийся как единственный и делает
    вывод о классе, которого не имел в виду.
    """
    if found <= 1:
        return None
    return f"Символов с именем «{name}» несколько: {found}"
