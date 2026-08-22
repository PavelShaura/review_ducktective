"""Разбор JavaScript и TypeScript через tree-sitter.

Отдельный парсер, а не ветка внутри питоновского: совпадает только форма
работы — обойти дерево, собрать символы, нарезать чанки, — а узлы, правила
именования и способ объявить функцию разные настолько, что общая реализация
свелась бы к сплошным условиям по языку.

Грамматик три, и выбирается она по расширению: у TSX и JS различается разбор
угловых скобок, и `<Foo>` в одном языке приведение типа, а в другом элемент.
Ошибиться грамматикой значит получить дерево ошибок вместо файла.
"""

from dataclasses import (
    dataclass,
)
from pathlib import (
    PurePosixPath,
)
from uuid import (
    uuid4,
)

import tree_sitter_javascript
import tree_sitter_typescript
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
    EdgeKind,
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


JAVASCRIPT = "javascript"
TYPESCRIPT = "typescript"

CLASS_NODES = frozenset({"class_declaration", "abstract_class_declaration", "class"})
FUNCTION_NODES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_signature",
    }
)
METHOD_NODES = frozenset({"method_definition", "method_signature"})
TYPE_NODES = frozenset({"interface_declaration", "type_alias_declaration", "enum_declaration"})
VALUE_NODES = frozenset({"lexical_declaration", "variable_declaration"})
FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "function"})

DEFINITION_NODES = frozenset(
    CLASS_NODES | FUNCTION_NODES | METHOD_NODES | TYPE_NODES | VALUE_NODES | {"export_statement"}
)

EXPORT_NODE = "export_statement"
ERROR_NODE = "ERROR"
CALL_NODE = "call_expression"
IMPORT_NODE = "import_statement"

BODY_FIELDS = ("body", "value", "declaration")
"""Поля, за которыми у узла лежат вложенные определения.

У класса это `body`, у экспорта — `declaration`, у объявления константы
со стрелочной функцией — `value`. Одного поля не хватает ни одному языку
семейства.
"""


@dataclass(frozen=True, kw_only=True)
class ScriptContext:
    source: bytes
    module_path: str


class ScriptParser:
    """Разбор JavaScript и TypeScript.

    Функция объявляется четырьмя способами — `function`, метод класса,
    `const x = () => {}` и экспорт любого из них, — и все четыре считаются
    определением: в коде фронта стрелочная константа встречается чаще
    классического объявления, и пропустить её значит пропустить половину.
    """

    def __init__(self) -> None:
        self._javascript = Parser(Language(tree_sitter_javascript.language()))
        self._typescript = Parser(Language(tree_sitter_typescript.language_typescript()))
        self._tsx = Parser(Language(tree_sitter_typescript.language_tsx()))

    def supports(self, language: str | None) -> bool:
        return language in {JAVASCRIPT, TYPESCRIPT}

    def parse(self, *, path: str, content: str) -> ParsedFile:
        source = content.encode("utf-8")
        tree = self._parser_for(path).parse(source)
        context = ScriptContext(source=source, module_path=module_path_of(path))

        module = _module_symbol(tree.root_node, context)
        definitions = _collect_definitions(tree.root_node, context, parent=module)
        symbols = [module, *definitions]

        return ParsedFile(
            symbols=symbols,
            chunks=build_chunks(
                root=tree.root_node,
                source=source,
                symbols=symbols,
                module_path=context.module_path,
                definition_nodes=DEFINITION_NODES,
            ),
            references=_collect_references(tree.root_node, context, symbols),
        )

    def _parser_for(self, path: str) -> Parser:
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".tsx":
            return self._tsx
        if suffix in {".ts", ".mts", ".cts"}:
            return self._typescript
        return self._javascript


def module_path_of(path: str) -> str:
    """Путь файла точками: src/api/client.ts → src.api.client.

    Расширение отбрасывается, `index` — тоже: `import { api } from "./api"`
    приводит к каталогу, а не к файлу внутри него, и имя символа должно
    совпадать с тем, что пишут в импорте.
    """
    pure = PurePosixPath(path)
    parts = [*pure.parts[:-1], pure.stem]
    meaningful = [part for part in parts if part not in {"", ".", ".."}]

    if meaningful and meaningful[-1] == "index":
        meaningful = meaningful[:-1]

    return ".".join(meaningful)


def _module_symbol(root: Node, context: ScriptContext) -> CodeSymbol:
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
    )


def _collect_definitions(
    node: Node,
    context: ScriptContext,
    *,
    parent: CodeSymbol,
) -> list[CodeSymbol]:
    collected: list[CodeSymbol] = []

    for child in _definition_children(node):
        definition = _unwrap_export(child)
        name = _name_of(definition, context.source)
        if name is None:
            continue

        symbol = _build_symbol(child, definition, name, context, parent=parent)
        collected.append(symbol)
        collected.extend(_collect_definitions(definition, context, parent=symbol))

    return collected


def _definition_children(node: Node) -> list[Node]:
    """Определения, объявленные непосредственно в этом узле.

    Узлы ошибок проходятся насквозь: один сломанный метод не должен уносить
    из индекса весь класс.
    """
    collected: list[Node] = []

    for container in _containers_of(node):
        for child in container.named_children:
            if _is_definition(child):
                collected.append(child)
            elif child.type == ERROR_NODE:
                collected.extend(_definition_children(child))

    return sorted(collected, key=lambda child: child.start_byte)


