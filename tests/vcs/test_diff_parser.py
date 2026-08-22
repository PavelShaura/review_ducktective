import pytest

from ducktective.core.diff.entities import (
    Diff,
)
from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.exceptions import (
    DiffParsingError,
)
from ducktective.core.types import (
    CommitSha,
)
from ducktective.vcs.diff_parser import (
    UnifiedDiffParser,
)
from tests.diff_fixtures import (
    BROKEN_PATCH,
    DELETED_PATCH,
    MODIFIED_AND_ADDED_PATCH,
    RENAMED_PATCH,
)


BASE_SHA = CommitSha("a" * 40)
HEAD_SHA = CommitSha("b" * 40)


def parse(patch_text: str) -> Diff:
    return UnifiedDiffParser().parse(patch_text, base_sha=BASE_SHA, head_sha=HEAD_SHA)


def test_empty_patch_produces_empty_diff() -> None:
    diff = parse("")

    assert diff.is_empty
    assert diff.base_sha == BASE_SHA


def test_modified_and_added_files_are_recognised() -> None:
    diff = parse(MODIFIED_AND_ADDED_PATCH)

    paths = [file.path for file in diff.files]
    change_types = [file.change_type for file in diff.files]

    assert paths == ["app/service.py", "app/helpers.py"]
    assert change_types == [ChangeType.MODIFIED, ChangeType.ADDED]


def test_line_counters_are_collected() -> None:
    diff = parse(MODIFIED_AND_ADDED_PATCH)

    assert diff.added_lines == 4
    assert diff.removed_lines == 1


def test_language_is_detected_from_extension() -> None:
    diff = parse(MODIFIED_AND_ADDED_PATCH)

    assert {file.language for file in diff.files} == {"python"}


def test_hunk_ranges_match_patch_header() -> None:
    diff = parse(MODIFIED_AND_ADDED_PATCH)
    hunk = diff.files[0].hunks[0]

    assert hunk.old_start == 10
    assert hunk.old_lines == 2
    assert hunk.new_start == 10
    assert hunk.new_lines == 3
    assert hunk.new_range is not None
    assert hunk.new_range.contains(12)


def test_rename_keeps_previous_path() -> None:
    diff = parse(RENAMED_PATCH)
    file = diff.files[0]

    assert file.change_type is ChangeType.RENAMED
    assert file.path == "app/new_name.py"
    assert file.previous_path == "app/old_name.py"


def test_deleted_file_is_not_reviewable() -> None:
    diff = parse(DELETED_PATCH)
    file = diff.files[0]

    assert file.change_type is ChangeType.DELETED
    assert file.is_reviewable is False
    assert diff.reviewable_files() == []


def test_broken_patch_raises_domain_error() -> None:
    with pytest.raises(DiffParsingError):
        parse(BROKEN_PATCH)
