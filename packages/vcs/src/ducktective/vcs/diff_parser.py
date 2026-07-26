from unidiff.errors import (
    UnidiffParseError,
)
from unidiff.patch import (
    PatchedFile,
    PatchSet,
)

from ducktective.core.diff.entities import (
    Diff,
    DiffFile,
    DiffHunk,
)
from ducktective.core.diff.languages import (
    detect_language,
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


SOURCE_PREFIX = "a/"


class UnifiedDiffParser:
    """Разбор unified diff в доменные объекты на базе unidiff."""

    def parse(self, patch_text: str, *, base_sha: CommitSha, head_sha: CommitSha) -> Diff:
        if not patch_text.strip():
            return Diff(base_sha=base_sha, head_sha=head_sha, files=[])

        try:
            patch_set = PatchSet(patch_text)
        except UnidiffParseError as error:
            raise DiffParsingError(f"Не удалось разобрать патч: {error}") from error

        return Diff(
            base_sha=base_sha,
            head_sha=head_sha,
            files=[self._build_file(patched_file) for patched_file in patch_set],
        )

    def _build_file(self, patched_file: PatchedFile) -> DiffFile:
        path = patched_file.path

        return DiffFile(
            path=path,
            previous_path=self._previous_path(patched_file),
            change_type=self._change_type(patched_file),
            language=detect_language(path),
            added_lines=patched_file.added,
            removed_lines=patched_file.removed,
            hunks=[
                DiffHunk(
                    old_start=hunk.source_start,
                    old_lines=hunk.source_length,
                    new_start=hunk.target_start,
                    new_lines=hunk.target_length,
                    header=hunk.section_header or "",
                    patch_text=str(hunk),
                )
                for hunk in patched_file
            ],
        )

    def _change_type(self, patched_file: PatchedFile) -> ChangeType:
        if patched_file.is_rename:
            return ChangeType.RENAMED
        if patched_file.is_added_file:
            return ChangeType.ADDED
        if patched_file.is_removed_file:
            return ChangeType.DELETED
        return ChangeType.MODIFIED

    def _previous_path(self, patched_file: PatchedFile) -> str | None:
        if not patched_file.is_rename:
            return None
        return _strip_prefix(patched_file.source_file, SOURCE_PREFIX)


def _strip_prefix(path: str, prefix: str) -> str:
    return path[len(prefix) :] if path.startswith(prefix) else path
