from ducktective.core.diff.entities import (
    Diff,
    DiffFile,
)
from ducktective.core.diff.value_objects import (
    ChangeType,
)
from ducktective.core.types import (
    CommitSha,
)


PATHS = (
    "src/ssuz/report/builder.py",
    "src/ssuz/report/tests/test_builder.py",
    "src/ssuz/admin/views.py",
    "docs/changelog.md",
)


def build_diff() -> Diff:
    return Diff(
        base_sha=CommitSha("a" * 40),
        head_sha=CommitSha("b" * 40),
        files=[
            DiffFile(path=path, change_type=ChangeType.MODIFIED, added_lines=1) for path in PATHS
        ],
    )


def paths_after(*patterns: str) -> list[str]:
    return [file.path for file in build_diff().include_only(patterns).files]


def test_without_patterns_diff_is_unchanged() -> None:
    assert paths_after() == list(PATHS)


def test_directory_pattern_matches_at_any_depth() -> None:
    assert paths_after("src/ssuz/report/*") == [
        "src/ssuz/report/builder.py",
        "src/ssuz/report/tests/test_builder.py",
    ]


def test_extension_pattern() -> None:
    assert paths_after("*.md") == ["docs/changelog.md"]


def test_several_patterns_are_combined() -> None:
    assert paths_after("*/admin/*", "*.md") == [
        "src/ssuz/admin/views.py",
        "docs/changelog.md",
    ]


def test_exact_path_matches_single_file() -> None:
    assert paths_after("src/ssuz/admin/views.py") == ["src/ssuz/admin/views.py"]


def test_pattern_without_matches_gives_empty_diff() -> None:
    filtered = build_diff().include_only(("src/nowhere/*",))

    assert filtered.is_empty
    assert filtered.base_sha == CommitSha("a" * 40)
