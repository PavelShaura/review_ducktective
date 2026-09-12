from ducktective.core.indexing.vectors import (
    deserves_vector,
)


def test_generated_and_vendored_paths_get_no_vector() -> None:
    assert not deserves_vector("app/migrations/0017_add_flag.py")
    assert not deserves_vector("tests/fixtures/users.json")
    assert not deserves_vector("web/static/vendor/lib.js")
    assert not deserves_vector("web/static/app.min.js")
    assert not deserves_vector("locale/ru/LC_MESSAGES/django.po")
    assert not deserves_vector("uv.lock")


def test_ordinary_code_and_docs_do() -> None:
    assert deserves_vector("app/services/chats.py")
    assert deserves_vector("app/migration_helpers.py")
    assert deserves_vector("docs/architecture.md")
    assert deserves_vector("web/static/app.js")
