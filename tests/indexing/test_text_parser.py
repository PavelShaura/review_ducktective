from ducktective.core.indexing.ports import (
    ParsedFile,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.indexing.parsers import (
    build_parser,
)
from ducktective.indexing.text_parser import (
    TextParser,
)


TEMPLATE = """<div class="report-card">
  <h2>Отчёт</h2>
  <button data-action="print">Печать</button>
</div>
"""

STYLES = """.report-card {
  padding: 1rem;
}

.report-card__title {
  font-weight: 600;
}
"""

REQUIREMENTS = """django==4.2.11
celery==5.3.6
tablib==3.9.0
"""


def parse(path: str, content: str) -> ParsedFile:
    return TextParser().parse(path=path, content=content)


def test_markup_is_searchable_without_symbols() -> None:
    """У шаблона нет определений, но найтись он обязан."""
    parsed = parse("templates/report.html", TEMPLATE)

    assert len(parsed.symbols) == 1
    assert parsed.symbols[0].kind is SymbolKind.MODULE
    assert parsed.chunks
    assert "report-card" in parsed.chunks[0].content


def test_file_symbol_names_the_place() -> None:
    """Чанк не к чему привязать без символа, а в выдаче нечего назвать."""
    parsed = parse("static/css/report.css", STYLES)

    symbol = parsed.symbols[0]
    assert symbol.name == "report.css"
    assert str(symbol.qualified_name) == "static/css/report.css"


def test_dependencies_become_searchable() -> None:
    """Вопрос «какая версия библиотеки» иначе решается окольным путём."""
    parsed = parse("requirements/base.txt", REQUIREMENTS)

    assert "tablib==3.9.0" in parsed.chunks[0].content


def test_graph_is_not_invented_for_markup() -> None:
    """Связывать в разметке нечего, и притворяться не нужно."""
    assert parse("templates/report.html", TEMPLATE).references == []


def test_empty_file_gives_no_chunks() -> None:
    assert parse("static/css/empty.css", "\n\n  \n").chunks == []


def test_long_file_is_cut_into_several_chunks() -> None:
    """Куском на весь файл поиск отвечать не должен: он приносит с собой всё."""
    rule = ".rule {\n  padding: 1rem;\n}\n\n"
    parsed = parse("static/css/big.css", rule * 200)

    assert len(parsed.chunks) > 1


def test_markup_goes_through_the_composite_parser() -> None:
    parsed = build_parser().parse(path="templates/report.html", content=TEMPLATE)

    assert parsed.chunks
    assert parsed.references == []
