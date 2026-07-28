import re


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

MAX_EXTRA_TOKENS = 200


def build_search_text(*parts: str | None) -> str:
    """Готовит текст для лексического поиска по коду.

    К исходному тексту добавляются части составных имён: полнотекстовый
    разбор Postgres делит `add_finding` по подчёркиванию, но `ReviewRun`
    оставляет одним словом, и запрос «Review» такой символ не находит.

    Число добавленных слов ограничено: у длинного файла список частей
    вырастает больше самого текста, а ценность добавки быстро падает.
    """
    text = "\n".join(part for part in parts if part)
    extra = _split_identifiers(text)
    return f"{text}\n{' '.join(extra)}" if extra else text


def _split_identifiers(text: str) -> list[str]:
    seen: dict[str, None] = {}

    for match in IDENTIFIER.finditer(text):
        identifier = match.group()
        for word in _words_of(identifier):
            if len(word) > 1 and word.lower() != identifier.lower():
                seen.setdefault(word.lower(), None)
        if len(seen) >= MAX_EXTRA_TOKENS:
            break

    return list(seen)[:MAX_EXTRA_TOKENS]


def _words_of(identifier: str) -> list[str]:
    return [
        word
        for chunk in identifier.split("_")
        if chunk
        for word in CAMEL_BOUNDARY.split(chunk)
        if word
    ]
