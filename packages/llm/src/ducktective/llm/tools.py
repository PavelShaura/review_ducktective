import json
from dataclasses import (
    dataclass,
)
from typing import (
    Any,
    Protocol,
)

from ducktective.core.chat.documents import (
    select_passages,
)
from ducktective.core.chat.entities import (
    AttachedDocument,
)
from ducktective.core.llm.value_objects import (
    ToolCall,
    ToolSpec,
)
from ducktective.core.retrieval.navigation import (
    CodeFragment,
    CodeNavigator,
    FragmentRole,
    NavigationAnswer,
    NavigationSource,
    ReferenceRelation,
)
from ducktective.llm.query_expansion import (
    QueryExpander,
    looks_like_prose,
)


MAX_TOOL_RESULT_CHARS = 1600
"""Сколько от ответа инструмента видит модель.

Результат остаётся в диалоге до конца цикла, а окно конечно: при 16 000
четыре неурезанных ответа не оставят места ни на дифф, ни на сам разбор.
Предел жёсткий именно поэтому, а не из экономии.
"""

EXPANDED_QUERY_NOTE = (
    "Запрос «{query}» переведён в имена, какими они пишутся в коде, "
    "и поиск шёл по ним: {candidates}."
)

SOURCE_NOTES = {
    NavigationSource.INDEX: "Источник: индекс проекта (символы и граф вызовов).",
    NavigationSource.GIT: "Источник: поиск по словам в ревизии, индекса нет.",
}

ROLE_TITLES = {
    FragmentRole.DEFINITION: "Определение",
    FragmentRole.CALLEE: "Вызывает",
    FragmentRole.CALLER: "Вызывается из",
    FragmentRole.MATCH: "Совпадение",
    FragmentRole.SUBCLASS: "Наследует",
    FragmentRole.IMPORTER: "Импортирует",
    FragmentRole.RAISER: "Возбуждает",
    FragmentRole.DECORATED: "Декорирован им",
    FragmentRole.RELATED: "Ссылается",
    FragmentRole.SOURCE: "Строки",
    FragmentRole.NAME: "Имя",
}

SEARCH_CODE = ToolSpec(
    name="search_code",
    description=(
        "Find code by a free-form query: a name, a concept, or a description of behaviour. "
        "Use it to see how something is done elsewhere in this project."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for"},
            "limit": {"type": "integer", "description": "How many fragments, default 5"},
        },
        "required": ["query"],
    },
)

GET_DEFINITION = ToolSpec(
    name="get_definition",
    description=(
        "Show the definition of a symbol. The name may be qualified (ReviewRun.add_finding) "
        "or short (add_finding). Namesakes are all returned."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Symbol name"},
            "limit": {"type": "integer", "description": "How many definitions, default 3"},
        },
        "required": ["name"],
    },
)

FIND_CALLERS = ToolSpec(
    name="find_callers",
    description=(
        "Show where a symbol is called from - calls only. This answers what breaks if the "
        "change alters its contract. For subclasses, importers or other kinds of reference, "
        "use find_references: a base class breaks the classes that inherit it, and those "
        "never appear among its callers."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Symbol name"},
            "limit": {"type": "integer", "description": "How many callers, default 8"},
        },
        "required": ["name"],
    },
)

GET_FILE_CONTEXT = ToolSpec(
    name="get_file_context",
    description="Show what surrounds a range of lines in a file of this repository.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path inside the repository"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path", "start_line", "end_line"],
    },
)

FIND_REFERENCES = ToolSpec(
    name="find_references",
    description=(
        "Show what refers to a symbol other than by calling it, and how. Use "
        "'subclasses' for the classes that inherit it, 'importers' for the modules that "
        "import it, 'raised_by' for the code that raises it, 'any' to see every kind of "
        "reference at once. Changing a base class or a shared module breaks these, and "
        "find_callers does not list them."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Symbol name"},
            "relation": {
                "type": "string",
                "enum": [relation.value for relation in ReferenceRelation],
                "description": "Kind of reference, default 'any'",
            },
            "limit": {"type": "integer", "description": "How many references, default 8"},
        },
        "required": ["name"],
    },
)

