from dataclasses import (
    dataclass,
    field,
)

from tree_sitter import (
    Node,
)

from ducktective.core.indexing.entities import (
    CodeSymbol,
)
from ducktective.core.indexing.ports import (
    SymbolReference,
)
from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.core.types import (
    QualifiedName,
)


ATTRIBUTE_CONFIDENCE = 0.5

SELF_NAMES = frozenset({"self", "cls"})

BUILTIN_NAMES = frozenset(
    {
        "print",
        "len",
        "range",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "isinstance",
        "getattr",
        "setattr",
        "hasattr",
        "super",
        "sorted",
        "sum",
        "min",
        "max",
        "any",
        "all",
        "enumerate",
        "zip",
        "open",
        "type",
        "repr",
        "format",
        "next",
        "iter",
    }
)


@dataclass
class ImportTable:
    """Что именно означают имена, встреченные в этом модуле.

    Разрешение имён в Python принципиально неполно: значение имени может
    определиться только во время выполнения. Таблица покрывает статически
    видимую часть — импорты, — а остальное остаётся догадкой.
    """

    aliases: dict[str, str] = field(default_factory=dict)

    def resolve(self, name: str) -> str | None:
        head, _, tail = name.partition(".")
        target = self.aliases.get(head)
        if target is None:
            return None
        return f"{target}.{tail}" if tail else target


def collect_imports(root: Node, source: bytes) -> ImportTable:
    """Собирает соответствие «имя в коде → полное имя» из импортов модуля."""
    table = ImportTable()

    for node in _walk(root):
        if node.type == "import_statement":
            _read_plain_import(node, source, table)
        elif node.type == "import_from_statement":
            _read_from_import(node, source, table)

    return table


def collect_references(
    symbol: CodeSymbol,
    node: Node,
    source: bytes,
    imports: ImportTable,
    *,
    module_path: str,
    local_names: set[str],
    self_scope: str | None = None,
) -> list[SymbolReference]:
    """Ссылки, исходящие из одного символа.

    Вложенные определения пропускаются: их ссылки принадлежат им самим,
    иначе класс присвоил бы себе всё, что делают его методы.
    """
    references: list[SymbolReference] = []
    seen: set[tuple[str, EdgeKind]] = set()

    for kind, raw_name in _raw_references(node, source):
        target = _resolve(
            raw_name,
            imports,
            module_path=module_path,
            local_names=local_names,
            self_scope=self_scope,
        )
        if target is None:
            continue

        key = (target, kind)
        if key in seen:
            continue

        seen.add(key)
        references.append(
            SymbolReference(
                source_symbol_id=symbol.id,
                kind=kind,
                target_name=QualifiedName(target),
                confidence=ATTRIBUTE_CONFIDENCE if "." in raw_name else 1.0,
            )
        )

    return references


def _raw_references(node: Node, source: bytes) -> list[tuple[EdgeKind, str]]:
    """Сырые имена, на которые ссылается символ.

    Конструктор исключения не порождает отдельного вызова: `raise ValueError(...)`
    — это одно событие, и два ребра на него описывали бы одну и ту же строку
    дважды.
    """
    collected: list[tuple[EdgeKind, str]] = []

    collected.extend((EdgeKind.INHERITS, name) for name in _superclasses(node, source))
    collected.extend((EdgeKind.DECORATES, name) for name in _decorators(node, source))

    body = _walk_own_body(node)
    raised_calls = {
        _span(child.named_children[0])
        for child in body
        if child.type == "raise_statement" and child.named_children
    }

    for child in body:
        if child.type == "call" and _span(child) not in raised_calls:
            name = _callee_name(child, source)
            if name is not None:
                collected.append((EdgeKind.CALLS, name))
        elif child.type == "raise_statement":
            name = _raised_name(child, source)
            if name is not None:
                collected.append((EdgeKind.RAISES, name))

    return collected


def _span(node: Node) -> tuple[int, int]:
    return (node.start_byte, node.end_byte)


