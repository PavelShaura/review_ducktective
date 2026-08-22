"""Выбор разбора по языку файла.

Реализует тот же порт, что и каждый парсер по отдельности: `BuildIndex`
не должен знать, сколько их и какие. Добавить язык — значит добавить парсер
в этот список и расширение в `detect_language`, а не править индексацию.

Порядок важен: первый, кто отвечает «поддерживаю», и разбирает. Языки не
пересекаются, поэтому порядок здесь — вопрос читаемости, а не разрешения
конфликтов.
"""

from ducktective.core.diff.languages import (
    detect_language,
)
from ducktective.core.indexing.ports import (
    CodeParser,
    ParsedFile,
)
from ducktective.indexing.python_parser import (
    PythonParser,
)
from ducktective.indexing.script_parser import (
    ScriptParser,
)
from ducktective.indexing.text_parser import (
    TextParser,
)


class CompositeParser:
    """Разбор любого поддерживаемого языка."""

    def __init__(self, parsers: list[CodeParser] | None = None) -> None:
        self._parsers: list[CodeParser] = parsers or [
            PythonParser(),
            ScriptParser(),
            TextParser(),
        ]

    def supports(self, language: str | None) -> bool:
        return any(parser.supports(language) for parser in self._parsers)

    def parse(self, *, path: str, content: str) -> ParsedFile:
        language = detect_language(path)
        for parser in self._parsers:
            if parser.supports(language):
                return parser.parse(path=path, content=content)

        raise ValueError(f"Разбор для {path} не найден: язык {language}")


def build_parser() -> CompositeParser:
    """Парсер со всеми языками, которые проект умеет разбирать."""
    return CompositeParser()
