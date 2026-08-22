from ducktective.core.indexing.search import (
    MAX_EXTRA_TOKENS,
    build_search_text,
)


def tokens_of(*parts: str | None) -> set[str]:
    return set(build_search_text(*parts).split())


def test_camel_case_is_split_into_words() -> None:
    """Полнотекстовый разбор Postgres этого не делает, а поиск по части имени нужен."""
    tokens = tokens_of("class ReviewRun:")

    assert "review" in tokens
    assert "run" in tokens


def test_snake_case_parts_are_added_too() -> None:
    tokens = tokens_of("def add_finding(self):")

    assert "add" in tokens
    assert "finding" in tokens


def test_acronyms_are_split_at_the_last_capital() -> None:
    tokens = tokens_of("class HTTPClient:")

    assert "http" in tokens
    assert "client" in tokens


def test_original_text_survives() -> None:
    assert "add_finding" in build_search_text("def add_finding(self):")


def test_single_letters_are_dropped() -> None:
    assert "x" not in tokens_of("def f(x):")


def test_whole_identifier_is_not_duplicated() -> None:
    """Слово, совпадающее с самим именем, добавлять незачем."""
    text = build_search_text("finding")

    assert text.split().count("finding") == 1


def test_parts_are_joined() -> None:
    text = build_search_text("app.report", "def build(self)", "Собирает отчёт")

    assert "app.report" in text
    assert "def build(self)" in text
    assert "Собирает отчёт" in text


def test_empty_parts_are_skipped() -> None:
    assert build_search_text(None, "", "value") == "value"


def test_extra_tokens_are_capped() -> None:
    """У длинного файла список частей перерастает сам текст."""
    source = " ".join(f"someVeryLongName{number}" for number in range(500))

    extra = build_search_text(source).removeprefix(source).split()

    assert len(extra) <= MAX_EXTRA_TOKENS


def test_text_without_identifiers_is_returned_as_is() -> None:
    assert build_search_text("дедупликация находок") == "дедупликация находок"