READ_FILE = ToolSpec(
    name="read_file",
    description=(
        "Read a range of lines of a file as plain lines. Use it for files that have no "
        "symbols to walk - a migration, a settings file, a template, a lock file - where "
        "get_file_context has nothing to answer with, and for reading a place you already "
        "found by its line numbers."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path inside the repository"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path", "start_line", "end_line"],
    },
)

GET_FILE_OUTLINE = ToolSpec(
    name="get_file_outline",
    description=(
        "List what a file defines - classes, functions, methods - with their line ranges "
        "and no bodies. Use it to see the shape of a large file before deciding what to "
        "read: the outline of a thousand-line file is twenty lines long."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path inside the repository"},
        },
        "required": ["path"],
    },
)

FIND_SYMBOL = ToolSpec(
    name="find_symbol",
    description=(
        "Find symbols whose names look like the query. Use it when you remember a word "
        "from the name but not the file or the full name - 'permission', 'archived', "
        "'report builder'. This searches names, while search_code searches content."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A word or part of a name"},
            "limit": {"type": "integer", "description": "How many symbols, default 8"},
        },
        "required": ["query"],
    },
)

PROJECT_DOCS = ToolSpec(
    name="project_docs",
    description=(
        "Search the documentation of this repository - README, docs, ADRs - instead of its "
        "code. Use it for questions about how things are meant to work here, what was "
        "decided and why. It says how the project is intended, which is not always how it "
        "is built."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for"},
        },
        "required": ["query"],
    },
)

DESCRIBE_REPOSITORY = ToolSpec(
    name="describe_repository",
    description=(
        "Describe what this repository is made of: how many files, in which languages, and "
        "what the top-level directories are. Start here when the question is about the "
        "project as a whole rather than a place in it."
    ),
    parameters={"type": "object", "properties": {}},
)

LIST_FILES = ToolSpec(
    name="list_files",
    description=(
        "List the files of this repository matching a pattern: an extension like '.js', "
        "a directory like 'templates/', a glob like 'src/*/models.py'. Use it to see what "
        "the project actually contains before assuming what it is built with - guessing a "
        "framework and searching for its import proves nothing when the guess is wrong."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Extension, directory or glob"},
        },
        "required": ["pattern"],
    },
)

SEARCH_DOCUMENT = ToolSpec(
    name="search_document",
    description=(
        "Search the document attached to this conversation - a requirement, a spec, a page "
        "exported from Confluence. Use it when the question refers to what is written there, "
        "or to check the code against what it says."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for in the document"},
        },
        "required": ["query"],
    },
)

NAVIGATION_TOOLS = (
    DESCRIBE_REPOSITORY,
    SEARCH_CODE,
    FIND_SYMBOL,
    GET_DEFINITION,
    FIND_CALLERS,
    FIND_REFERENCES,
    GET_FILE_CONTEXT,
    GET_FILE_OUTLINE,
    READ_FILE,
    LIST_FILES,
    PROJECT_DOCS,
)


@dataclass(frozen=True)
class ToolExecutionResult:
    """Что вернул инструмент.

    Текст уходит модели, фрагменты — проверке доказательств: подтверждать
    цитату нужно по тому, что инструмент действительно показал, а из текста
    ответа этого уже не восстановить.
    """

    text: str
    fragments: tuple[CodeFragment, ...] = ()
    is_error: bool = False


class Toolbox(Protocol):
    """Набор инструментов, каким его видит цикл обращений к модели.

    Наборов два: разговор ходит только по коду, ревью видит вдобавок свой
    дифф. Цикл об этом не знает — ему нужно перечислить инструменты
    и исполнить вызов.
    """

    @property
    def specs(self) -> tuple[ToolSpec, ...]: ...

    async def execute(self, call: ToolCall) -> ToolExecutionResult: ...


