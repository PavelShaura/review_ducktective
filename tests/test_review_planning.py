from uuid import (
    uuid4,
)

from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewHunk,
)
from ducktective.core.review.planning import (
    AGENTIC_PATCH_CHARS_LIMIT,
    plan_file_review,
)
from ducktective.core.review.reviewers import (
    ReviewMode,
    review_mode_of,
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


def test_ordinary_file_is_read_agentically() -> None:
    assert plan_file_review(build_file()) is ReviewMode.AGENTIC


def test_large_file_falls_back_to_one_pass() -> None:
    """Патч, съедающий окно, не оставляет места на диалог с инструментами."""
    file = build_file(added="    value = compute()" * (AGENTIC_PATCH_CHARS_LIMIT // 10))

    assert plan_file_review(file) is ReviewMode.SINGLE_PASS


def test_only_available_modes_are_planned() -> None:
    assert plan_file_review(build_file(), available=(ReviewMode.SINGLE_PASS,)) is (
        ReviewMode.SINGLE_PASS
    )


def test_without_reviewers_nothing_is_planned() -> None:
    """Файл, на который никого не позвали, неотличим от файла без замечаний."""
    assert plan_file_review(build_file(), available=()) is None


def test_unknown_name_has_no_mode() -> None:
    assert review_mode_of("reviewer:fake") is None
    assert review_mode_of(reviewer_name(ReviewMode.AGENTIC)) is ReviewMode.AGENTIC
