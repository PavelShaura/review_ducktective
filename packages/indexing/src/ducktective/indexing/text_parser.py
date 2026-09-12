"""Индексация файлов, у которых нет символов: разметка, стили, конфигурация.

Шаблон, таблица стилей и список зависимостей — не код в том смысле, в каком
им является функция: у них нет ни определений, ни вызовов, и графу символов
там нечего связывать. Но найтись они обязаны: вопрос «где этот экран» ведёт
в шаблон, «какая версия библиотеки» — в список зависимостей, и без них
ответ приходится собирать окольным путём через упоминания в коде.

Поэтому здесь нет разбора грамматикой — только нарезка на куски по размеру
и границам пустых строк. Дешевле, чем грамматика на каждый формат, и честнее:
притворяться, что у CSS есть символы, значит завести десятки тысяч записей,
по которым никто не спрашивает.
"""

from pathlib import (
    PurePosixPath,
)
from uuid import (
    uuid4,
)

from ducktective.core.indexing.entities import (
    CodeChunk,
    CodeSymbol,
)
from ducktective.core.indexing.ports import (
    ParsedFile,
)
from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    QualifiedName,
)
from ducktective.indexing.hashing import (
    content_hash,
    estimate_tokens,
)


MARKUP_LANGUAGES = frozenset({"html", "css", "scss"})
TEXT_LANGUAGES = frozenset({"markdown", "yaml", "toml", "json", "text", "dockerfile", "make"})

MAX_CHUNK_TOKENS = 400
"""Сколько токенов берёт один кусок разметки.

Меньше, чем у кода: у шаблона нет границ определений, по которым можно
резать осмысленно, и крупный кусок несёт больше лишнего. Четырёхсот
токенов хватает на секцию страницы или блок правил.
"""

HARD_CHUNK_TOKENS = 2 * MAX_CHUNK_TOKENS
"""Предел, после которого кусок режется и без пустой строки.

Файл без пустых строк — минифицированный или сгенерированный — иначе идёт
одним куском на весь себя, а модель эмбеддингов такой кусок обрезает молча.
"""

MIN_CHUNK_LINES = 3


class TextParser:
    """Нарезка файлов без символов на куски для поиска.

    Символ заводится ровно один — сам файл: без него чанк не к чему привязать,
    а в выдаче нечего назвать. Он и служит ответом на «где это»: путь и строки.
    """

    def supports(self, language: str | None) -> bool:
        return language in MARKUP_LANGUAGES | TEXT_LANGUAGES

    def parse(self, *, path: str, content: str) -> ParsedFile:
        source = content.encode("utf-8")
        lines = content.splitlines()
        name = PurePosixPath(path).name

        file_symbol = CodeSymbol(
            id=CodeSymbolId(uuid4()),
            kind=SymbolKind.MODULE,
            name=name,
            qualified_name=QualifiedName(path),
            start_line=1,
            end_line=max(len(lines), 1),
            start_byte=0,
            end_byte=len(source),
            content_hash=content_hash(content),
        )

        return ParsedFile(
            symbols=[file_symbol],
            chunks=_chunks_of(lines, path, file_symbol),
            references=[],
        )


def _chunks_of(lines: list[str], path: str, symbol: CodeSymbol) -> list[CodeChunk]:
    """Режет файл по пустым строкам, пока кусок не станет достаточно большим.

    Пустая строка — единственная граница смысла, доступная без грамматики:
    ею отделены правило от правила, секция от секции, блок настроек от
    следующего. Резать по числу строк значило бы рвать их посередине.
    """
    chunks: list[CodeChunk] = []
    current: list[str] = []
    start = 1

    for number, line in enumerate(lines, start=1):
        current.append(line)
        tokens = estimate_tokens("\n".join(current))
        is_boundary = not line.strip() and len(current) >= MIN_CHUNK_LINES
        is_full = tokens >= MAX_CHUNK_TOKENS

        if (is_boundary and is_full) or tokens >= HARD_CHUNK_TOKENS:
            chunks.append(_chunk_of(current, start, number, path, symbol))
            current = []
            start = number + 1

    if any(line.strip() for line in current):
        chunks.append(_chunk_of(current, start, len(lines), path, symbol))

    return chunks


def _chunk_of(
    lines: list[str],
    start: int,
    end: int,
    path: str,
    symbol: CodeSymbol,
) -> CodeChunk:
    text = "\n".join(lines).strip("\n")
    return CodeChunk(
        id=CodeChunkId(uuid4()),
        symbol_id=symbol.id,
        content=text,
        content_hash=content_hash(text),
        start_line=start,
        end_line=max(end, start),
        token_count=estimate_tokens(text),
        breadcrumb=path,
    )