class NavigationToolbox:
    """Инструменты навигации, какими их видит модель.

    Схемы вызова живут рядом с промптами, а не в домене: это деталь протокола
    обращения к модели, и меняется она вместе с подсказкой, а не вместе
    с правилами ревью (D-020).

    Ошибка исполнения возвращается текстом, а не исключением. Для модели
    «такого инструмента нет» или «аргументы не разобрались» — полезный ответ,
    после которого она исправляется; исключение обрывает расследование
    целиком.
    """

    def __init__(
        self,
        navigator: CodeNavigator,
        *,
        result_chars: int = MAX_TOOL_RESULT_CHARS,
        document: AttachedDocument | None = None,
        expander: QueryExpander | None = None,
    ) -> None:
        self._navigator = navigator
        self._result_chars = result_chars
        self._document = document
        self._expander = expander

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """Инструменты, предложенные модели.

        Поиск по документу появляется только когда документ приложен:
        инструмент, отвечающий «прикладывать нечего», тратит и шаг цикла,
        и место в окне, где перечислены инструменты.
        """
        if self._document is None:
            return NAVIGATION_TOOLS
        return (*NAVIGATION_TOOLS, SEARCH_DOCUMENT)

    async def execute(self, call: ToolCall) -> ToolExecutionResult:
        try:
            arguments = parse_arguments(call.arguments)
        except ValueError as error:
            return ToolExecutionResult(str(error), is_error=True)

        if call.name == SEARCH_DOCUMENT.name:
            return self._search_document(arguments)

        try:
            answer = await self._dispatch(call.name, arguments)
        except KeyError:
            available = ", ".join(tool.name for tool in self.specs)
            return ToolExecutionResult(
                f"Инструмента «{call.name}» нет. Доступны: {available}",
                is_error=True,
            )
        except (TypeError, ValueError) as error:
            return ToolExecutionResult(f"Аргументы не подошли: {error}", is_error=True)
        except Exception as error:
            return ToolExecutionResult(f"Инструмент не отработал: {error}", is_error=True)

        return ToolExecutionResult(
            render_for_model(answer, limit=self._result_chars),
            fragments=answer.fragments,
        )

    def _search_document(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        """Куски приложенного документа, относящиеся к запросу.

        Фрагментами кода они не притворяются: у них нет ни файла, ни строк,
        и в проверке доказательств им делать нечего. Абзац назван номером —
        так на него можно сослаться в ответе, не выдавая за место в коде.
        """
        if self._document is None:
            return ToolExecutionResult("К разговору не приложен документ", is_error=True)

        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolExecutionResult("Пустой запрос к документу", is_error=True)

        passages = select_passages(self._document.text, query)
        if not passages:
            return ToolExecutionResult(
                f"В документе «{self._document.name}» ничего не нашлось по запросу «{query}»"
            )

        rendered = "\n\n".join(f"Абзац {passage.number}\n{passage.text}" for passage in passages)
        return ToolExecutionResult(
            _clipped(f"Документ «{self._document.name}»\n\n{rendered}", self._result_chars)
        )

    async def _search_code(self, query: str, *, limit: int) -> NavigationAnswer:
        """Поиск по запросу и по тому, как этот запрос выглядел бы в коде.

        Кандидаты идут первыми: перевод вопроса на язык кода точнее самого
        вопроса, а буквальный запрос на прозе поднимает наверх миграции
        и тесты, где случайно совпали слова.

        Что искали на самом деле, говорится в ответе: молча подменённый
        запрос — это выдача, которую нельзя объяснить.
        """
        if self._expander is None or not looks_like_prose(query):
            return await self._navigator.search_code(query, limit=limit)

        candidates = await self._expander.expand(query)
        if not candidates:
            return await self._navigator.search_code(query, limit=limit)

        collected: list[CodeFragment] = []
        seen: set[str] = set()
        for term in (*candidates, query):
            if len(collected) >= limit:
                break

            answer = await self._navigator.search_code(term, limit=limit)
            for fragment in answer.fragments:
                if fragment.location in seen:
                    continue
                seen.add(fragment.location)
                collected.append(fragment)

        listed = ", ".join(candidates)
        return NavigationAnswer(
            source=self._navigator.source,
            fragments=tuple(collected[:limit]),
            note=EXPANDED_QUERY_NOTE.format(query=query, candidates=listed),
        )

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> NavigationAnswer:
        if name == SEARCH_CODE.name:
            return await self._search_code(
                str(arguments["query"]),
                limit=int(arguments.get("limit", 5)),
            )
        if name == GET_DEFINITION.name:
            return await self._navigator.get_definition(
                str(arguments["name"]),
                limit=int(arguments.get("limit", 3)),
            )
        if name == FIND_CALLERS.name:
            return await self._navigator.find_callers(
                str(arguments["name"]),
                limit=int(arguments.get("limit", 8)),
            )
        if name == DESCRIBE_REPOSITORY.name:
            return await self._navigator.describe_repository()
        if name == PROJECT_DOCS.name:
            return await self._navigator.project_docs(str(arguments["query"]))
        if name == FIND_SYMBOL.name:
            return await self._navigator.find_symbol(
                str(arguments["query"]),
                limit=int(arguments.get("limit", 8)),
            )
        if name == READ_FILE.name:
            return await self._navigator.read_file(
                str(arguments["path"]),
                start_line=int(arguments["start_line"]),
                end_line=int(arguments["end_line"]),
            )
        if name == GET_FILE_OUTLINE.name:
            return await self._navigator.get_file_outline(str(arguments["path"]))
        if name == FIND_REFERENCES.name:
            return await self._navigator.find_references(
                str(arguments["name"]),
                relation=_relation(arguments.get("relation")),
                limit=int(arguments.get("limit", 8)),
            )
        if name == LIST_FILES.name:
            return await self._navigator.list_files(str(arguments["pattern"]))
        if name == GET_FILE_CONTEXT.name:
            return await self._navigator.get_file_context(
                str(arguments["path"]),
                start_line=int(arguments["start_line"]),
                end_line=int(arguments["end_line"]),
            )
        raise KeyError(name)


def render_for_model(answer: NavigationAnswer, *, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Превращает ответ навигатора в текст для диалога.

    Источник называется всегда: совпадение имени в лексическом поиске
    и ребро графа — доказательства разной силы, и решать это должна модель,
    а не тот, кто собрал ответ.
    """
    sections = [SOURCE_NOTES[answer.source]]
    if answer.note:
        sections.append(answer.note)

    if answer.is_empty:
        sections.append("Ничего не нашлось.")
        return "\n".join(sections)

    for fragment in answer.fragments:
        title = f" · {fragment.title}" if fragment.title else ""
        sections.append(
            f"\n{ROLE_TITLES[fragment.role]}{title} — {fragment.location}\n"
            f"```\n{fragment.text}\n```"
        )

    return _clipped("\n".join(sections), limit)


def _relation(raw: Any) -> ReferenceRelation:
    """Вид ссылки, названный моделью.

    Неизвестное значение не ошибка: «inheritance» вместо «subclasses» стоит
    понять как «покажи любые», а не потратить шаг цикла на препирательство
    о написании.
    """
    if raw is None:
        return ReferenceRelation.ANY
    try:
        return ReferenceRelation(str(raw).strip().lower())
    except ValueError:
        return ReferenceRelation.ANY


def parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as error:
        raise ValueError(f"Аргументы вызова не разобрались как JSON: {error}") from error

    if not isinstance(parsed, dict):
        raise ValueError("Аргументы вызова должны быть объектом JSON")
    return parsed


def _clipped(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    remainder = len(text) - limit
    return (
        f"{text[:limit].rstrip()}\n… ответ обрезан, ещё {remainder} символов. "
        f"Спросите точнее, если нужно продолжение."
    )
