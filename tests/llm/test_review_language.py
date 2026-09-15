from ducktective.core.review.trace import (
    TRACE,
    trace,
)
from ducktective.core.review.value_objects import (
    ReviewLanguage,
)
from ducktective.llm.code_reviewer import (
    LANGUAGE_PLACEHOLDER,
    system_prompt,
)


def test_findings_language_is_substituted_into_the_prompt() -> None:
    """Подсказка одна, а дело читают на языке того, кто его завёл."""
    russian = system_prompt(language=ReviewLanguage.RU)
    english = system_prompt(language=ReviewLanguage.EN)

    assert "must be written in Russian" in russian
    assert "must be written in English" in english
    assert LANGUAGE_PLACEHOLDER not in russian
    assert LANGUAGE_PLACEHOLDER not in english


def test_agent_prompt_carries_the_language_too() -> None:
    assert "must be written in English" in system_prompt(
        with_tools=True, language=ReviewLanguage.EN
    )


def test_russian_stays_the_default() -> None:
    """Старые вызовы без языка и старые прогоны без поля — русские."""
    assert "must be written in Russian" in system_prompt()


def test_trace_lines_follow_the_language_of_the_run() -> None:
    """Ленту читает человек — на языке, на котором завёл дело."""
    assert trace(ReviewLanguage.RU, "asking_model", attempt=3) == "Спрашиваю модель, обращение 3"
    assert trace(ReviewLanguage.EN, "asking_model", attempt=3) == "Asking the model, call 3"


def test_every_trace_phrase_exists_in_both_languages() -> None:
    for key, phrases in TRACE.items():
        assert set(phrases) == set(ReviewLanguage), key
