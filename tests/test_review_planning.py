from uuid import (
    uuid4,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.retrieval.context import (
    ContextOrigin,
    ContextPiece,
    DiffContext,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewHunk,
)
from ducktective.core.review.planning import (
    select_reviewers,
)
from ducktective.core.review.reviewers import (
    ReviewerKind,
    reviewer_kind_of,
    reviewer_name,
)
from ducktective.core.types import (
    ReviewFileId,
    ReviewHunkId,
)


def build_file(*, path: str = "app/service.py", added: str = "    return result") -> ReviewFile:
    body = "".join(f"+{line}\n" for line in added.splitlines())
    return ReviewFile(
        id=ReviewFileId(uuid4()),
        path=path,
        previous_path=None,
        change_type=ChangeType.MODIFIED,
        language="python",
        added_lines=len(body.splitlines()),
        removed_lines=0,
        hunks=[
            ReviewHunk(
                id=ReviewHunkId(uuid4()),
                old_start=10,
                old_lines=2,
                new_start=10,
                new_lines=3,
                header="class ReportBuilder:",
                patch_text=f"@@ -10,2 +10,3 @@\n     context_line = 1\n{body}",
            )
        ],
    )


def build_context(*origins: ContextOrigin) -> DiffContext:
    return DiffContext(
        path="app/service.py",
        pieces=tuple(
            ContextPiece(
                origin=origin,
                path="app/other.py",
                qualified_name=None,
                start_line=1,
                end_line=2,
                text="def other():\n    return 1",
                token_count=8,
            )
            for origin in origins
        ),
    )


def test_correctness_reads_every_file() -> None:
    assert select_reviewers(build_file()) == (ReviewerKind.CORRECTNESS,)


def test_security_is_called_by_path() -> None:
    selected = select_reviewers(build_file(path="app/auth/tokens.py"))

    assert ReviewerKind.SECURITY in selected


def test_security_is_called_by_added_code() -> None:
    selected = select_reviewers(build_file(added="    subprocess.run(command, shell=True)"))

    assert ReviewerKind.SECURITY in selected


def test_untouched_neighbouring_code_does_not_call_security() -> None:
    """Признаки ищутся в добавленных строках: контекст патча — не изменение."""
    file = build_file()
    hunk = file.hunks[0]
    hunk.patch_text = "@@ -10,2 +10,3 @@\n     subprocess.run(command)\n+    return result\n"

    assert select_reviewers(file) == (ReviewerKind.CORRECTNESS,)


def test_performance_is_called_on_a_query_inside_a_loop() -> None:
    selected = select_reviewers(
        build_file(added="    for item in items:\n        await session.get(Order, item.id)")
    )

    assert ReviewerKind.PERFORMANCE in selected


def test_plain_loop_alone_does_not_call_performance() -> None:
    selected = select_reviewers(
        build_file(added="    for value in values:\n        total += value")
    )

    assert ReviewerKind.PERFORMANCE not in selected


def test_conventions_waits_for_similar_places() -> None:
    without = select_reviewers(build_file(), context=build_context(ContextOrigin.CALLER))
    with_similar = select_reviewers(build_file(), context=build_context(ContextOrigin.SIMILAR))

    assert ReviewerKind.CONVENTIONS not in without
    assert ReviewerKind.CONVENTIONS in with_similar


def test_tests_are_left_to_correctness_alone() -> None:
    """Инъекция в фикстуре и запрос в цикле внутри теста — не дефекты."""
    selected = select_reviewers(
        build_file(
            path="tests/test_orders.py",
            added="    for row in rows:\n        session.execute(text(query))",
        )
    )

    assert selected == (ReviewerKind.CORRECTNESS,)


def test_file_is_never_left_without_a_reviewer() -> None:
    """Файл, на который никого не позвали, неотличим от файла без замечаний."""
    selected = select_reviewers(build_file(), available=(ReviewerKind.SECURITY,))

    assert selected == (ReviewerKind.SECURITY,)


def test_unknown_name_has_no_specialisation() -> None:
    assert reviewer_kind_of("reviewer:fake") is None
    assert reviewer_kind_of(reviewer_name(ReviewerKind.SECURITY)) is ReviewerKind.SECURITY
