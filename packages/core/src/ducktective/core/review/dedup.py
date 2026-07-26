import hashlib
import re

from ducktective.core.review.value_objects import (
    FindingCategory,
)


WHITESPACE_PATTERN = re.compile(r"\s+")


def build_dedup_key(
    *,
    category: FindingCategory,
    rule_id: str | None,
    symbol_name: str | None,
    file_path: str,
    code_fragment: str,
) -> str:
    """Ключ дедупликации находки.

    Номер строки в ключ намеренно не входит: после доработки PR код сдвигается,
    и привязка к строке приводила бы к повторному показу уже отклонённых находок.
    """
    normalized_fragment = WHITESPACE_PATTERN.sub(" ", code_fragment).strip()
    anchor = symbol_name or file_path
    payload = "\x1f".join([category.value, rule_id or "", anchor, normalized_fragment])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
