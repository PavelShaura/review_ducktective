import pytest

from ducktective.core.indexing.ports import (
    ParsedFile,
)
from ducktective.core.indexing.value_objects import (
    EdgeKind,
    SymbolKind,
)
from ducktective.indexing.parsers import (
    build_parser,
)
from ducktective.indexing.script_parser import (
    ScriptParser,
    module_path_of,
)


TYPESCRIPT = """
import { api } from "./client";

export interface Report {
  total: number;
}

export class ReportBuilder {
  constructor(private readonly source: string) {}

  build(items: number[]): Report {
    return { total: api.sum(items) };
  }
}

export const formatTotal = (report: Report): string => `${report.total}`;
"""

JAVASCRIPT = """
function openRegistry(url) {
  return window.open(url);
}

const handlers = {
  onSave: function (event) {
    openRegistry(event.target.dataset.url);
  },
};
"""


def parse(path: str, content: str) -> ParsedFile:
    return ScriptParser().parse(path=path, content=content)


def test_class_and_its_methods_become_symbols() -> None:
    parsed = parse("src/report/builder.ts", TYPESCRIPT)

    kinds = {str(symbol.qualified_name): symbol.kind for symbol in parsed.symbols}
    assert kinds["src.report.builder.ReportBuilder"] is SymbolKind.CLASS
    assert kinds["src.report.builder.ReportBuilder.build"] is SymbolKind.METHOD


def test_arrow_constant_counts_as_a_function() -> None:
    """Во фронте это обычный способ объявить функцию, а не константа."""
    parsed = parse("src/report/builder.ts", TYPESCRIPT)

    names = {str(symbol.qualified_name) for symbol in parsed.symbols}
    assert "src.report.builder.formatTotal" in names


def test_interface_is_indexed_as_a_type() -> None:
    parsed = parse("src/report/builder.ts", TYPESCRIPT)

    kinds = {str(symbol.qualified_name): symbol.kind for symbol in parsed.symbols}
    assert kinds["src.report.builder.Report"] is SymbolKind.CLASS


def test_plain_javascript_function_is_found() -> None:
    parsed = parse("static/js/registry.js", JAVASCRIPT)

    names = {symbol.name for symbol in parsed.symbols}
    assert "openRegistry" in names


def test_calls_and_imports_become_references() -> None:
    parsed = parse("src/report/builder.ts", TYPESCRIPT)

    kinds = {reference.kind for reference in parsed.references}
    targets = {str(reference.target_name) for reference in parsed.references}
    assert EdgeKind.IMPORTS in kinds
    assert "api.sum" in targets


def test_reference_belongs_to_the_symbol_it_was_written_in() -> None:
    """Вызов внутри метода принадлежит методу, а не файлу.

    Иначе обход графа отвечает «этот модуль что-то вызывает» — сведение,
    по которому нельзя понять, что сломается.
    """
    parsed = parse("src/report/builder.ts", TYPESCRIPT)
    by_id = {symbol.id: symbol for symbol in parsed.symbols}

    calls = [reference for reference in parsed.references if reference.kind is EdgeKind.CALLS]
    owners = {str(by_id[reference.source_symbol_id].qualified_name) for reference in calls}

    assert "src.report.builder.ReportBuilder.build" in owners


def test_broken_file_keeps_what_was_parsed() -> None:
    """Незакрытая скобка не должна уносить из индекса весь файл.

    Что именно уцелеет, решает грамматика: класс с оборванным методом
    целиком уходит в узел ошибки, а методы из него разбираются. Обещание
    здесь одно — разобранное не теряется, — и его достаточно: файл, который
    правят прямо сейчас, всё равно попадёт в индекс следующей сборкой.
    """
    parsed = parse("src/broken.ts", "export class A {\n  ok() { return 1; }\n  broken(")

    names = {symbol.name for symbol in parsed.symbols}
    assert "ok" in names


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/api/client.ts", "src.api.client"),
        ("src/api/index.ts", "src.api"),
        ("static/js/registry.js", "static.js.registry"),
    ],
)
def test_module_path_matches_what_is_written_in_imports(path: str, expected: str) -> None:
    assert module_path_of(path) == expected


@pytest.mark.parametrize(
    "path",
    ["src/app.ts", "src/app.tsx", "src/app.js", "src/app.jsx", "src/app.mjs"],
)
def test_every_flavour_is_parsed_by_its_own_grammar(path: str) -> None:
    """У TSX и JS по-разному разбираются угловые скобки.

    Ошибиться грамматикой значит получить дерево ошибок вместо файла.
    """
    parsed = parse(path, "export function render() { return 1; }")

    assert any(symbol.name == "render" for symbol in parsed.symbols)


def test_composite_parser_takes_every_supported_language() -> None:
    parser = build_parser()

    assert parser.supports("python")
    assert parser.supports("typescript")
    assert parser.supports("javascript")
    assert parser.supports("html")
    assert parser.supports("css")
    assert not parser.supports("brainfuck")
    assert not parser.supports(None)
