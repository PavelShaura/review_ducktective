from dataclasses import (
    dataclass,
)
from uuid import (
    uuid4,
)

from tree_sitter import (
    Node,
)

from ducktective.core.indexing.entities import (
    CodeChunk,
    CodeSymbol,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
)
from ducktective.indexing.hashing import (
    content_hash,
    estimate_tokens,
)


MAX_CHUNK_TOKENS = 512
MIN_CHUNK_TOKENS = 48
OVERLAP_LINES = 2

DEFINITION_NODES = frozenset({"class_definition", "function_definition", "decorated_definition"})
"""Узлы определений в Python — значение по умолчанию.

Набор передаётся снаружи, потому что принадлежит языку, а не нарезке:
у JavaScript определение это `class_declaration` или `lexical_declaration`
со стрелочной функцией, и зашитый здесь питоновский список превратил бы
любой другой язык в один сплошной модульный чанк.
"""


@dataclass(frozen=True, kw_only=True)
class Fragment:
    """Кусок файла до превращения в чанк: строки и их содержимое.

    Владелец хранится именем, а не ссылкой на символ: после склейки соседей
    фрагмент может покрывать несколько определений, и тогда честный ответ
    на вопрос «чей это код» — их общий родитель, а не первый из них.
    """

    start_line: int
    end_line: int
    text: str
    symbol_id: CodeSymbolId | None = None
    owner: str | None = None
    is_module_level: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    @classmethod
    def of_symbol(
        cls,
        symbol: CodeSymbol | None,
        *,
        start_line: int,
        end_line: int,
        text: str,
    ) -> "Fragment":
        return cls(
            start_line=start_line,
            end_line=end_line,
            text=text,
            symbol_id=symbol.id if symbol else None,
            owner=symbol.qualified_name if symbol else None,
        )


def build_chunks(
    *,
    root: Node,
    source: bytes,
    symbols: list[CodeSymbol],
    module_path: str,
    definition_nodes: frozenset[str] = DEFINITION_NODES,
) -> list[CodeChunk]:
    """Режет файл по границам определений, а не по числу символов.

    Наивное разбиение рвёт функции пополам и теряет принадлежность классу;
    фрагмент, вырванный так, для поиска почти бесполезен.

    Определения верхнего уровня становятся чанками целиком, слишком большие
    режутся по границам вложенных блоков, слишком мелкие соседи склеиваются.
    Код между определениями — импорты, константы — собирается в отдельный
    чанк: он часто нужен для понимания остального.
    """
    by_position = {(symbol.start_line, symbol.end_line): symbol for symbol in symbols}
    fragments: list[Fragment] = []
    module_lines: list[Fragment] = []

    for node in root.named_children:
        fragment = _fragment_of(node, source, by_position)
        if node.type in definition_nodes:
            fragments.extend(_flush(module_lines))
            module_lines = []
            fragments.extend(_split_if_large(node, source, fragment, by_position, definition_nodes))
        else:
            module_lines.append(fragment)

    fragments.extend(_flush(module_lines))

    return [
        _to_chunk(fragment, module_path=module_path)
        for fragment in _merge_small(fragments)
        if fragment.text.strip()
    ]


def _fragment_of(
    node: Node,
    source: bytes,
    by_position: dict[tuple[int, int], CodeSymbol],
) -> Fragment:
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    return Fragment.of_symbol(
        by_position.get((start_line, end_line)),
        start_line=start_line,
        end_line=end_line,
        text=source[node.start_byte : node.end_byte].decode("utf-8", errors="replace"),
    )


def _split_if_large(
    node: Node,
    source: bytes,
    fragment: Fragment,
    by_position: dict[tuple[int, int], CodeSymbol],
    definition_nodes: frozenset[str] = DEFINITION_NODES,
) -> list[Fragment]:
    """Разрезает крупное определение по вложенным блокам с перекрытием.

    Перекрытие в пару строк оставляет заголовок и первые строки тела в обоих
    кусках: без него второй кусок начинается посреди функции и непонятно,
    чей это код.
    """
    if fragment.tokens <= MAX_CHUNK_TOKENS:
        return [fragment]

    inner = _inner_definitions(node, definition_nodes)
    if not inner:
        return _split_by_lines(fragment)

    pieces: list[Fragment] = []
    header_end = inner[0].start_point[0]
    if header_end > node.start_point[0]:
        pieces.append(_slice(fragment, node.start_point[0] + 1, header_end))

    for child in inner:
        child_fragment = _fragment_of(child, source, by_position)
        pieces.extend(_split_if_large(child, source, child_fragment, by_position, definition_nodes))

    return pieces


def _inner_definitions(node: Node, definition_nodes: frozenset[str]) -> list[Node]:
    body = node.child_by_field_name("body")
    if body is None and node.type == "decorated_definition":
        definition = node.child_by_field_name("definition")
        body = definition.child_by_field_name("body") if definition is not None else None
    if body is None:
        return []

    return [child for child in body.named_children if child.type in definition_nodes]


