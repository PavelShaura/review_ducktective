from collections.abc import (
    Collection,
    Iterable,
)

from ducktective.core.retrieval.context import (
    ContextOrigin,
    DiffContext,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.review.reviewers import (
    ReviewerKind,
)


TEST_PATH_MARKERS = ("/tests/", "/test/", "__tests__/", "spec/")
TEST_NAME_MARKERS = ("test_", "_test.", ".test.", ".spec.")

SECURITY_PATH_MARKERS = (
    "auth",
    "login",
    "permission",
    "role",
    "security",
    "crypto",
    "session",
    "secret",
    "token",
    "password",
    "middleware",
    "payment",
)

SECURITY_CODE_MARKERS = (
    "subprocess",
    "os.system",
    "eval(",
    "exec(",
    "pickle",
    "yaml.load",
    "shell=true",
    "verify=false",
    "innerhtml",
    "execute(",
    "cursor",
    "sql",
    "os.environ",
    "getenv",
    "password",
    "secret",
    "token",
    "api_key",
    "jwt",
    "hashlib",
    "md5",
    "sha1",
    "urlopen",
    "requests.",
    "httpx",
    "allow_origins",
    "chmod",
)

LOOP_MARKERS = ("for ", "while ")

REMOTE_CALL_MARKERS = (
    "await ",
    "session.",
    "execute(",
    "requests.",
    "httpx",
    "fetch(",
    "open(",
    ".save(",
    ".first()",
    ".get(",
)

QUERY_MARKERS = ("select(", "query(", ".all()", ".scalars(", "fetchall(", "aggregate(")


def select_reviewers(
    file: ReviewFile,
    *,
    context: DiffContext | None = None,
    available: Collection[ReviewerKind] = tuple(ReviewerKind),
) -> tuple[ReviewerKind, ...]:
    """Решает, кого из ревьюеров звать на этот файл.

    Отбор — ограничитель стоимости, а не диспетчер (D-018): при локальной
    модели каждый лишний проход стоит минуты, поэтому специалист зовётся
    по признакам в добавленных строках, а не на всякий случай.

    Признаки ищутся только в добавленных строках: контекстные строки патча
    описывают код, которого изменение не касалось, и звать по ним security
    на каждый файл рядом с чужим `subprocess` — ровно та цена, которую узел
    обязан не платить.

    `correctness` работает всегда: смысл изменения читает он, и файла без
    смысла не бывает. В тестах молчат `security` и `performance` — инъекция
    в фикстуре и запрос в цикле внутри теста не дефекты. `conventions` без
    похожих мест в контексте не зовётся вовсе: сравнивать не с чем, а без
    сравнения он гадает.

    Пустым результат не бывает, пока есть хоть один доступный ревьюер: файл,
    на который никого не позвали, выглядит как файл без замечаний, а это
    ровно та неразличимость, которой прогон не должен допускать.
    """
    added_lines = _added_lines(file)
    selected = [ReviewerKind.CORRECTNESS]

    if not _is_test_file(file.path):
        if _mentions(file.path.lower(), SECURITY_PATH_MARKERS) or _mentions(
            added_lines, SECURITY_CODE_MARKERS
        ):
            selected.append(ReviewerKind.SECURITY)
        if _has_costly_shape(added_lines):
            selected.append(ReviewerKind.PERFORMANCE)

    if _has_similar_places(context):
        selected.append(ReviewerKind.CONVENTIONS)

    planned = tuple(kind for kind in selected if kind in available)
    if planned or not available:
        return planned
    return tuple(kind for kind in ReviewerKind if kind in available)[:1]


def _added_lines(file: ReviewFile) -> str:
    added = [
        line[1:]
        for hunk in file.hunks
        for line in hunk.patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    return "\n".join(added).lower()


def _is_test_file(path: str) -> bool:
    lowered = path.lower()
    name = lowered.rsplit("/", maxsplit=1)[-1]
    return _mentions(lowered, TEST_PATH_MARKERS) or _mentions(name, TEST_NAME_MARKERS)


def _has_costly_shape(added_lines: str) -> bool:
    """Форма, ради которой зовут `performance`.

    Обращение наружу внутри цикла — это N+1, самая частая находка уровня
    major. Новый запрос сам по себе тоже повод: у него спрашивают про индекс
    и про объём выборки, и спросить это больше некому.
    """
    in_loop = _mentions(added_lines, LOOP_MARKERS) and _mentions(added_lines, REMOTE_CALL_MARKERS)
    return in_loop or _mentions(added_lines, QUERY_MARKERS)


def _has_similar_places(context: DiffContext | None) -> bool:
    return context is not None and bool(context.of_origin(ContextOrigin.SIMILAR))


def _mentions(text: str, markers: Iterable[str]) -> bool:
    return any(marker in text for marker in markers)
