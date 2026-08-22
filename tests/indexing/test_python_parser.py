from ducktective.core.diff.value_objects import (
    LineRange,
)
from ducktective.core.indexing.ports import (
    ParsedFile,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.indexing.python_parser import (
    PythonParser,
    module_path_of,
)


SAMPLE = '''"""Отчёты по успеваемости."""

import json
from decimal import Decimal

TAX_RATE = Decimal("0.2")


class ReportBuilder:
    """Собирает отчёт из оценок."""

    def __init__(self, session):
        self._session = session

    @property
    def is_ready(self) -> bool:
        return self._session is not None

    def build(self, student_id: int) -> dict:
        """Возвращает отчёт одного студента."""
        grades = self._session.query(student_id)
        return {"total": sum(grades)}


def render(report: dict) -> str:
    return json.dumps(report)
'''


def parse(content: str = SAMPLE, path: str = "app/report.py") -> ParsedFile:
    return PythonParser().parse(path=path, content=content)


def test_module_path_drops_source_root() -> None:
    assert module_path_of("packages/core/src/ducktective/core/review/entities.py") == (
        "ducktective.core.review.entities"
    )


def test_module_path_of_flat_layout() -> None:
    assert module_path_of("app/report/builder.py") == "app.report.builder"


def test_package_init_is_named_by_its_directory() -> None:
    assert module_path_of("app/report/__init__.py") == "app.report"


def test_module_becomes_a_symbol() -> None:
    parsed = parse()

    module = parsed.symbols[0]
    assert module.kind is SymbolKind.MODULE
    assert module.qualified_name == "app.report"
    assert module.docstring == "Отчёты по успеваемости."


def test_classes_methods_and_functions_are_distinguished() -> None:
    parsed = parse()
    kinds = {str(symbol.qualified_name): symbol.kind for symbol in parsed.symbols}

    assert kinds["app.report.ReportBuilder"] is SymbolKind.CLASS
    assert kinds["app.report.ReportBuilder.build"] is SymbolKind.METHOD
    assert kinds["app.report.ReportBuilder.is_ready"] is SymbolKind.PROPERTY
    assert kinds["app.report.render"] is SymbolKind.FUNCTION


def test_nesting_is_recorded_both_ways() -> None:
    parsed = parse()
    by_name = {str(symbol.qualified_name): symbol for symbol in parsed.symbols}

    builder = by_name["app.report.ReportBuilder"]
    build = by_name["app.report.ReportBuilder.build"]

    assert build.parent_id == builder.id
    assert build.qualified_name.startswith(builder.qualified_name)


def test_signature_excludes_body() -> None:
    parsed = parse()
    build = next(symbol for symbol in parsed.symbols if symbol.name == "build")

    assert build.signature == "def build(self, student_id: int) -> dict"
    assert build.docstring == "Возвращает отчёт одного студента."


def test_decorator_belongs_to_its_definition() -> None:
    parsed = parse()
    is_ready = next(symbol for symbol in parsed.symbols if symbol.name == "is_ready")

    assert SAMPLE.splitlines()[is_ready.start_line - 1].strip() == "@property"


def test_hunk_lines_resolve_to_the_innermost_symbol() -> None:
    parsed = parse()
    build = next(symbol for symbol in parsed.symbols if symbol.name == "build")

    covering = [
        symbol.qualified_name
        for symbol in parsed.symbols
        if symbol.overlaps(LineRange(start=build.start_line + 1, end=build.start_line + 1))
    ]

    assert covering == [
        "app.report",
        "app.report.ReportBuilder",
        "app.report.ReportBuilder.build",
    ]


def test_one_broken_method_does_not_hide_the_rest_of_the_class() -> None:
    """Определения из-под узла ошибки достаются: индексируется чужой код."""
    parsed = parse(
        "class A:\n    def ok(self):\n        return 1\n\n    def bad(self)\n        return 2\n"
    )

    names = {str(symbol.qualified_name) for symbol in parsed.symbols}
    assert "app.report.A" in names
    assert "app.report.A.ok" in names


def test_unclosed_bracket_leaves_nothing_to_parse() -> None:
    """Граница восстановления: такая поломка съедает файл целиком."""
    parsed = parse("class Broken:\n    def method(self):\n        return (((\n")

    assert [symbol.kind for symbol in parsed.symbols] == [SymbolKind.MODULE]


def test_empty_file_has_only_module_symbol() -> None:
    parsed = parse("")

    assert [symbol.kind for symbol in parsed.symbols] == [SymbolKind.MODULE]
    assert parsed.chunks == []


def test_language_support_is_declared() -> None:
    parser = PythonParser()

    assert parser.supports("python") is True
    assert parser.supports("typescript") is False
    assert parser.supports(None) is False
