import subprocess
from pathlib import (
    Path,
)

import pytest

from ducktective.core.retrieval.navigation import (
    FragmentRole,
    NavigationSource,
)
from ducktective.vcs.git_provider import (
    LocalGitProvider,
)
from ducktective.vcs.navigation import (
    GitCodeNavigator,
)


REPORT = """class ReportBuilder:
    def build_total(self, rows):
        return sum(row.amount for row in rows)


def render(rows):
    builder = ReportBuilder()
    return builder.build_total(rows)
"""

API = """from app.report import ReportBuilder


def handle(request):
    builder = ReportBuilder()
    total = builder.build_total(request.rows)
    return {"total": total}
"""


def run_git(repository_path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_path), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.email", "test@local")
    run_git(tmp_path, "config", "user.name", "test")

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "report.py").write_text(REPORT, encoding="utf-8")
    (tmp_path / "app" / "api.py").write_text(API, encoding="utf-8")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def navigator(repository: Path, revision: str = "HEAD") -> GitCodeNavigator:
    return GitCodeNavigator(repository, revision, git=LocalGitProvider())


async def test_search_finds_lines_of_the_revision(repository: Path) -> None:
    answer = await navigator(repository).search_code("build_total")

    assert answer.source is NavigationSource.GIT
    assert {fragment.path for fragment in answer.fragments} == {"app/report.py", "app/api.py"}
    assert all(fragment.role is FragmentRole.MATCH for fragment in answer.fragments)


async def test_answer_admits_that_the_search_is_lexical(repository: Path) -> None:
    """Пустой греп и пустой обход графа выглядят одинаково, а значат разное."""
    answer = await navigator(repository).search_code("ничего такого нет")

    assert answer.is_empty
    assert answer.note is not None
    assert "Индекса нет" in answer.note


async def test_definition_shows_the_body_after_the_signature(repository: Path) -> None:
    answer = await navigator(repository).get_definition("ReportBuilder.build_total")

    assert answer.fragments
    assert "def build_total" in answer.fragments[0].text
    assert "return sum(row.amount for row in rows)" in answer.fragments[0].text
    assert answer.fragments[0].role is FragmentRole.DEFINITION


async def test_definition_is_looked_up_by_the_last_segment(repository: Path) -> None:
    """`ReportBuilder.build_total` в коде так не пишется нигде, кроме вызова."""
    answer = await navigator(repository).get_definition("app.report.ReportBuilder.build_total")

    assert [fragment.path for fragment in answer.fragments] == ["app/report.py"]


async def test_callers_exclude_the_definition_itself(repository: Path) -> None:
    answer = await navigator(repository).find_callers("build_total")

    assert answer.fragments
    assert all("def build_total" not in fragment.text for fragment in answer.fragments)
    assert {fragment.path for fragment in answer.fragments} == {"app/report.py", "app/api.py"}


async def test_stale_index_is_named_as_the_reason(repository: Path) -> None:
    """«Индекса нет» и «индекс на другом коммите» — разные новости для модели."""
    navigator = GitCodeNavigator(
        repository,
        "HEAD",
        git=LocalGitProvider(),
        reason="индекс собран на другой ревизии (f7f877d5)",
    )

    answer = await navigator.find_callers("build_total")

    assert answer.note is not None
    assert "другой ревизии" in answer.note


async def test_callers_warn_about_namesakes(repository: Path) -> None:
    answer = await navigator(repository).find_callers("build_total")

    assert answer.note is not None
    assert "Однофамильцы" in answer.note


async def test_file_context_returns_a_window_around_the_lines(repository: Path) -> None:
    answer = await navigator(repository).get_file_context(
        "app/api.py",
        start_line=5,
        end_line=6,
    )

    assert answer.fragments[0].start_line == 1
    assert "def handle(request)" in answer.fragments[0].text


async def test_missing_file_is_named_instead_of_returning_nothing(repository: Path) -> None:
    answer = await navigator(repository).get_file_context(
        "app/gone.py",
        start_line=1,
        end_line=2,
    )

    assert answer.is_empty
    assert answer.note is not None
    assert "app/gone.py" in answer.note


async def test_navigation_reads_the_revision_and_not_the_working_copy(repository: Path) -> None:
    """Ревизия зафиксирована: eval-прогон обязан повторяться (D-021)."""
    (repository / "app" / "report.py").write_text(
        REPORT.replace("build_total", "build_grand_total"),
        encoding="utf-8",
    )

    answer = await navigator(repository).get_definition("build_total")

    assert answer.fragments
    assert "def build_total" in answer.fragments[0].text


async def test_unknown_revision_answers_instead_of_failing(repository: Path) -> None:
    """Сбой git — не повод ронять расследование: модели нужен ответ, а не исключение."""
    answer = await navigator(repository, revision="0000000").search_code("build_total")

    assert answer.is_empty