def _split_by_lines(fragment: Fragment) -> list[Fragment]:
    """Последнее средство: длинное тело без вложенных определений."""
    lines = fragment.text.splitlines()
    step = max(1, len(lines) * MAX_CHUNK_TOKENS // max(fragment.tokens, 1))

    pieces: list[Fragment] = []
    start = 0
    while start < len(lines):
        end = min(start + step, len(lines))
        pieces.append(
            Fragment(
                start_line=fragment.start_line + start,
                end_line=fragment.start_line + end - 1,
                text="\n".join(lines[start:end]),
                symbol_id=fragment.symbol_id if start == 0 else None,
                owner=fragment.owner,
                is_module_level=fragment.is_module_level,
            )
        )
        if end >= len(lines):
            break
        start = max(end - OVERLAP_LINES, start + 1)

    return pieces


def _slice(fragment: Fragment, start_line: int, end_line: int) -> Fragment:
    lines = fragment.text.splitlines()
    offset = start_line - fragment.start_line
    length = end_line - start_line + 1
    return Fragment(
        start_line=start_line,
        end_line=end_line,
        text="\n".join(lines[offset : offset + length]),
        symbol_id=fragment.symbol_id,
        owner=fragment.owner,
    )


def _flush(module_lines: list[Fragment]) -> list[Fragment]:
    """Собирает накопленный код между определениями, соблюдая размер чанка.

    Собирать всё в один фрагмент нельзя: файл без определений — сплошные
    константы, таблицы прав, реестры — иначе даёт один чанк на весь файл.
    Такой чанк бесполезен для поиска и разрушителен для выдачи: попав в
    ответ, он приносит с собой файл целиком.

    Границы групп проходят по границам узлов, поэтому номера строк остаются
    точными. По строкам режется только одиночный узел, который сам не влез, —
    его текст непрерывен, и смещение считается от его собственного начала.
    """
    if not module_lines:
        return []

    pieces: list[Fragment] = []
    for group in _grouped_by_budget(module_lines):
        collected = _module_fragment(group)
        if collected.tokens <= MAX_CHUNK_TOKENS:
            pieces.append(collected)
            continue
        pieces.extend(_split_by_lines(collected))

    return pieces


def _grouped_by_budget(module_lines: list[Fragment]) -> list[list[Fragment]]:
    groups: list[list[Fragment]] = []
    current: list[Fragment] = []
    total = 0

    for fragment in module_lines:
        if current and total + fragment.tokens > MAX_CHUNK_TOKENS:
            groups.append(current)
            current = []
            total = 0
        current.append(fragment)
        total += fragment.tokens

    groups.append(current)
    return groups


def _module_fragment(group: list[Fragment]) -> Fragment:
    return Fragment(
        start_line=group[0].start_line,
        end_line=group[-1].end_line,
        text="\n".join(fragment.text for fragment in group),
        is_module_level=True,
    )


def _merge_small(fragments: list[Fragment]) -> list[Fragment]:
    """Склеивает соседние мелкие фрагменты до разумного размера.

    Отдельный чанк на однострочный метод засоряет индекс: такой фрагмент
    ничего не значит без соседей, а место в выдаче занимает.

    Модульный уровень из склейки исключён, даже когда состоит из пары
    импортов: на вопрос «откуда берётся это имя» отвечает именно он, и
    приклеенный к первой попавшейся функции он этот ответ теряет.
    """
    merged: list[Fragment] = []

    for fragment in fragments:
        previous = merged[-1] if merged else None
        joinable = (
            previous is not None
            and not previous.is_module_level
            and not fragment.is_module_level
            and previous.tokens < MIN_CHUNK_TOKENS
            and previous.tokens + fragment.tokens <= MAX_CHUNK_TOKENS
            and fragment.start_line >= previous.end_line
        )
        if previous is not None and joinable:
            merged[-1] = Fragment(
                start_line=previous.start_line,
                end_line=fragment.end_line,
                text=f"{previous.text}\n{fragment.text}",
                symbol_id=_merged_symbol_id(previous, fragment),
                owner=_common_owner(previous.owner, fragment.owner),
            )
        else:
            merged.append(fragment)

    return merged


def _merged_symbol_id(previous: Fragment, fragment: Fragment) -> CodeSymbolId | None:
    """Ссылка на символ переживает склейку, только если он там один."""
    if previous.symbol_id is None:
        return fragment.symbol_id
    if fragment.symbol_id is None or fragment.symbol_id == previous.symbol_id:
        return previous.symbol_id
    return None


def _common_owner(first: str | None, second: str | None) -> str | None:
    """Ближайшее имя, охватывающее оба фрагмента."""
    if first is None or second is None:
        return first or second

    shared: list[str] = []
    for left, right in zip(first.split("."), second.split("."), strict=False):
        if left != right:
            break
        shared.append(left)

    return ".".join(shared) or None


def _to_chunk(fragment: Fragment, *, module_path: str) -> CodeChunk:
    return CodeChunk(
        id=CodeChunkId(uuid4()),
        content=fragment.text,
        content_hash=content_hash(fragment.text),
        token_count=fragment.tokens,
        start_line=fragment.start_line,
        end_line=fragment.end_line,
        breadcrumb=_breadcrumb(fragment.owner, module_path=module_path),
        symbol_id=fragment.symbol_id,
    )


def _breadcrumb(owner: str | None, *, module_path: str) -> str:
    """Путь до фрагмента в терминах кода, а не файловой системы.

    Модуль остаётся точечным именем — таким, каким его пишут в import, —
    а вложенность внутри файла разворачивается стрелками:
    `app.report > Builder > build`.
    """
    if owner is None or owner == module_path:
        return module_path

    inner = owner.removeprefix(f"{module_path}.")
    return f"{module_path} > {inner.replace('.', ' > ')}"
