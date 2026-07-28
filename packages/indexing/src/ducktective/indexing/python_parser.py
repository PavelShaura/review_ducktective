from dataclasses import (
    dataclass,
)
from pathlib import (
    PurePosixPath,
)
from uuid import (
    uuid4,
)

import tree_sitter_python
from tree_sitter import (
    Language,
    Node,
    Parser,
)

from ducktective.core.indexing.entities import (
    CodeSymbol,
)
from ducktective.core.indexing.ports import (
    ParsedFile,
    SymbolReference,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.types import (
    CodeSymbolId,
    QualifiedName,
)
from ducktective.indexing.chunking import (
    build_chunks,
)
from ducktective.indexing.hashing import (
    content_hash,
)
from ducktective.indexing.references import (
    collect_imports,
    collect_references,
)


PYTHON = "python"

SOURCE_ROOT = "src"
PACKAGE_MARKER = "__init__"

DEFINITION_NODES = frozenset({"class_definition", "function_definition"})

DECORATED_DEFINITION = "decorated_definition"
ERROR_NODE = "ERROR"

PROPERTY_DECORATORS = frozenset({"property", "cached_property"})


@dataclass(frozen=True, kw_only=True)
class ParseContext:
    source: bytes
    module_path: str


class PythonParser:
    """Разбор Python через tree-sitter.

    Дерево строится грамматикой, а не регулярными выражениями: определения
    внутри классов, декораторы и вложенные функции иначе не различить.
    Синтаксически сломанный файл разбирается частично — tree-sitter отдаёт
    дерево с узлами ошибок, и всё, что удалось распознать, остаётся полезным.
    """

    def __init__(self) -> None:
        self._parser = Parser(Language(tree_sitter_python.language()))

    def supports(self, language: str | None) -> bool:
        return language == PYTHON

    def parse(self, *, path: str, content: str) -> ParsedFile:
        source = content.encode("utf-8")
        tree = self._parser.parse(source)
        context = ParseContext(source=source, module_path=module_path_of(path))

        module = _build_module_symbol(tree.root_node, context)
        definitions = _collect_definitions(tree.root_node, context, parent=module)
        symbols = [module, *definitions]

        return ParsedFile(
            symbols=symbols,
            chunks=build_chunks(
                root=tree.root_node,
                source=source,
                symbols=symbols,
                module_path=context.module_path,
            ),
            references=_collect_references(tree.root_node, context, symbols),
        )


def module_path_of(path: str) -> str:
    """Путь файла в точечной записи: app/report/builder.py → app.report.builder.

    Каталог `src` и всё, что выше него, отбрасывается: при src-layout
    импортируемое имя начинается после него, и `packages.core.src.ducktective`
    не соответствует ничему, что можно написать в import.
    """
    pure = PurePosixPath(path)
    parts = [*pure.parts[:-1], pure.stem]
    meaningful = [part for part in parts if part not in {"", ".", ".."}]

    if SOURCE_ROOT in meaningful:
        meaningful = meaningful[len(meaningful) - meaningful[::-1].index(SOURCE_ROOT) :]

    if meaningful and meaningful[-1] == PACKAGE_MARKER:
        meaningful = meaningful[:-1]

    return ".".join(meaningful)


def _collect_references(
    root: Node,
    context: ParseContext,
    symbols: list[CodeSymbol],
) -> list[SymbolReference]:
    """Собирает исходящие ссылки каждого символа.

    Таблица импортов строится один раз на файл: именно она превращает
    `Decimal` в коде в `decimal.Decimal` в графе.
    """
    imports = collect_imports(root, context.source)
    local_names = {
        symbol.qualified_name.removeprefix(f"{context.module_path}.")
        for symbol in symbols
        if symbol.kind is not SymbolKind.MODULE
    }
    nodes_by_symbol = _nodes_by_position(root, symbols)
    by_id = {symbol.id: symbol for symbol in symbols}

    references: list[SymbolReference] = []
    for symbol in symbols:
        node = nodes_by_symbol.get(symbol.id)
        if node is None:
            continue

        references.extend(
            collect_references(
                symbol,
                node,
                context.source,
                imports,
                module_path=context.module_path,
                local_names=local_names,
                self_scope=_enclosing_class(symbol, by_id),
            )
        )

    return references


def _enclosing_class(symbol: CodeSymbol, by_id: dict[CodeSymbolId, CodeSymbol]) -> str | None:
    """Класс, которому принадлежит символ, если он есть."""
    parent = by_id.get(symbol.parent_id) if symbol.parent_id else None
    return parent.qualified_name if parent and parent.kind is SymbolKind.CLASS else None


def _nodes_by_position(root: Node, symbols: list[CodeSymbol]) -> dict[CodeSymbolId, Node]:
    by_position = {(symbol.start_byte, symbol.end_byte): symbol.id for symbol in symbols}
    found: dict[CodeSymbolId, Node] = {}

    stack = [root]
    while stack:
        node = stack.pop()
        symbol_id = by_position.get((node.start_byte, node.end_byte))
        if symbol_id is not None and symbol_id not in found:
            found[symbol_id] = node
        stack.extend(node.named_children)

    return found


def _build_module_symbol(root: Node, context: ParseContext) -> CodeSymbol:
    text = _text_of(root, context.source)
    return CodeSymbol(
        id=CodeSymbolId(uuid4()),
        kind=SymbolKind.MODULE,
        name=context.module_path.rsplit(".", maxsplit=1)[-1],
        qualified_name=QualifiedName(context.module_path),
        start_line=root.start_point[0] + 1,
        end_line=max(root.end_point[0] + 1, root.start_point[0] + 1),
        start_byte=root.start_byte,
        end_byte=root.end_byte,
        content_hash=content_hash(text),
        docstring=_docstring_of(root, context.source),
    )


def _collect_definitions(
    node: Node,
    context: ParseContext,
    *,
    parent: CodeSymbol,
) -> list[CodeSymbol]:
    """Обходит тело узла, собирая объявленные в нём классы и функции.

    Вложенность выражается и в `parent_id`, и в полном имени: замыкание
    внутри метода получает имя вида `module.Class.method.helper`.
    """
    collected: list[CodeSymbol] = []

    for child in _definition_children(node):
        definition = _unwrap_decorated(child)
        name = _name_of(definition, context.source)
        if name is None:
            continue

        symbol = _build_symbol(child, definition, name, context, parent=parent)
        collected.append(symbol)
        collected.extend(_collect_definitions(definition, context, parent=symbol))

    return collected


def _definition_children(node: Node) -> list[Node]:
    """Определения, объявленные непосредственно в теле узла.

    Узлы ошибок проходятся насквозь: один неверный метод не должен уносить
    из индекса весь остальной класс. Восстановиться удаётся не всегда —
    незакрытая скобка съедает файл до конца, и тогда разбирать нечего.
    """
    collected: list[Node] = []
    for container in _containers_of(node):
        for child in container.named_children:
            if child.type in DEFINITION_NODES or child.type == DECORATED_DEFINITION:
                collected.append(child)
            elif child.type == ERROR_NODE:
                collected.extend(_definition_children(child))

    return sorted(collected, key=lambda child: child.start_byte)


def _containers_of(node: Node) -> list[Node]:
    """Места, где у узла могут лежать вложенные определения.

    У целого определения это его тело. У разобранного с ошибкой часть
    содержимого оседает в соседнем узле ошибки, а не в теле, — поэтому
    смотреть приходится в оба места.
    """
    if node.type not in DEFINITION_NODES:
        return [node]

    body = node.child_by_field_name("body")
    containers = [body] if body is not None else []
    containers.extend(child for child in node.named_children if child.type == ERROR_NODE)
    return containers


def _unwrap_decorated(node: Node) -> Node:
    if node.type != DECORATED_DEFINITION:
        return node

    definition = node.child_by_field_name("definition")
    return definition if definition is not None else node


def _build_symbol(
    outer: Node,
    definition: Node,
    name: str,
    context: ParseContext,
    *,
    parent: CodeSymbol,
) -> CodeSymbol:
    """Собирает символ из узла определения.

    Границы берутся у внешнего узла, чтобы декораторы попадали внутрь
    символа: `@property` без своей функции ничего не значит, и при
    пересечении с диффом изменение декоратора обязано указывать на неё.
    """
    text = _text_of(outer, context.source)
    return CodeSymbol(
        id=CodeSymbolId(uuid4()),
        kind=_kind_of(definition, outer, parent),
        name=name,
        qualified_name=QualifiedName(f"{parent.qualified_name}.{name}"),
        start_line=outer.start_point[0] + 1,
        end_line=outer.end_point[0] + 1,
        start_byte=outer.start_byte,
        end_byte=outer.end_byte,
        content_hash=content_hash(text),
        parent_id=parent.id,
        signature=_signature_of(definition, context.source),
        docstring=_docstring_of(definition, context.source),
    )


def _kind_of(definition: Node, outer: Node, parent: CodeSymbol) -> SymbolKind:
    if definition.type == "class_definition":
        return SymbolKind.CLASS
    if _has_property_decorator(outer):
        return SymbolKind.PROPERTY
    if parent.kind is SymbolKind.CLASS:
        return SymbolKind.METHOD
    return SymbolKind.FUNCTION


def _has_property_decorator(node: Node) -> bool:
    if node.type != DECORATED_DEFINITION:
        return False

    for child in node.named_children:
        if child.type != "decorator" or child.text is None:
            continue
        name = child.text.decode("utf-8", errors="replace").lstrip("@").split("(")[0]
        if name.rsplit(".", maxsplit=1)[-1] in PROPERTY_DECORATORS:
            return True
    return False


def _name_of(definition: Node, source: bytes) -> str | None:
    name_node = definition.child_by_field_name("name")
    return None if name_node is None else _text_of(name_node, source)


def _signature_of(definition: Node, source: bytes) -> str | None:
    """Заголовок определения без тела: имя, параметры и тип возврата."""
    name_node = definition.child_by_field_name("name")
    if name_node is None:
        return None

    body = definition.child_by_field_name("body")
    end_byte = body.start_byte if body is not None else definition.end_byte
    header = source[definition.start_byte : end_byte].decode("utf-8", errors="replace")
    return header.strip().rstrip(":").strip() or None


def _docstring_of(node: Node, source: bytes) -> str | None:
    body = node.child_by_field_name("body") if node.type in DEFINITION_NODES else node
    if body is None or not body.named_children:
        return None

    first = body.named_children[0]
    if first.type != "expression_statement" or not first.named_children:
        return None

    literal = first.named_children[0]
    if literal.type != "string":
        return None

    return _text_of(literal, source).strip("\"'").strip() or None


def _text_of(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
