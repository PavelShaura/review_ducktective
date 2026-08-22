from uuid import (
    uuid4,
)

import pytest

from ducktective.core.chat.documents import (
    MAX_PASSAGE_CHARS,
    plain_text,
    select_passages,
    split_passages,
)
from ducktective.core.chat.entities import (
    MAX_DOCUMENT_CHARS,
    Conversation,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


SPECIFICATION = """Требование 3.1. Выбор филиала

Читатель выбирает филиал из справочника. Закрытые филиалы
не показываются в списке.

Требование 3.2. Печать справки

Справка печатается в PDF и подписывается электронной подписью.

Общие положения

Система должна работать круглосуточно."""


def build_conversation() -> Conversation:
    return Conversation.start(tenant_id=TenantId(uuid4()), repository_id=RepositoryId(uuid4()))


def test_attached_document_replaces_the_previous_one() -> None:
    """Приложить второй значит передумать насчёт первого (D-025)."""
    conversation = build_conversation()

    conversation.attach("первое.md", "текст требования")
    conversation.attach("второе.md", "другое требование")

    assert conversation.document is not None
    assert conversation.document.name == "второе.md"


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty_document_is_refused(text: str) -> None:
    conversation = build_conversation()

    with pytest.raises(InvariantViolationError):
        conversation.attach("пустой.md", text)


def test_book_sized_document_is_refused() -> None:
    """Четыреста тысяч знаков — это книга, и приложивший её ошибся файлом."""
    conversation = build_conversation()

    with pytest.raises(InvariantViolationError):
        conversation.attach("книга.md", "х" * (MAX_DOCUMENT_CHARS + 1))


def test_detached_document_is_gone() -> None:
    conversation = build_conversation()
    conversation.attach("требование.md", "текст")

    conversation.detach()

    assert not conversation.has_document


def test_passages_are_found_across_word_forms() -> None:
    """Документ по-русски, вопрос тоже: «филиал» против «филиала»."""
    found = select_passages(SPECIFICATION, "как выбирается филиал?")

    assert found
    assert "выбирает филиал" in found[0].text


def test_question_untouched_by_the_document_gets_nothing() -> None:
    """Пустой ответ честнее первого попавшегося абзаца."""
    assert select_passages(SPECIFICATION, "блокчейн и криптовалюта") == []


def test_rare_words_weigh_more_than_common_ones() -> None:
    """Слово из каждого абзаца не отличает ничего, редкое — отличает сильно."""
    found = select_passages(SPECIFICATION, "требование про печать справки")

    assert "Справка печатается" in found[0].text


def test_long_passage_is_clipped() -> None:
    """Абзац требований бывает страницей и вытеснил бы и соседей, и код."""
    document = f"Заголовок\n\n{'слово филиалов ' * 400}"

    found = select_passages(document, "филиалов")

    assert len(found[0].text) <= MAX_PASSAGE_CHARS + 1


def test_html_export_loses_tags_but_keeps_paragraphs() -> None:
    """Выгрузка из Confluence приходит страницей, а нужны из неё абзацы."""
    page = (
        "<html><head><style>p{color:red}</style></head><body>"
        "<h1>Требование 3.1</h1><p>Выбор филиала из справочника.</p>"
        "<p>Закрытые не показываются &mdash; совсем.</p></body></html>"
    )

    text = plain_text(page)

    assert "<" not in text
    assert "color:red" not in text
    assert "—" in text
    assert len(split_passages(text)) == 3


def test_plain_text_passes_through_untouched() -> None:
    assert plain_text(SPECIFICATION) == SPECIFICATION
