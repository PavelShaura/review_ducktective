import json
from dataclasses import (
    dataclass,
)
from typing import (
    Any,
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
)


MAX_TOOL_RESULT_CHARS = 1600
"""Сколько от ответа инструмента видит модель.

Результат остаётся в диалоге до конца цикла, а окно конечно: при 16 000
четыре неурезанных ответа не оставят места ни на дифф, ни на сам разбор.
Предел жёсткий именно поэтому, а не из экономии.
"""

SOURCE_NOTES = {
    NavigationSource.INDEX: "Источник: индекс проекта (символы и граф вызовов).",
    NavigationSource.GIT: "Источник: поиск по словам в ревизии, индекса нет.",
}

ROLE_TITLES = {
    FragmentRole.DEFINITION: "Определение",
    FragmentRole.CALLEE: "Вызывает",
    FragmentRole.CALLER: "Вызывается из",
    FragmentRole.MATCH: "Совпадение",
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
        "Show where a symbol is called from. This answers what breaks if the change alters "
        "its contract."
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

NAVIGATION_TOOLS = (SEARCH_CODE, GET_DEFINITION, FIND_CALLERS, GET_FILE_CONTEXT)


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
    ) -> None:
        self._navigator = navigator
        self._result_chars = result_chars

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return NAVIGATION_TOOLS

    async def execute(self, call: ToolCall) -> ToolExecutionResult:
        try:
            arguments = _parse_arguments(call.arguments)
        except ValueError as error:
            return ToolExecutionResult(str(error), is_error=True)

        try:
            answer = await self._dispatch(call.name, arguments)
        except KeyError:
            available = ", ".join(tool.name for tool in NAVIGATION_TOOLS)
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

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> NavigationAnswer:
        if name == SEARCH_CODE.name:
            return await self._navigator.search_code(
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


def _parse_arguments(raw: str) -> dict[str, Any]:
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