def _containers_of(node: Node) -> list[Node]:
    if node.type in CLASS_NODES:
        body = node.child_by_field_name("body")
        return [body] if body is not None else []

    if node.type == EXPORT_NODE:
        return [node]

    if _is_definition(node):
        return []

    return [node]


def _is_definition(node: Node) -> bool:
    if node.type in CLASS_NODES | FUNCTION_NODES | METHOD_NODES | TYPE_NODES:
        return True
    if node.type == EXPORT_NODE:
        return _exported_declaration(node) is not None
    if node.type in VALUE_NODES:
        return _declared_function(node) is not None
    return False


def _unwrap_export(node: Node) -> Node:
    if node.type != EXPORT_NODE:
        return node
    declaration = _exported_declaration(node)
    return declaration if declaration is not None else node


def _exported_declaration(node: Node) -> Node | None:
    declaration = node.child_by_field_name("declaration")
    if declaration is None:
        return None
    if declaration.type in VALUE_NODES and _declared_function(declaration) is None:
        return None
    return declaration


def _declared_function(node: Node) -> Node | None:
    """Объявление, за которым стоит функция: `const handle = () => {}`.

    Константа со стрелочной функцией — обычный способ объявить функцию
    во фронте, и не считать её определением значит потерять из индекса
    большую часть модулей. Константа со значением определением не считается:
    иначе символами станут все настройки подряд.
    """
    for declarator in node.named_children:
        if declarator.type != "variable_declarator":
            continue
        value = declarator.child_by_field_name("value")
        if value is not None and value.type in FUNCTION_VALUES:
            return declarator
    return None


def _name_of(node: Node, source: bytes) -> str | None:
    if node.type in VALUE_NODES:
        declarator = _declared_function(node)
        return _name_of(declarator, source) if declarator is not None else None

    name = node.child_by_field_name("name")
    return _text_of(name, source) if name is not None else None


def _build_symbol(
    outer: Node,
    definition: Node,
    name: str,
    context: ScriptContext,
    *,
    parent: CodeSymbol,
) -> CodeSymbol:
    text = _text_of(outer, context.source)
    return CodeSymbol(
        id=CodeSymbolId(uuid4()),
        kind=_kind_of(definition, parent),
        name=name,
        qualified_name=QualifiedName(f"{parent.qualified_name}.{name}"),
        start_line=outer.start_point[0] + 1,
        end_line=outer.end_point[0] + 1,
        start_byte=outer.start_byte,
        end_byte=outer.end_byte,
        content_hash=content_hash(text),
        parent_id=parent.id,
        signature=_signature_of(definition, context.source),
    )


def _kind_of(definition: Node, parent: CodeSymbol) -> SymbolKind:
    if definition.type in CLASS_NODES or definition.type in TYPE_NODES:
        return SymbolKind.CLASS
    if definition.type in METHOD_NODES or parent.kind is SymbolKind.CLASS:
        return SymbolKind.METHOD
    return SymbolKind.FUNCTION


def _signature_of(node: Node, source: bytes) -> str | None:
    """Первая строка объявления: имя, параметры и тип возврата.

    Тело в сигнатуру не входит — от неё нужен контракт, а тело у соседа
    по графу заняло бы весь бюджет.
    """
    text = _text_of(node, source)
    if not text:
        return None

    head = text.split("\n", maxsplit=1)[0].strip()
    return head.removesuffix("{").strip() or None


def _collect_references(
    root: Node,
    context: ScriptContext,
    symbols: list[CodeSymbol],
) -> list[SymbolReference]:
    """Вызовы и импорты, найденные в файле.

    Разрешаются они позже и не здесь: парсер отвечает за то, что в файле
    написано, а связать имя с определением можно только зная остальные
    файлы репозитория.
    """
    by_id = {symbol.id: symbol for symbol in symbols}
    ordered = sorted(symbols, key=lambda symbol: (symbol.start_byte, -symbol.end_byte))
    references: list[SymbolReference] = []

    for node in _walk(root):
        if node.type == CALL_NODE:
            target = _called_name(node, context.source)
            kind = EdgeKind.CALLS
        elif node.type == IMPORT_NODE:
            target = _imported_module(node, context.source)
            kind = EdgeKind.IMPORTS
        else:
            continue

        if not target:
            continue

        owner = _owner_of(node, ordered, by_id)
        references.append(
            SymbolReference(
                source_symbol_id=owner.id,
                target_name=QualifiedName(target),
                kind=kind,
            )
        )

    return references


def _called_name(node: Node, source: bytes) -> str | None:
    function = node.child_by_field_name("function")
    if function is None:
        return None

    text = _text_of(function, source)
    return text.split("(", maxsplit=1)[0].strip() or None


def _imported_module(node: Node, source: bytes) -> str | None:
    source_node = node.child_by_field_name("source")
    if source_node is None:
        return None

    text = _text_of(source_node, source).strip("\"'`")
    return text.replace("/", ".").removeprefix("..").removeprefix(".") or None


def _owner_of(
    node: Node,
    ordered: list[CodeSymbol],
    by_id: dict[CodeSymbolId, CodeSymbol],
) -> CodeSymbol:
    """Символ, внутри которого лежит узел, — самый внутренний из подходящих."""
    owner = ordered[0]
    for symbol in ordered:
        if symbol.start_byte <= node.start_byte and node.end_byte <= symbol.end_byte:
            owner = symbol
    return by_id[owner.id]


def _walk(node: Node) -> list[Node]:
    collected = [node]
    for child in node.named_children:
        collected.extend(_walk(child))
    return collected


def _text_of(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