def _resolve(
    raw_name: str,
    imports: ImportTable,
    *,
    module_path: str,
    local_names: set[str],
    self_scope: str | None,
) -> str | None:
    """Приводит имя из кода к полному имени.

    Порядок соответствует тому, как имя ищет сам интерпретатор: сначала то,
    что объявлено рядом, затем импорты. Обращение через `self` разрешается
    в свой класс, а не в модуль: `self.normalize` внутри метода — это соседний
    метод, и именно эта связь отвечает на вопрос «что сломается».

    Встроенные функции отбрасываются: они засоряют граф, ничего не объясняя.
    """
    head, _, tail = raw_name.partition(".")

    if head in SELF_NAMES:
        if not tail:
            return None
        return f"{self_scope}.{tail}" if self_scope else f"{module_path}.{tail}"

    if raw_name in BUILTIN_NAMES:
        return None

    if head in local_names:
        return f"{module_path}.{raw_name}"

    return imports.resolve(raw_name) or raw_name


def _superclasses(node: Node, source: bytes) -> list[str]:
    definition = _definition_of(node)
    if definition is None or definition.type != "class_definition":
        return []

    arguments = definition.child_by_field_name("superclasses")
    if arguments is None:
        return []

    return [
        _text(child, source)
        for child in arguments.named_children
        if child.type in {"identifier", "attribute"}
    ]


def _decorators(node: Node, source: bytes) -> list[str]:
    if node.type != "decorated_definition":
        return []

    names: list[str] = []
    for child in node.named_children:
        if child.type != "decorator" or not child.named_children:
            continue

        expression = child.named_children[0]
        if expression.type == "call":
            callee = expression.child_by_field_name("function")
            expression = callee if callee is not None else expression
        if expression.type in {"identifier", "attribute"}:
            names.append(_text(expression, source))

    return names


def _callee_name(call: Node, source: bytes) -> str | None:
    function = call.child_by_field_name("function")
    if function is None or function.type not in {"identifier", "attribute"}:
        return None
    return _text(function, source)


def _raised_name(statement: Node, source: bytes) -> str | None:
    if not statement.named_children:
        return None

    raised = statement.named_children[0]
    if raised.type == "call":
        return _callee_name(raised, source)
    if raised.type in {"identifier", "attribute"}:
        return _text(raised, source)
    return None


def _definition_of(node: Node) -> Node | None:
    if node.type == "decorated_definition":
        return node.child_by_field_name("definition")
    return node


def _walk_own_body(node: Node) -> list[Node]:
    """Узлы символа, кроме тел вложенных определений.

    У модуля тела как отдельного узла нет — им является он сам, поэтому
    иначе весь код между определениями остался бы без связей.
    """
    definition = _definition_of(node)
    if definition is None:
        return []

    body = definition.child_by_field_name("body") or definition

    collected: list[Node] = []
    stack = list(body.named_children)
    while stack:
        current = stack.pop()
        if current.type in {"class_definition", "function_definition", "decorated_definition"}:
            continue
        collected.append(current)
        stack.extend(current.named_children)

    return collected


def _walk(node: Node) -> list[Node]:
    collected: list[Node] = []
    stack = [node]
    while stack:
        current = stack.pop()
        collected.append(current)
        stack.extend(current.named_children)
    return collected


def _read_plain_import(node: Node, source: bytes, table: ImportTable) -> None:
    for child in node.named_children:
        if child.type == "dotted_name":
            name = _text(child, source)
            table.aliases[name.split(".")[0]] = name.split(".")[0]
            table.aliases[name] = name
        elif child.type == "aliased_import":
            _read_alias(child, source, table, prefix="")


def _read_from_import(node: Node, source: bytes, table: ImportTable) -> None:
    module_node = node.child_by_field_name("module_name")
    prefix = _text(module_node, source) if module_node is not None else ""

    for child in node.named_children:
        if child is module_node:
            continue
        if child.type == "dotted_name":
            name = _text(child, source)
            table.aliases[name] = f"{prefix}.{name}" if prefix else name
        elif child.type == "aliased_import":
            _read_alias(child, source, table, prefix=prefix)


def _read_alias(node: Node, source: bytes, table: ImportTable, *, prefix: str) -> None:
    name_node = node.child_by_field_name("name")
    alias_node = node.child_by_field_name("alias")
    if name_node is None or alias_node is None:
        return

    name = _text(name_node, source)
    table.aliases[_text(alias_node, source)] = f"{prefix}.{name}" if prefix else name


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
